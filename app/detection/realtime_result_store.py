from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from collections import OrderedDict
from typing import Any

import numpy as np

from app.schemas.vision_result import DetectedObject, VisionResult


@dataclass(frozen=True)
class DetectionSnapshot:
    camera_id: str
    frame_seq: int
    frame_width: int
    frame_height: int
    timestamp: str
    monotonic_at: float
    frame: np.ndarray
    objects: list[DetectedObject]
    detector: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectSnapshot:
    camera_id: str
    frame_seq: int
    frame_width: int
    frame_height: int
    timestamp: str
    monotonic_at: float
    objects: list[DetectedObject]


@dataclass(frozen=True)
class PipelineSnapshot:
    camera_id: str
    latest_detection: DetectionSnapshot | None
    latest_fall_detection: DetectionSnapshot | None
    latest_tracking: ObjectSnapshot | None
    latest_pose: ObjectSnapshot | None
    latest_behavior: ObjectSnapshot | None
    latest_temporal: ObjectSnapshot | None
    latest_fused_result: VisionResult | None
    latest_published_result: VisionResult | None


@dataclass(frozen=True)
class FreshSnapshot:
    value: Any | None
    state: str
    age_ms: float | None
    frame_seq: int | None
    frame_delta: int | None = None
    stale_reason: str | None = None


class RealtimeResultStore:
    DETECTION_HISTORY_LIMIT = 30

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detections: dict[str, DetectionSnapshot] = {}
        self._detection_history: dict[str, OrderedDict[int, DetectionSnapshot]] = {}
        self._fall_detections: dict[str, DetectionSnapshot] = {}
        self._tracking: dict[str, ObjectSnapshot] = {}
        self._pose: dict[str, ObjectSnapshot] = {}
        self._behavior: dict[str, ObjectSnapshot] = {}
        self._temporal: dict[str, ObjectSnapshot] = {}
        self._fused: dict[str, VisionResult] = {}
        self._published: dict[str, VisionResult] = {}

    def update_detection(self, snapshot: DetectionSnapshot) -> None:
        with self._lock:
            self._detections[snapshot.camera_id] = snapshot
            history = self._detection_history.setdefault(snapshot.camera_id, OrderedDict())
            history[snapshot.frame_seq] = snapshot
            history.move_to_end(snapshot.frame_seq)
            while len(history) > self.DETECTION_HISTORY_LIMIT:
                history.popitem(last=False)

    def latest_detection(self, camera_id: str) -> DetectionSnapshot | None:
        with self._lock:
            return self._detections.get(camera_id)

    def detection_for_frame(self, camera_id: str, frame_seq: int) -> DetectionSnapshot | None:
        with self._lock:
            return self._detection_history.get(camera_id, {}).get(frame_seq)

    def update_fall_detection(self, snapshot: DetectionSnapshot) -> None:
        with self._lock:
            self._fall_detections[snapshot.camera_id] = snapshot

    def latest_fall_detection(self, camera_id: str) -> DetectionSnapshot | None:
        with self._lock:
            return self._fall_detections.get(camera_id)

    def update_tracking(self, snapshot: ObjectSnapshot) -> None:
        with self._lock:
            self._tracking[snapshot.camera_id] = snapshot

    def latest_tracking(self, camera_id: str) -> ObjectSnapshot | None:
        with self._lock:
            return self._tracking.get(camera_id)

    def update_pose(self, snapshot: ObjectSnapshot) -> None:
        with self._lock:
            self._pose[snapshot.camera_id] = snapshot

    def latest_pose(self, camera_id: str) -> ObjectSnapshot | None:
        with self._lock:
            return self._pose.get(camera_id)

    def update_behavior(self, snapshot: ObjectSnapshot) -> None:
        with self._lock:
            self._behavior[snapshot.camera_id] = snapshot

    def latest_behavior(self, camera_id: str) -> ObjectSnapshot | None:
        with self._lock:
            return self._behavior.get(camera_id)

    def update_temporal(self, snapshot: ObjectSnapshot) -> None:
        with self._lock:
            self._temporal[snapshot.camera_id] = snapshot

    def latest_temporal(self, camera_id: str) -> ObjectSnapshot | None:
        with self._lock:
            return self._temporal.get(camera_id)

    def update_fused(self, result: VisionResult) -> None:
        with self._lock:
            self._fused[result.camera_id] = result

    def latest_fused(self, camera_id: str) -> VisionResult | None:
        with self._lock:
            return self._fused.get(camera_id)

    def update_published(self, result: VisionResult) -> None:
        with self._lock:
            self._published[result.camera_id] = result

    def latest_published(self, camera_id: str) -> VisionResult | None:
        with self._lock:
            return self._published.get(camera_id)

    def clear_camera(self, camera_id: str) -> None:
        with self._lock:
            self._detections.pop(camera_id, None)
            self._detection_history.pop(camera_id, None)
            self._fall_detections.pop(camera_id, None)
            self._tracking.pop(camera_id, None)
            self._pose.pop(camera_id, None)
            self._behavior.pop(camera_id, None)
            self._temporal.pop(camera_id, None)
            self._fused.pop(camera_id, None)
            self._published.pop(camera_id, None)

    def snapshot(self, camera_id: str) -> PipelineSnapshot:
        with self._lock:
            return PipelineSnapshot(
                camera_id=camera_id,
                latest_detection=self._detections.get(camera_id),
                latest_fall_detection=self._fall_detections.get(camera_id),
                latest_tracking=self._tracking.get(camera_id),
                latest_pose=self._pose.get(camera_id),
                latest_behavior=self._behavior.get(camera_id),
                latest_temporal=self._temporal.get(camera_id),
                latest_fused_result=self._fused.get(camera_id),
                latest_published_result=self._published.get(camera_id),
            )

    def latest_with_freshness(
        self,
        camera_id: str,
        slot: str,
        ttl_ms: int,
        *,
        base_frame_seq: int | None = None,
        max_frame_delta: int | None = None,
        disabled: bool = False,
    ) -> FreshSnapshot:
        if disabled:
            return FreshSnapshot(
                value=None,
                state="disabled",
                age_ms=None,
                frame_seq=None,
                stale_reason="disabled",
            )

        with self._lock:
            value = {
                "detection": self._detections,
                "fall_hint": self._fall_detections,
                "fall_detection": self._fall_detections,
                "tracking": self._tracking,
                "pose": self._pose,
                "behavior": self._behavior,
                "temporal": self._temporal,
                "fused": self._fused,
                "published": self._published,
            }.get(slot, {}).get(camera_id)

        if value is None:
            return FreshSnapshot(
                value=None,
                state="missing",
                age_ms=None,
                frame_seq=None,
                stale_reason="missing",
            )
        monotonic_at = getattr(value, "monotonic_at", None)
        if monotonic_at is None and isinstance(getattr(value, "detector", None), dict):
            monotonic_at = value.detector.get("_monotonic_at")
        frame_seq = getattr(value, "frame_seq", None)
        age_ms = self.age_ms(monotonic_at)
        if ttl_ms > 0 and age_ms is not None and age_ms > ttl_ms:
            return FreshSnapshot(
                value=value,
                state="stale",
                age_ms=age_ms,
                frame_seq=frame_seq,
                stale_reason="ttl_expired",
            )
        frame_delta = None
        if base_frame_seq is not None and frame_seq is not None:
            frame_delta = int(frame_seq) - int(base_frame_seq)
            if max_frame_delta is not None and abs(frame_delta) > max_frame_delta:
                return FreshSnapshot(
                    value=value,
                    state="frame_misaligned",
                    age_ms=age_ms,
                    frame_seq=frame_seq,
                    frame_delta=frame_delta,
                    stale_reason="frame_misaligned",
                )
        return FreshSnapshot(
            value=value,
            state="fresh",
            age_ms=age_ms,
            frame_seq=frame_seq,
            frame_delta=frame_delta,
        )

    @staticmethod
    def age_ms(monotonic_at: float | None) -> float | None:
        if monotonic_at is None:
            return None
        return round((time.monotonic() - monotonic_at) * 1000, 2)
