from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.camera.frame_buffer import FrameBuffer
from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.object_detector import DetectionRunStats, NoopPersonDetector, PersonDetector, YoloPersonDetector
from app.detection.yolo_fall_detector import YoloFallDetector
from app.detection.realtime_result_store import DetectionSnapshot, RealtimeResultStore
from app.monitoring.metrics import FPSMeter
from app.schemas.common import utc_now_iso
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


@dataclass
class DetectionWorkerStatus:
    camera_id: str
    running: bool
    enabled: bool
    loaded: bool
    model_name: str | None
    detection_fps: float = 0.0
    fall_hint_fps: float = 0.0
    inference_latency_ms: float | None = None
    fall_inference_latency_ms: float | None = None
    pipeline_mode: str = "legacy"
    fall_hint_writer_source: str = "DetectionService"
    last_error: str | None = None
    latest_raw_person_count: int = 0
    latest_fall_model_count: int = 0
    latest_person_boxes: list[list[float]] | None = None
    latest_person_confidences: list[float] | None = None
    latest_fall_labels: list[str] | None = None
    latest_fall_confidences: list[float] | None = None
    latest_fall_boxes: list[list[float]] | None = None


class DetectionService:
    def __init__(
        self,
        settings: Settings,
        source_manager: CameraSourceManager,
        realtime_store: RealtimeResultStore,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.realtime_store = realtime_store
        if settings.pipeline_mode == "post_fall_v2" and not settings.post_fall_v2_aux_person_detection_enabled:
            self.detector: PersonDetector = NoopPersonDetector("disabled in post_fall_v2 mode")
        else:
            self.detector = YoloPersonDetector(settings)
        self.fall_detector = YoloFallDetector(settings) if self._fall_hint_in_detection_enabled else None
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._fall_fps: dict[str, FPSMeter] = {}
        self._stats: dict[str, DetectionRunStats] = {}
        self._last_fall_detection_at: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def _fall_hint_in_detection_enabled(self) -> bool:
        return bool(
            self.settings.fall_detector_enabled
            and self.settings.pipeline_mode == "legacy"
            and self.settings.fall_hint_in_detection_service
        )

    def start_for_camera(self, camera_id: str) -> None:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._fall_fps[camera_id] = FPSMeter()
            self._stats[camera_id] = DetectionRunStats()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"detect-{camera_id}",
                daemon=True,
            )
            self._workers[camera_id] = worker
            worker.start()

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            stop_event = self._stops.pop(camera_id, None)
            worker = self._workers.pop(camera_id, None)
            self._fall_fps.pop(camera_id, None)
            self._last_fall_detection_at.pop(camera_id, None)
        if stop_event:
            stop_event.set()
        if worker and worker.is_alive():
            worker.join(timeout=3)

    def stop_all(self) -> None:
        for camera_id in list(self._workers.keys()):
            self.stop_for_camera(camera_id)

    def status(self, camera_id: str) -> DetectionWorkerStatus:
        detector_status = self.detector.status()
        with self._lock:
            worker = self._workers.get(camera_id)
            stats = self._stats.get(camera_id, DetectionRunStats())
            fps = self._fps.get(camera_id)
            fall_fps = self._fall_fps.get(camera_id)
        running = bool(worker and worker.is_alive())
        last_error = stats.last_error or detector_status.last_error
        return DetectionWorkerStatus(
            camera_id=camera_id,
            running=running,
            enabled=detector_status.enabled,
            loaded=detector_status.loaded,
            model_name=detector_status.model_name,
            detection_fps=fps.fps if fps else 0.0,
            fall_hint_fps=fall_fps.fps if fall_fps else 0.0,
            inference_latency_ms=stats.inference_latency_ms,
            fall_inference_latency_ms=stats.fall_inference_latency_ms,
            pipeline_mode=self.settings.pipeline_mode,
            fall_hint_writer_source="DetectionService" if self._fall_hint_in_detection_enabled else "none",
            last_error=last_error,
            latest_raw_person_count=stats.latest_raw_person_count,
            latest_fall_model_count=stats.latest_fall_model_count,
            latest_person_boxes=stats.latest_person_boxes,
            latest_person_confidences=stats.latest_person_confidences,
            latest_fall_labels=stats.latest_fall_labels,
            latest_fall_confidences=stats.latest_fall_confidences,
            latest_fall_boxes=stats.latest_fall_boxes,
        )

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        last_seq = 0
        interval = max(self.settings.detection_interval_ms, 1) / 1000
        logger.info("detection_worker_started camera_id=%s", camera_id)

        while not stop_event.is_set():
            buffer = self.source_manager.get_buffer(camera_id)
            if buffer is None:
                stop_event.wait(interval)
                continue

            packet = buffer.latest()
            if packet is None or packet.seq == last_seq:
                stop_event.wait(0.03)
                continue
            last_seq = packet.seq
            self._detect_packet(buffer, packet)
            stop_event.wait(interval)

        logger.info("detection_worker_stopped camera_id=%s", camera_id)

    def _detect_packet(self, buffer: FrameBuffer, packet) -> None:
        camera_id = packet.camera_id
        start = time.perf_counter()
        try:
            objects = self.detector.detect(packet.frame)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            self.realtime_store.update_detection(
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
                        "name": "ultralytics_yolo",
                        "mode": "person_detect",
                        "latency_ms": latency_ms,
                    },
                )
            )
            fall_objects: list[DetectedObject] = []
            fall_latency_ms: float | None = None
            run_fall_hint = self._should_run_fall_hint(camera_id)
            if run_fall_hint:
                fall_started = time.perf_counter()
                assert self.fall_detector is not None
                fall_objects = self.fall_detector.detect(packet.frame)
                fall_latency_ms = round((time.perf_counter() - fall_started) * 1000, 2)
            if run_fall_hint:
                self.realtime_store.update_fall_detection(
                    DetectionSnapshot(
                        camera_id=camera_id,
                        timestamp=utc_now_iso(),
                        frame_seq=packet.seq,
                        frame_width=packet.width,
                        frame_height=packet.height,
                        monotonic_at=time.monotonic(),
                        frame=packet.frame,
                        objects=fall_objects,
                        detector={
                            "name": "ultralytics_yolo_fall",
                            "mode": "fall_hint",
                            "latency_ms": fall_latency_ms,
                            "model_name": self.fall_detector.status().model_name,
                        },
                    )
            )
            with self._lock:
                fps = self._fps.setdefault(camera_id, FPSMeter())
                fall_fps = self._fall_fps.setdefault(camera_id, FPSMeter())
                stats = self._stats.setdefault(camera_id, DetectionRunStats())
                fps.tick()
                stats.inference_latency_ms = latency_ms
                stats.last_error = None
                stats.last_detected_at = time.monotonic()
                stats.latest_raw_person_count = len(objects)
                stats.latest_person_boxes = [[float(value) for value in item.bbox] for item in objects]
                stats.latest_person_confidences = [float(item.confidence) for item in objects]
                if run_fall_hint:
                    fall_fps.tick()
                    self._last_fall_detection_at[camera_id] = time.monotonic()
                    stats.fall_inference_latency_ms = fall_latency_ms
                    stats.last_fall_detected_at = self._last_fall_detection_at[camera_id]
                    stats.latest_fall_model_count = len(fall_objects)
                    stats.latest_fall_labels = [str(item.label) for item in fall_objects]
                    stats.latest_fall_confidences = [float(item.confidence) for item in fall_objects]
                    stats.latest_fall_boxes = [[float(value) for value in item.bbox] for item in fall_objects]
        except Exception as exc:
            logger.exception("detection_error camera_id=%s", camera_id)
            with self._lock:
                self._stats.setdefault(camera_id, DetectionRunStats()).last_error = str(exc)

    def _should_run_fall_hint(self, camera_id: str) -> bool:
        if not self._fall_hint_in_detection_enabled or self.fall_detector is None:
            return False
        now = time.monotonic()
        interval_ms = max(1, self.settings.fall_detector_interval_ms)
        with self._lock:
            last_at = self._last_fall_detection_at.get(camera_id)
            if last_at is not None and (now - last_at) * 1000 < interval_ms:
                return False
            self._last_fall_detection_at[camera_id] = now
            return True
