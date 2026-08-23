from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.tracking.schemas import TrackedObject, TrackingDetection, TrackingStatus

logger = get_logger(__name__)


class _ByteTrackResults:
    """Small adapter that exposes the subset of Ultralytics Results used by BYTETracker."""

    def __init__(self, detections: list[TrackingDetection]) -> None:
        self._xyxy = np.asarray([item.bbox for item in detections], dtype=np.float32)
        self.conf = np.asarray([item.confidence for item in detections], dtype=np.float32)
        self.cls = np.zeros(len(detections), dtype=np.float32)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, index) -> "_ByteTrackResults":
        clone = object.__new__(_ByteTrackResults)
        clone._xyxy = np.asarray(self._xyxy[index], dtype=np.float32).reshape(-1, 4)
        clone.conf = np.asarray(self.conf[index], dtype=np.float32).reshape(-1)
        clone.cls = np.asarray(self.cls[index], dtype=np.float32).reshape(-1)
        return clone

    @property
    def xyxy(self) -> np.ndarray:
        return self._xyxy

    @property
    def xywh(self) -> np.ndarray:
        if len(self._xyxy) == 0:
            return np.empty((0, 4), dtype=np.float32)
        xywh = self._xyxy.copy()
        xywh[:, 0] = (self._xyxy[:, 0] + self._xyxy[:, 2]) / 2
        xywh[:, 1] = (self._xyxy[:, 1] + self._xyxy[:, 3]) / 2
        xywh[:, 2] = self._xyxy[:, 2] - self._xyxy[:, 0]
        xywh[:, 3] = self._xyxy[:, 3] - self._xyxy[:, 1]
        return xywh


@dataclass
class ByteTrackRunStats:
    tracker_running: bool = False
    tracked_objects_count: int = 0
    last_error: str | None = None


class ByteTrackTracker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tracker = None
        self._stats = ByteTrackRunStats(tracker_running=settings.enable_tracking)
        self._load_attempted = False
        if settings.enable_tracking:
            self._load_tracker()

    def _load_tracker(self) -> None:
        self._load_attempted = True
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker

            args = SimpleNamespace(
                track_high_thresh=self.settings.bytetrack_track_high_thresh,
                track_low_thresh=self.settings.bytetrack_track_low_thresh,
                new_track_thresh=self.settings.bytetrack_new_track_thresh,
                match_thresh=self.settings.bytetrack_match_thresh,
                track_buffer=self.settings.bytetrack_track_buffer,
                frame_rate=self.settings.bytetrack_frame_rate,
                fuse_score=self.settings.bytetrack_fuse_score,
            )
            self._tracker = BYTETracker(args=args)
            self._stats.tracker_running = True
            self._stats.last_error = None
            logger.info("bytetrack_loaded")
        except Exception as exc:
            self._tracker = None
            self._stats.tracker_running = False
            self._stats.last_error = str(exc)
            logger.error("bytetrack_load_failed error=%s", exc)

    def update(
        self,
        detections: list[TrackingDetection],
        frame: np.ndarray | None = None,
    ) -> list[TrackedObject]:
        if not self.settings.enable_tracking:
            return []
        if self._tracker is None and not self._load_attempted:
            self._load_tracker()
        if self._tracker is None:
            return []

        try:
            results = _ByteTrackResults(detections)
            tracks = self._tracker.update(results, img=frame)
            objects = [self._to_tracked_object(row) for row in tracks]
            self._stats.tracked_objects_count = len(objects)
            self._stats.tracker_running = True
            self._stats.last_error = None
            return objects
        except Exception as exc:
            self._stats.last_error = str(exc)
            logger.exception("bytetrack_update_failed")
            raise

    def reset(self) -> None:
        self._tracker = None
        self._load_attempted = False
        self._stats.tracked_objects_count = 0
        if self.settings.enable_tracking:
            self._load_tracker()

    def status(self) -> TrackingStatus:
        return TrackingStatus(
            tracker_running=self._stats.tracker_running,
            tracked_objects_count=self._stats.tracked_objects_count,
            last_error=self._stats.last_error,
        )

    @staticmethod
    def _to_tracked_object(row: np.ndarray) -> TrackedObject:
        x1, y1, x2, y2, track_id, score, _cls, _idx = row.tolist()
        return TrackedObject(
            track_id=int(track_id),
            label="person",
            confidence=round(float(score), 4),
            bbox=[round(float(v), 2) for v in [x1, y1, x2, y2]],
        )
