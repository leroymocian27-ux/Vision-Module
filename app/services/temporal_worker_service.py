from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import ObjectSnapshot, RealtimeResultStore
from app.monitoring.metrics import FPSMeter
from app.schemas.vision_result import DetectedObject
from app.services.temporal_service import TemporalService

logger = get_logger(__name__)


@dataclass
class TemporalWorkerStatus:
    camera_id: str
    enabled: bool
    running: bool
    fps: float = 0.0
    last_latency_ms: float | None = None
    result_age_ms: float | None = None
    last_frame_seq: int | None = None
    skipped_duplicate_frame_count: int = 0
    skipped_stale_input_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    state: str = "disabled"


@dataclass
class _TemporalWorkerStats:
    last_latency_ms: float | None = None
    last_success_monotonic: float | None = None
    last_frame_seq: int | None = None
    skipped_duplicate_frame_count: int = 0
    skipped_stale_input_count: int = 0
    error_count: int = 0
    last_error: str | None = None


class TemporalWorkerService:
    def __init__(
        self,
        settings: Settings,
        realtime_store: RealtimeResultStore,
        temporal_service: TemporalService,
    ) -> None:
        self.settings = settings
        self.realtime_store = realtime_store
        self.temporal_service = temporal_service
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._stats: dict[str, _TemporalWorkerStats] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enable_temporal and self.settings.temporal_worker_enabled)

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
                name=f"temporal-worker-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._stats[camera_id] = _TemporalWorkerStats()
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

    def status(self, camera_id: str) -> TemporalWorkerStatus:
        with self._lock:
            worker = self._workers.get(camera_id)
            fps = self._fps.get(camera_id)
            stats = self._stats.get(camera_id, _TemporalWorkerStats())
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
        elif result_age_ms is not None and result_age_ms > self.settings.temporal_result_ttl_ms:
            state = "stale"
        else:
            state = "healthy"
        return TemporalWorkerStatus(
            camera_id=camera_id,
            enabled=self.enabled,
            running=running,
            fps=fps.fps if fps else 0.0,
            last_latency_ms=stats.last_latency_ms,
            result_age_ms=result_age_ms,
            last_frame_seq=stats.last_frame_seq,
            skipped_duplicate_frame_count=stats.skipped_duplicate_frame_count,
            skipped_stale_input_count=stats.skipped_stale_input_count,
            error_count=stats.error_count,
            last_error=stats.last_error,
            state=state,
        )

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.temporal_worker_fps, 0.1)
        next_tick = time.perf_counter()
        logger.info("temporal_worker_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            delay = next_tick - time.perf_counter()
            if delay > 0:
                stop_event.wait(delay)
            next_tick += interval
            self._tick(camera_id)
        logger.info("temporal_worker_stopped camera_id=%s", camera_id)

    def _tick(self, camera_id: str) -> None:
        pipeline = self.realtime_store.snapshot(camera_id)
        base = pipeline.latest_tracking or pipeline.latest_detection
        if base is None:
            return
        age_ms = self.realtime_store.age_ms(base.monotonic_at)
        with self._lock:
            stats = self._stats.setdefault(camera_id, _TemporalWorkerStats())
            if stats.last_frame_seq == base.frame_seq:
                stats.skipped_duplicate_frame_count += 1
                return
            if age_ms is not None and age_ms > self.settings.stream_stale_threshold_ms:
                stats.skipped_stale_input_count += 1
                return

        started = time.perf_counter()
        try:
            objects = list(base.objects)
            objects = self._merge_snapshot(objects, pipeline.latest_pose, base_frame_seq=base.frame_seq, ttl_ms=self.settings.pose_result_ttl_ms)
            objects = self._merge_snapshot(objects, pipeline.latest_behavior, base_frame_seq=base.frame_seq, ttl_ms=self.settings.behavior_result_ttl_ms)
            enriched = self.temporal_service.enrich(camera_id=camera_id, objects=objects)
            self.realtime_store.update_temporal(
                ObjectSnapshot(
                    camera_id=camera_id,
                    frame_seq=base.frame_seq,
                    frame_width=base.frame_width,
                    frame_height=base.frame_height,
                    timestamp=base.timestamp,
                    monotonic_at=time.monotonic(),
                    objects=enriched,
                )
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            with self._lock:
                fps = self._fps.setdefault(camera_id, FPSMeter())
                stats = self._stats.setdefault(camera_id, _TemporalWorkerStats())
                fps.tick()
                stats.last_latency_ms = latency_ms
                stats.last_success_monotonic = time.monotonic()
                stats.last_frame_seq = base.frame_seq
                stats.last_error = None
        except Exception as exc:
            logger.exception("temporal_worker_error camera_id=%s", camera_id)
            with self._lock:
                stats = self._stats.setdefault(camera_id, _TemporalWorkerStats())
                stats.error_count += 1
                stats.last_error = str(exc)

    def _merge_snapshot(
        self,
        objects: list[DetectedObject],
        snapshot: ObjectSnapshot | None,
        *,
        base_frame_seq: int,
        ttl_ms: int,
    ) -> list[DetectedObject]:
        if snapshot is None:
            return objects
        age_ms = self.realtime_store.age_ms(snapshot.monotonic_at)
        if age_ms is not None and age_ms > ttl_ms:
            return objects
        if abs(int(snapshot.frame_seq) - int(base_frame_seq)) > self.settings.temporal_max_frame_delta:
            return objects
        by_track = {item.track_id: item for item in snapshot.objects if item.track_id is not None}
        merged: list[DetectedObject] = []
        for item in objects:
            patch = by_track.get(item.track_id)
            if patch is None:
                merged.append(item)
                continue
            updates = {}
            if patch.pose is not None:
                updates["pose"] = patch.pose
            if patch.behavior is not None:
                updates["behavior"] = patch.behavior
            merged.append(item.model_copy(update=updates) if updates else item)
        return merged
