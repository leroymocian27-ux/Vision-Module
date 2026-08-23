from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import RealtimeResultStore
from app.monitoring.metrics import FPSMeter
from app.services.result_publisher_service import ResultPublisherService

logger = get_logger(__name__)


@dataclass
class FusionWorkerStatus:
    camera_id: str
    enabled: bool
    running: bool
    fps: float = 0.0
    last_latency_ms: float | None = None
    result_age_ms: float | None = None
    last_frame_seq: int | None = None
    skipped_empty_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    state: str = "disabled"


@dataclass
class _FusionWorkerStats:
    last_latency_ms: float | None = None
    last_success_monotonic: float | None = None
    last_frame_seq: int | None = None
    skipped_empty_count: int = 0
    error_count: int = 0
    last_error: str | None = None


class FusionWorkerService:
    def __init__(
        self,
        settings: Settings,
        realtime_store: RealtimeResultStore,
        result_builder: ResultPublisherService,
    ) -> None:
        self.settings = settings
        self.realtime_store = realtime_store
        self.result_builder = result_builder
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._stats: dict[str, _FusionWorkerStats] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.fusion_worker_enabled)

    def start_for_camera(self, camera_id: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"fusion-worker-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._stats[camera_id] = _FusionWorkerStats()
            self._workers[camera_id] = worker
            worker.start()

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            stop_event = self._stops.pop(camera_id, None)
            worker = self._workers.pop(camera_id, None)
            self._fps.pop(camera_id, None)
        if stop_event:
            stop_event.set()
        if worker and worker.is_alive():
            worker.join(timeout=3)

    def stop_all(self) -> None:
        for camera_id in list(self._workers.keys()):
            self.stop_for_camera(camera_id)

    def clear_camera(self, camera_id: str) -> None:
        with self._lock:
            self._stats.pop(camera_id, None)

    def status(self, camera_id: str) -> FusionWorkerStatus:
        with self._lock:
            worker = self._workers.get(camera_id)
            fps = self._fps.get(camera_id)
            stats = self._stats.get(camera_id, _FusionWorkerStats())
        running = bool(worker and worker.is_alive())
        result_age_ms = None
        if stats.last_success_monotonic is not None:
            result_age_ms = round((time.monotonic() - stats.last_success_monotonic) * 1000, 2)
        if not self.enabled:
            state = "disabled"
        elif not running:
            state = "stopped"
        elif stats.last_error:
            state = "degraded"
        elif result_age_ms is not None and result_age_ms > self.settings.fused_result_ttl_ms:
            state = "stale"
        else:
            state = "healthy"
        return FusionWorkerStatus(
            camera_id=camera_id,
            enabled=self.enabled,
            running=running,
            fps=fps.fps if fps else 0.0,
            last_latency_ms=stats.last_latency_ms,
            result_age_ms=result_age_ms,
            last_frame_seq=stats.last_frame_seq,
            skipped_empty_count=stats.skipped_empty_count,
            error_count=stats.error_count,
            last_error=stats.last_error,
            state=state,
        )

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.fusion_worker_fps, 0.1)
        next_tick = time.perf_counter()
        logger.info("fusion_worker_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            delay = next_tick - time.perf_counter()
            if delay > 0:
                stop_event.wait(delay)
            next_tick += interval
            self._tick(camera_id)
        logger.info("fusion_worker_stopped camera_id=%s", camera_id)

    def _tick(self, camera_id: str) -> None:
        started = time.perf_counter()
        try:
            result = self.result_builder.build_result_snapshot(camera_id)
            if result is None:
                with self._lock:
                    self._stats.setdefault(camera_id, _FusionWorkerStats()).skipped_empty_count += 1
                return
            result.detector["_monotonic_at"] = time.monotonic()
            self.realtime_store.update_fused(result)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            with self._lock:
                fps = self._fps.setdefault(camera_id, FPSMeter())
                stats = self._stats.setdefault(camera_id, _FusionWorkerStats())
                fps.tick()
                stats.last_latency_ms = latency_ms
                stats.last_success_monotonic = time.monotonic()
                stats.last_frame_seq = result.frame_seq
                stats.last_error = None
        except Exception as exc:
            logger.exception("fusion_worker_error camera_id=%s", camera_id)
            with self._lock:
                stats = self._stats.setdefault(camera_id, _FusionWorkerStats())
                stats.error_count += 1
                stats.last_error = str(exc)
