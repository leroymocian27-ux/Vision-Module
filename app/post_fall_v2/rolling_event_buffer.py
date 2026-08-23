from __future__ import annotations

import threading
from collections import defaultdict, deque

from app.post_fall_v2.schemas import BufferedFrame, SampledFrame


class RollingEventBuffer:
    def __init__(self, *, window_seconds: float, max_frames_per_camera: int | None = None) -> None:
        self.window_seconds = max(0.5, float(window_seconds))
        self.max_frames_per_camera = max_frames_per_camera or max(8, int(self.window_seconds * 10))
        self._frames: dict[str, deque[BufferedFrame]] = defaultdict(deque)
        self._lock = threading.Lock()

    def add_sampled_frame(self, sampled: SampledFrame) -> BufferedFrame:
        buffered = BufferedFrame(
            camera_id=sampled.camera_id,
            frame_id=sampled.frame_id,
            frame_seq=sampled.frame_seq,
            timestamp=sampled.captured_at,
            monotonic_at=sampled.captured_monotonic,
            source_width=sampled.source_width,
            source_height=sampled.source_height,
            frame=sampled.frame.copy(),
        )
        with self._lock:
            frames = self._frames[sampled.camera_id]
            frames.append(buffered)
            self._trim_locked(frames, sampled.captured_monotonic)
        return buffered

    def nearest(self, camera_id: str, target_monotonic: float) -> BufferedFrame | None:
        with self._lock:
            frames = list(self._frames.get(camera_id, ()))
        if not frames:
            return None
        return min(frames, key=lambda item: abs(item.monotonic_at - target_monotonic))

    def nearest_within(
        self,
        camera_id: str,
        target_monotonic: float,
        *,
        tolerance_ms: float,
    ) -> BufferedFrame | None:
        tolerance_seconds = max(0.0, float(tolerance_ms)) / 1000.0
        candidate = self.nearest(camera_id, target_monotonic)
        if candidate is None:
            return None
        if abs(candidate.monotonic_at - target_monotonic) > tolerance_seconds:
            return None
        return candidate

    def window(self, camera_id: str) -> list[BufferedFrame]:
        with self._lock:
            return list(self._frames.get(camera_id, ()))

    def clear(self, camera_id: str) -> None:
        with self._lock:
            self._frames.pop(camera_id, None)

    def _trim_locked(self, frames: deque[BufferedFrame], now: float) -> None:
        min_ts = now - self.window_seconds
        while frames and frames[0].monotonic_at < min_ts:
            frames.popleft()
        while len(frames) > self.max_frames_per_camera:
            frames.popleft()
