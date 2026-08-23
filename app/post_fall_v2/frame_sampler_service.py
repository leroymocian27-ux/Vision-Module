from __future__ import annotations

import time
from dataclasses import dataclass

from app.camera.frame_buffer import FramePacket
from app.post_fall_v2.schemas import SampledFrame, monotonic_to_utc_iso


@dataclass
class FrameSamplerDecision:
    sampled: SampledFrame | None
    reason: str


class FrameSamplerService:
    """Time-based non-consuming sampler for FrameBuffer latest packets."""

    def __init__(self, *, sample_fps: float, max_frame_age_ms: float) -> None:
        self.sample_fps = max(float(sample_fps), 0.01)
        self.max_frame_age_ms = float(max_frame_age_ms)
        self._min_interval = 1.0 / self.sample_fps
        self._last_sample_monotonic: dict[str, float] = {}
        self._last_seq: dict[str, int] = {}
        self.skipped_duplicate_frame_count: dict[str, int] = {}
        self.skipped_stale_frame_count: dict[str, int] = {}
        self.skipped_interval_count: dict[str, int] = {}

    def try_sample(self, packet: FramePacket | None, *, now: float | None = None) -> FrameSamplerDecision:
        if packet is None:
            return FrameSamplerDecision(None, "no_frame")
        now = time.monotonic() if now is None else now
        camera_id = packet.camera_id
        last_at = self._last_sample_monotonic.get(camera_id)
        if last_at is not None and now - last_at < self._min_interval:
            self.skipped_interval_count[camera_id] = self.skipped_interval_count.get(camera_id, 0) + 1
            return FrameSamplerDecision(None, "sample_interval")
        if self._last_seq.get(camera_id) == packet.seq:
            self.skipped_duplicate_frame_count[camera_id] = self.skipped_duplicate_frame_count.get(camera_id, 0) + 1
            return FrameSamplerDecision(None, "duplicate_frame")
        age_ms = (now - packet.captured_at) * 1000
        if age_ms > self.max_frame_age_ms:
            self._last_seq[camera_id] = packet.seq
            self.skipped_stale_frame_count[camera_id] = self.skipped_stale_frame_count.get(camera_id, 0) + 1
            return FrameSamplerDecision(None, "stale_frame")

        self._last_sample_monotonic[camera_id] = now
        self._last_seq[camera_id] = packet.seq
        frame_id = f"{camera_id}_{packet.source_generation}_{packet.seq:08d}"
        sampled = SampledFrame(
            camera_id=camera_id,
            frame_id=frame_id,
            frame_seq=packet.seq,
            captured_at=packet.captured_at_iso,
            sampled_at=monotonic_to_utc_iso(now),
            captured_monotonic=packet.captured_at,
            sampled_monotonic=now,
            source_width=packet.width,
            source_height=packet.height,
            source_generation=packet.source_generation,
            frame=packet.frame.copy(),
        )
        return FrameSamplerDecision(sampled, "sampled")
