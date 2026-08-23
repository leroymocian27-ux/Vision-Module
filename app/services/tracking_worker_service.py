from __future__ import annotations

import threading
import time

from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.monitoring.metrics import FPSMeter
from app.schemas.vision_result import DetectedObject
from app.services.identity_binding_service import IdentityBindingService
from app.services.tracking_service import TrackingService

logger = get_logger(__name__)

PROMOTABLE_FALL_ONLY_LABELS = {"fall", "falling", "fallen"}


class TrackingWorkerService:
    def __init__(
        self,
        settings: Settings,
        realtime_store: RealtimeResultStore,
        tracking_service: TrackingService,
        identity_binding_service: IdentityBindingService | None = None,
    ) -> None:
        self.settings = settings
        self.realtime_store = realtime_store
        self.tracking_service = tracking_service
        self.identity_binding_service = identity_binding_service
        self._workers: dict[str, threading.Thread] = {}
        self._stops: dict[str, threading.Event] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._last_error: dict[str, str | None] = {}
        self._last_detection_seq: dict[str, int] = {}
        self._last_corrected_tracking_snapshot: dict[str, ObjectSnapshot] = {}
        self._previous_corrected_tracking_snapshot: dict[str, ObjectSnapshot] = {}
        self._last_emitted_tracking_snapshot: dict[str, ObjectSnapshot] = {}
        self._lock = threading.Lock()

    def start_for_camera(self, camera_id: str) -> None:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._run_loop,
                args=(camera_id, stop_event),
                name=f"tracking-worker-{camera_id}",
                daemon=True,
            )
            self._stops[camera_id] = stop_event
            self._fps[camera_id] = FPSMeter()
            self._workers[camera_id] = worker
            worker.start()

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            stop_event = self._stops.pop(camera_id, None)
            worker = self._workers.pop(camera_id, None)
            self._last_detection_seq.pop(camera_id, None)
            self._previous_corrected_tracking_snapshot.pop(camera_id, None)
            self._last_corrected_tracking_snapshot.pop(camera_id, None)
            self._last_emitted_tracking_snapshot.pop(camera_id, None)
        if stop_event:
            stop_event.set()
        if worker and worker.is_alive():
            worker.join(timeout=3)

    def stop_all(self) -> None:
        for camera_id in list(self._workers.keys()):
            self.stop_for_camera(camera_id)

    def status_fps(self, camera_id: str) -> float:
        with self._lock:
            fps = self._fps.get(camera_id)
        return fps.fps if fps else 0.0

    def last_error(self, camera_id: str) -> str | None:
        with self._lock:
            return self._last_error.get(camera_id)

    def _run_loop(self, camera_id: str, stop_event: threading.Event) -> None:
        interval = 1 / max(self.settings.tracking_worker_fps, 1)
        logger.info("tracking_worker_started camera_id=%s", camera_id)
        while not stop_event.is_set():
            try:
                self._tick(camera_id)
                with self._lock:
                    self._fps.setdefault(camera_id, FPSMeter()).tick()
                    self._last_error[camera_id] = None
            except Exception as exc:
                logger.exception("tracking_worker_error camera_id=%s", camera_id)
                with self._lock:
                    self._last_error[camera_id] = str(exc)
            stop_event.wait(interval)
        logger.info("tracking_worker_stopped camera_id=%s", camera_id)

    def _tick(self, camera_id: str) -> None:
        detection = self.realtime_store.latest_detection(camera_id)
        if detection is None:
            return
        with self._lock:
            last_seq = self._last_detection_seq.get(camera_id)
        has_new_detection = detection.frame_seq != last_seq
        if has_new_detection:
            fall_detection = self.realtime_store.latest_fall_detection(camera_id)
            merged_detection = self._with_fall_promoted_objects(detection, fall_detection)
            objects = self._update_from_detection(merged_detection)
        else:
            objects = self._hold_or_predict(camera_id)
            if objects is None:
                return

        snapshot = ObjectSnapshot(
            camera_id=detection.camera_id,
            frame_seq=detection.frame_seq,
            frame_width=detection.frame_width,
            frame_height=detection.frame_height,
            timestamp=detection.timestamp,
            monotonic_at=time.monotonic(),
            objects=objects,
        )
        self.realtime_store.update_tracking(snapshot)
        with self._lock:
            if has_new_detection:
                previous_snapshot = self._last_corrected_tracking_snapshot.get(camera_id)
                if previous_snapshot is not None:
                    self._previous_corrected_tracking_snapshot[camera_id] = previous_snapshot
                self._last_corrected_tracking_snapshot[camera_id] = snapshot
                self._last_detection_seq[camera_id] = detection.frame_seq
            self._last_emitted_tracking_snapshot[camera_id] = snapshot

    def _update_from_detection(self, detection: DetectionSnapshot) -> list[DetectedObject]:
        objects = self.tracking_service.enrich(
            camera_id=detection.camera_id,
            detections=detection.objects,
            frame=detection.frame,
        )
        if self.identity_binding_service is not None:
            objects = self.identity_binding_service.apply_cached(detection.camera_id, objects)
        return objects

    def _hold_or_predict(self, camera_id: str) -> list[DetectedObject] | None:
        with self._lock:
            corrected = self._last_corrected_tracking_snapshot.get(camera_id)
            before_corrected = self._previous_corrected_tracking_snapshot.get(camera_id)
            last_emitted = self._last_emitted_tracking_snapshot.get(camera_id)
        if corrected is None:
            return None
        now = time.monotonic()
        age_ms = (now - corrected.monotonic_at) * 1000
        if before_corrected is None or age_ms > self.settings.target_lost_after_ms:
            held_snapshot = last_emitted or corrected
            return [
                item.model_copy(
                    update={
                        "fusion_debug": {
                            **(item.fusion_debug or {}),
                            "tracking_source": "held",
                            "tracking_age_ms": round(age_ms, 2),
                            "tracking_stale": age_ms > self.settings.target_lost_after_ms,
                        }
                    }
                )
                for item in held_snapshot.objects
            ]
        elapsed = max(corrected.monotonic_at - before_corrected.monotonic_at, 1e-6)
        prediction_dt = max(now - corrected.monotonic_at, 0.0)
        previous_by_track = {item.track_id: item for item in before_corrected.objects if item.track_id is not None}
        predicted: list[DetectedObject] = []
        for item in corrected.objects:
            prior = previous_by_track.get(item.track_id)
            if prior is None or item.track_id is None:
                predicted.append(
                    item.model_copy(
                        update={
                            "fusion_debug": {
                                **(item.fusion_debug or {}),
                                "tracking_source": "held",
                                "tracking_age_ms": round(age_ms, 2),
                                "tracking_stale": False,
                            }
                        }
                    )
                )
                continue
            dx = ((item.bbox[0] + item.bbox[2]) - (prior.bbox[0] + prior.bbox[2])) / 2
            dy = ((item.bbox[1] + item.bbox[3]) - (prior.bbox[1] + prior.bbox[3])) / 2
            vx = dx / elapsed
            vy = dy / elapsed
            shift_x = vx * prediction_dt
            shift_y = vy * prediction_dt
            predicted_bbox = [
                round(float(item.bbox[0] + shift_x), 2),
                round(float(item.bbox[1] + shift_y), 2),
                round(float(item.bbox[2] + shift_x), 2),
                round(float(item.bbox[3] + shift_y), 2),
            ]
            predicted.append(
                item.model_copy(
                    update={
                        "bbox": predicted_bbox,
                        "fusion_debug": {
                            **(item.fusion_debug or {}),
                            "tracking_source": "predicted",
                            "tracking_age_ms": round(age_ms, 2),
                            "tracking_stale": False,
                            "tracking_velocity_x": round(vx, 4),
                            "tracking_velocity_y": round(vy, 4),
                        },
                    }
                )
            )
        return predicted

    def _with_fall_promoted_objects(
        self,
        detection: DetectionSnapshot,
        fall_detection: DetectionSnapshot | None,
    ) -> DetectionSnapshot:
        if (
            fall_detection is None
            or not self.settings.fall_detector_promote_unmatched
            or fall_detection.frame_seq < detection.frame_seq - 5
        ):
            return detection

        raw_people = [item for item in detection.objects if item.label == "person"]
        qualifying_fall_only = [
            item
            for item in fall_detection.objects
            if item.confidence >= self.settings.fall_detector_promote_min_confidence
            and str(item.label).lower() in PROMOTABLE_FALL_ONLY_LABELS
        ]
        if not raw_people:
            if not qualifying_fall_only:
                return detection
            detector = dict(detection.detector)
            detector["fall_promoted_count"] = 0
            detector["fall_promoted_rejected_count"] = len(qualifying_fall_only)
            detector["fall_promoted_rejected_reason"] = "fall_only_without_person"
            return DetectionSnapshot(
                camera_id=detection.camera_id,
                frame_seq=detection.frame_seq,
                frame_width=detection.frame_width,
                frame_height=detection.frame_height,
                timestamp=detection.timestamp,
                monotonic_at=detection.monotonic_at,
                frame=detection.frame,
                objects=list(detection.objects),
                detector=detector,
            )

        merged = list(detection.objects)
        promoted_count = 0
        for fall_obj in fall_detection.objects:
            if fall_obj.confidence < self.settings.fall_detector_promote_min_confidence:
                continue
            if str(fall_obj.label).lower() not in PROMOTABLE_FALL_ONLY_LABELS:
                continue
            if any(self._iou(fall_obj.bbox, item.bbox) >= 0.08 for item in merged if item.label == "person"):
                continue
            promoted_count += 1
            merged.append(
                fall_obj.model_copy(
                    update={
                        "label": "person",
                        "confidence": float(fall_obj.confidence),
                        "fall_decision": {
                            "fall_state": "fallen_candidate",
                            "risk_level": "high",
                            "fall_probability": float(fall_obj.confidence),
                            "source": "yolo_fall_detector",
                            "detector_label": fall_obj.label,
                            "debug_reason": "fall_model_only_target",
                        },
                        "alarm_preview": {
                            "confirmed": False,
                            "risk_level": "high",
                            "fall_probability": float(fall_obj.confidence),
                            "source": "yolo_fall_detector",
                            "debug_reason": "fall_model_only_target",
                        },
                    }
                )
            )
        if promoted_count <= 0:
            return detection

        detector = dict(detection.detector)
        detector["fall_promoted_count"] = promoted_count
        return DetectionSnapshot(
            camera_id=detection.camera_id,
            frame_seq=detection.frame_seq,
            frame_width=detection.frame_width,
            frame_height=detection.frame_height,
            timestamp=detection.timestamp,
            monotonic_at=detection.monotonic_at,
            frame=detection.frame,
            objects=merged,
            detector=detector,
        )

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        if union <= 0:
            return 0.0
        return inter / union
