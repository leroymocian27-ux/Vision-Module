from __future__ import annotations

import threading

import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.monitoring.metrics import FPSMeter
from app.schemas.vision_result import DetectedObject
from app.tracking.bytetrack_tracker import ByteTrackTracker
from app.tracking.schemas import TargetState, TrackedObject, TrackingDetection, TrackingStatus
from app.tracking.target_manager import TargetManager

logger = get_logger(__name__)


class TrackingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._trackers: dict[str, ByteTrackTracker] = {}
        self._targets: dict[str, TargetManager] = {}
        self._fps: dict[str, FPSMeter] = {}
        self._last_error: dict[str, str | None] = {}
        self._tracked_objects_count: dict[str, int] = {}
        self._lock = threading.Lock()

    def enrich(
        self,
        camera_id: str,
        detections: list[DetectedObject],
        frame: np.ndarray | None = None,
    ) -> list[DetectedObject]:
        if not self.settings.enable_tracking:
            return detections

        try:
            tracking_detections = [
                TrackingDetection(
                    label=item.label,
                    confidence=item.confidence,
                    bbox=item.bbox,
                )
                for item in detections
                if item.label == "person"
            ]
            tracker = self._tracker_for(camera_id)
            tracked = tracker.update(tracking_detections, frame=frame)
            if not tracked and tracking_detections:
                fallback = self._fallback_tracked_objects(detections)
                with self._lock:
                    self._fps.setdefault(camera_id, FPSMeter()).tick()
                    self._last_error[camera_id] = tracker.status().last_error
                    self._tracked_objects_count[camera_id] = len(fallback)
                return fallback
            target_manager = self._target_for(camera_id)
            tracked = target_manager.update(tracked)
            with self._lock:
                self._fps.setdefault(camera_id, FPSMeter()).tick()
                self._last_error[camera_id] = None
                self._tracked_objects_count[camera_id] = len(tracked)
            return [self._tracked_to_detected(item) for item in tracked]
        except Exception as exc:
            logger.exception("tracking_enrich_failed camera_id=%s", camera_id)
            with self._lock:
                self._last_error[camera_id] = str(exc)
            fallback_objects = self._fallback_tracked_objects(detections)
            self._tracked_objects_count[camera_id] = len(fallback_objects)
            return fallback_objects or detections

    def reset(self, camera_id: str) -> None:
        with self._lock:
            tracker = self._trackers.pop(camera_id, None)
            self._targets.pop(camera_id, None)
            self._fps.pop(camera_id, None)
            self._last_error.pop(camera_id, None)
            self._tracked_objects_count.pop(camera_id, None)
        if tracker:
            tracker.reset()

    def status(self, camera_id: str) -> TrackingStatus:
        with self._lock:
            tracker = self._trackers.get(camera_id)
            target = self._targets.get(camera_id)
            fps = self._fps.get(camera_id)
            last_error = self._last_error.get(camera_id)
            tracked_objects_count = self._tracked_objects_count.get(camera_id, 0)

        tracker_status = tracker.status() if tracker else TrackingStatus(
            tracker_running=self.settings.enable_tracking,
        )
        tracking_state = target.state.value if target else TargetState.IDLE.value
        tracked_target_id = target.target_track_id if target else None
        active_target_exists = bool(target and target.active_target_exists)
        return TrackingStatus(
            tracker_running=self.settings.enable_tracking and tracker_status.tracker_running,
            tracking_state=tracking_state,
            tracked_target_id=tracked_target_id,
            active_target_exists=active_target_exists,
            tracked_objects_count=tracked_objects_count,
            tracking_fps=fps.fps if fps else 0.0,
            last_error=last_error or tracker_status.last_error,
        )

    def _tracker_for(self, camera_id: str) -> ByteTrackTracker:
        with self._lock:
            tracker = self._trackers.get(camera_id)
            if tracker is None:
                tracker = ByteTrackTracker(self.settings)
                self._trackers[camera_id] = tracker
            return tracker

    def _target_for(self, camera_id: str) -> TargetManager:
        with self._lock:
            target = self._targets.get(camera_id)
            if target is None:
                target = TargetManager(self.settings)
                self._targets[camera_id] = target
            return target

    @staticmethod
    def _tracked_to_detected(item: TrackedObject) -> DetectedObject:
        return DetectedObject(
            label=item.label,
            confidence=item.confidence,
            bbox=item.bbox,
            track_id=item.track_id,
            is_target=item.is_target,
            person_id=None,
            person_name=None,
            identity_state=item.identity_state,
        )

    @staticmethod
    def _fallback_tracked_objects(detections: list[DetectedObject]) -> list[DetectedObject]:
        return [
            item.model_copy(
                update={
                    "track_id": item.track_id if item.track_id is not None else index + 1,
                    "is_target": index == 0,
                    "identity_state": TargetState.TARGET_LOCKED.value if index == 0 else TargetState.IDLE.value,
                }
            )
            for index, item in enumerate(detections)
            if item.label == "person"
        ]
