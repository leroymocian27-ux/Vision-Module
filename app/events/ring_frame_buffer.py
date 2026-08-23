from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np


DEFAULT_EVENT_KEYFRAME_OFFSETS_MS = (-3000, -1000, 0, 1000, 3000, 5000)


@dataclass(frozen=True)
class RingFrame:
    camera_id: str
    frame_seq: int
    timestamp: str
    frame: np.ndarray

    @property
    def width(self) -> int:
        return int(self.frame.shape[1])

    @property
    def height(self) -> int:
        return int(self.frame.shape[0])

    @property
    def byte_size(self) -> int:
        return int(self.frame.nbytes)


@dataclass(frozen=True)
class KeyframeSelection:
    role: str
    offset_ms: int
    frame: RingFrame | None
    missing_reason: str | None = None


class RingFrameBuffer:
    """Bounded, timestamp-addressable frame history for asynchronous evidence.

    It is intentionally separate from the realtime latest-frame cache. A future
    feature-flagged capture hook can feed this buffer without affecting frame
    delivery if this optional store rejects or drops a frame.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 8.0,
        max_frames_per_camera: int = 96,
        max_bytes_per_camera: int = 128 * 1024 * 1024,
        nearest_tolerance_ms: int = 750,
    ) -> None:
        self.window_seconds = max(0.1, float(window_seconds))
        self.max_frames_per_camera = max(1, int(max_frames_per_camera))
        self.max_bytes_per_camera = max(1, int(max_bytes_per_camera))
        self.nearest_tolerance_ms = max(0, int(nearest_tolerance_ms))
        self._lock = threading.Lock()
        self._frames: dict[str, deque[RingFrame]] = {}
        self._bytes: dict[str, int] = {}

    def add_frame(self, camera_id: str, frame_seq: int, timestamp: str, frame: np.ndarray) -> None:
        """Store one immutable frame copy; invalid frames are ignored safely."""
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return
        try:
            parsed_timestamp = _parse_timestamp(timestamp)
            copied = np.ascontiguousarray(frame.copy())
        except Exception:
            return
        packet = RingFrame(camera_id=camera_id, frame_seq=int(frame_seq), timestamp=parsed_timestamp.isoformat(), frame=copied)
        with self._lock:
            queue = self._frames.setdefault(camera_id, deque())
            queue.append(packet)
            self._bytes[camera_id] = self._bytes.get(camera_id, 0) + packet.byte_size
            self._trim_locked(camera_id, parsed_timestamp)

    def get_nearest_frame(self, camera_id: str, target_timestamp: str) -> RingFrame | None:
        target = _parse_timestamp(target_timestamp)
        with self._lock:
            frames = tuple(self._frames.get(camera_id, ()))
        if not frames:
            return None
        return min(frames, key=lambda item: abs((_parse_timestamp(item.timestamp) - target).total_seconds()))

    def extract_event_keyframes(
        self,
        camera_id: str,
        trigger_timestamp: str,
        offsets_ms: tuple[int, ...] | list[int] = DEFAULT_EVENT_KEYFRAME_OFFSETS_MS,
    ) -> list[KeyframeSelection]:
        trigger = _parse_timestamp(trigger_timestamp)
        with self._lock:
            frames = tuple(self._frames.get(camera_id, ()))
        selections: list[KeyframeSelection] = []
        for offset_ms in offsets_ms:
            role = _keyframe_role(int(offset_ms))
            target = trigger + timedelta(milliseconds=int(offset_ms))
            if not frames:
                selections.append(KeyframeSelection(role=role, offset_ms=int(offset_ms), frame=None, missing_reason="no_buffered_frames"))
                continue
            nearest = min(frames, key=lambda item: abs((_parse_timestamp(item.timestamp) - target).total_seconds()))
            if not _is_within_tolerance(nearest.timestamp, target, self.nearest_tolerance_ms):
                selections.append(KeyframeSelection(role=role, offset_ms=int(offset_ms), frame=None, missing_reason="no_frame_near_target"))
                continue
            selections.append(KeyframeSelection(role=role, offset_ms=int(offset_ms), frame=nearest))
        return selections

    def frame_count(self, camera_id: str) -> int:
        with self._lock:
            return len(self._frames.get(camera_id, ()))

    def byte_size(self, camera_id: str) -> int:
        with self._lock:
            return self._bytes.get(camera_id, 0)

    def _trim_locked(self, camera_id: str, latest: datetime) -> None:
        queue = self._frames[camera_id]
        cutoff = latest - timedelta(seconds=self.window_seconds)
        while queue and _parse_timestamp(queue[0].timestamp) < cutoff:
            self._drop_oldest_locked(camera_id)
        while queue and (
            len(queue) > self.max_frames_per_camera or self._bytes.get(camera_id, 0) > self.max_bytes_per_camera
        ):
            self._drop_oldest_locked(camera_id)

    def _drop_oldest_locked(self, camera_id: str) -> None:
        queue = self._frames.get(camera_id)
        if not queue:
            return
        dropped = queue.popleft()
        self._bytes[camera_id] = max(0, self._bytes.get(camera_id, 0) - dropped.byte_size)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _is_within_tolerance(frame_timestamp: str, target: datetime, tolerance_ms: int) -> bool:
    return abs((_parse_timestamp(frame_timestamp) - target).total_seconds() * 1000) <= tolerance_ms


def _keyframe_role(offset_ms: int) -> str:
    if offset_ms <= -2000:
        return "pre_context"
    if offset_ms < 0:
        return "pre_fall"
    if offset_ms == 0:
        return "trigger"
    if offset_ms < 3000:
        return "post_fall"
    return "post_check"
