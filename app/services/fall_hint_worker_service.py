from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import DetectionSnapshot, RealtimeResultStore
from app.detection.yolo_fall_detector import FallDetectorLockBusy, YoloFallDetector
from app.monitoring.metrics import FPSMeter
from app.schemas.common import utc_now_iso

logger = get_logger(__name__)


@dataclass
class FallHintWorkerStatus:
    camera_id: str
    enabled: bool
    running: bool
    loaded: bool
    model_name: str | None
    state: str = "disabled"
    writer_source: str = "none"
    fps: float = 0.0
    last_frame_seq: int | None = None
    last_latency_ms: float | None = None
    avg_latency_ms: float | None = None
    result_age_ms: float | None = None
    input_frame_age_ms: float | None = None
    skipped_duplicate_frame_count: int = 0
    skipped_stale_frame_count: int = 0
    skipped_lock_busy_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    consecutive_error_count: int = 0
    circuit_open: bool = False
    circuit_cooldown_remaining_ms: float | None = None
    last_error: str | None = None
    latest_fall_model_count: int = 0
    latest_fall_labels: list[str] | None = None
    latest_fall_confidences: list[float] | None = None
    latest_fall_boxes: list[list[float]] | None = None


@dataclass
class _FallHintStats:
    last_frame_seq: int | None = None
    last_latency_ms: float | None = None
    avg_latency_ms: float | None = None
    input_frame_age_ms: float | None = None
    last_success_monotonic: float | None = None
    skipped_duplicate_frame_count: int = 0
    skipped_stale_frame_count: int = 0
    skipped_lock_busy_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    consecutive_error_count: int = 0
    circuit_open_until: float | None = None
    last_error: str | None = None
    latest_fall_model_count: int = 0
    latest_fall_labels: list[str] | None = None
    latest_fall_confidences: list[float] | None = None
    latest_fall_boxes: list[list[float]] | None = None


class FallHintWorkerService:
    def __init__(
        self,
        settings: Settings,
        source_manager: CameraSourceManager,
        realtime_store: RealtimeResultStore,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.realtime_store = realtime_store
        self.detector = YoloFallDetector(settings) if self._configured_enabled else None
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._stats: dict[str, _FallHintStats] = {}
        self._lock = threading.Lock()

    @property
    def _configured_enabled(self) -> bool:
        return bool(
            self.settings.fall_detector_enabled
            and self.settings.pipeline_mode == "async_v1"
            and self.settings.fall_hint_worker_enabled
        )

    def start_for_camera(self, camera_id: str) -> None:
        if not self._configured_enabled:
            return
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"fall-hint-worker-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._stats[camera_id] = _FallHintStats()
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

    def status(self, camera_id: str) -> FallHintWorkerStatus:
        detector_status = self.detector.status() if self.detector is not None else None
        with self._lock:
            worker = self._workers.get(camera_id)
            fps = self._fps.get(camera_id)
            stats = self._stats.get(camera_id, _FallHintStats())
        running = bool(worker and worker.is_alive())
        result_age_ms = None
        if stats.last_success_monotonic is not None:
            result_age_ms = round((time.monotonic() - stats.last_success_monotonic) * 1000, 2)
        circuit_remaining = self._circuit_remaining_ms(stats)
        state = self._state(running=running, stats=stats, result_age_ms=result_age_ms)
        return FallHintWorkerStatus(
            camera_id=camera_id,
            enabled=self._configured_enabled,
            running=running,
            loaded=bool(detector_status and detector_status.loaded),
            model_name=detector_status.model_name if detector_status else None,
            state=state,
            writer_source="FallHintWorkerService" if self._configured_enabled else "none",
            fps=fps.fps if fps else 0.0,
            last_frame_seq=stats.last_frame_seq,
            last_latency_ms=stats.last_latency_ms,
            avg_latency_ms=stats.avg_latency_ms,
            result_age_ms=result_age_ms,
            input_frame_age_ms=stats.input_frame_age_ms,
            skipped_duplicate_frame_count=stats.skipped_duplicate_frame_count,
            skipped_stale_frame_count=stats.skipped_stale_frame_count,
            skipped_lock_busy_count=stats.skipped_lock_busy_count,
            timeout_count=stats.timeout_count,
            error_count=stats.error_count,
            consecutive_error_count=stats.consecutive_error_count,
            circuit_open=circuit_remaining is not None,
            circuit_cooldown_remaining_ms=circuit_remaining,
            last_error=stats.last_error or (detector_status.last_error if detector_status else None),
            latest_fall_model_count=stats.latest_fall_model_count,
            latest_fall_labels=stats.latest_fall_labels,
            latest_fall_confidences=stats.latest_fall_confidences,
            latest_fall_boxes=stats.latest_fall_boxes,
        )

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.fall_hint_worker_fps, 0.1)
        next_tick = time.perf_counter()
        last_seq = 0
        logger.info("fall_hint_worker_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            delay = next_tick - time.perf_counter()
            if delay > 0:
                stop_event.wait(delay)
            next_tick += interval
            last_seq = self._tick(camera_id, last_seq)
        logger.info("fall_hint_worker_stopped camera_id=%s", camera_id)

    def _tick(self, camera_id: str, last_seq: int) -> int:
        buffer = self.source_manager.get_buffer(camera_id)
        if buffer is None:
            return last_seq
        packet = buffer.latest()
        if packet is None:
            return last_seq
        with self._lock:
            stats = self._stats.setdefault(camera_id, _FallHintStats())
            if packet.seq == last_seq:
                stats.skipped_duplicate_frame_count += 1
                return last_seq
            stats.input_frame_age_ms = packet.age_ms
            if packet.age_ms > self.settings.fall_hint_max_frame_age_ms:
                stats.skipped_stale_frame_count += 1
                return packet.seq
            if self._circuit_remaining_ms(stats) is not None:
                return packet.seq

        started = time.perf_counter()
        try:
            if self.detector is None:
                return packet.seq
            objects = self.detector.detect(
                packet.frame,
                lock_timeout_ms=self.settings.fall_hint_inference_lock_wait_ms,
                skip_if_busy=self.settings.fall_hint_skip_if_inference_busy,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            self.realtime_store.update_fall_detection(
                DetectionSnapshot(
                    camera_id=camera_id,
                    timestamp=utc_now_iso(),
                    frame_seq=packet.seq,
                    frame_width=packet.width,
                    frame_height=packet.height,
                    monotonic_at=time.monotonic(),
                    frame=packet.frame,
                    objects=objects,
                    detector={
                        "name": "ultralytics_yolo_fall",
                        "mode": "fall_hint",
                        "source_worker": "FallHintWorkerService",
                        "writer_source": "FallHintWorkerService",
                        "latency_ms": latency_ms,
                        "input_frame_age_ms": packet.age_ms,
                        "result_ttl_ms": self.settings.fall_hint_result_ttl_ms,
                        "model_name": self.detector.status().model_name,
                    },
                )
            )
            with self._lock:
                fps = self._fps.setdefault(camera_id, FPSMeter())
                stats = self._stats.setdefault(camera_id, _FallHintStats())
                fps.tick()
                stats.last_frame_seq = packet.seq
                stats.last_latency_ms = latency_ms
                stats.avg_latency_ms = (
                    latency_ms
                    if stats.avg_latency_ms is None
                    else round((stats.avg_latency_ms * 0.8) + (latency_ms * 0.2), 2)
                )
                stats.last_success_monotonic = time.monotonic()
                stats.last_error = None
                stats.consecutive_error_count = 0
                stats.latest_fall_model_count = len(objects)
                stats.latest_fall_labels = [str(item.label) for item in objects]
                stats.latest_fall_confidences = [float(item.confidence) for item in objects]
                stats.latest_fall_boxes = [[float(value) for value in item.bbox] for item in objects]
        except FallDetectorLockBusy:
            with self._lock:
                self._stats.setdefault(camera_id, _FallHintStats()).skipped_lock_busy_count += 1
        except Exception as exc:
            logger.exception("fall_hint_worker_error camera_id=%s", camera_id)
            with self._lock:
                stats = self._stats.setdefault(camera_id, _FallHintStats())
                stats.error_count += 1
                stats.consecutive_error_count += 1
                stats.last_error = str(exc)
                if (
                    self.settings.fall_hint_circuit_breaker_enabled
                    and stats.consecutive_error_count >= self.settings.fall_hint_circuit_failure_threshold
                ):
                    stats.circuit_open_until = time.monotonic() + (
                        self.settings.fall_hint_circuit_cooldown_ms / 1000
                    )
        return packet.seq

    def _circuit_remaining_ms(self, stats: _FallHintStats) -> float | None:
        if stats.circuit_open_until is None:
            return None
        remaining_ms = (stats.circuit_open_until - time.monotonic()) * 1000
        if remaining_ms <= 0:
            stats.circuit_open_until = None
            stats.consecutive_error_count = 0
            return None
        return round(remaining_ms, 2)

    def _state(self, *, running: bool, stats: _FallHintStats, result_age_ms: float | None) -> str:
        if not self._configured_enabled:
            return "disabled"
        if not running:
            return "stopped"
        if self._circuit_remaining_ms(stats) is not None:
            return "circuit_open"
        if stats.last_error:
            return "degraded"
        if result_age_ms is not None and result_age_ms > self.settings.fall_hint_result_ttl_ms:
            return "stale"
        return "healthy"
