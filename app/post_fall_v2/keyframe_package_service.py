from __future__ import annotations

from app.post_fall_v2.rolling_event_buffer import RollingEventBuffer
from app.post_fall_v2.schemas import BinaryAggregateDecision, KeyframeItem, KeyframePackage


class KeyframePackageService:
    def __init__(
        self,
        *,
        offsets_ms: tuple[int, ...] = (-3000, -1000, 0, 1000, 3000, 5000),
        tolerance_ms: int = 750,
    ) -> None:
        self.offsets_ms = offsets_ms
        self.tolerance_ms = max(0, int(tolerance_ms))

    def build(
        self,
        *,
        incident_id: str,
        decision: BinaryAggregateDecision,
        buffer: RollingEventBuffer,
        confirmed_monotonic: float,
    ) -> KeyframePackage:
        return self.build_from_available_frames(
            incident_id=incident_id,
            camera_id=decision.camera_id,
            confirmed_at=decision.updated_at,
            fall_probability_summary=decision.evidence.to_record(),
            buffer=buffer,
            confirmed_monotonic=confirmed_monotonic,
            now_monotonic=confirmed_monotonic,
        )

    def build_from_available_frames(
        self,
        *,
        incident_id: str,
        camera_id: str,
        confirmed_at: str,
        fall_probability_summary: dict,
        buffer: RollingEventBuffer,
        confirmed_monotonic: float,
        now_monotonic: float | None = None,
    ) -> KeyframePackage:
        frames: list[KeyframeItem] = []
        source_width = 0
        source_height = 0
        used_frame_ids: set[str] = set()
        resolved_offsets: list[int] = []
        missing_offsets: list[int] = []
        now_monotonic = confirmed_monotonic if now_monotonic is None else now_monotonic
        for offset_ms in self.offsets_ms:
            target = confirmed_monotonic + (offset_ms / 1000.0)
            if target > now_monotonic + (self.tolerance_ms / 1000.0):
                frames.append(self._missing(offset_ms, "future_frame_not_available_yet"))
                missing_offsets.append(offset_ms)
                continue
            nearest = buffer.nearest_within(
                camera_id,
                target,
                tolerance_ms=self.tolerance_ms,
            )
            if nearest is None:
                frames.append(self._missing(offset_ms, "no_frame_within_tolerance"))
                missing_offsets.append(offset_ms)
                continue
            if nearest.frame_id in used_frame_ids:
                frames.append(self._missing(offset_ms, "duplicate_frame_rejected"))
                missing_offsets.append(offset_ms)
                continue
            used_frame_ids.add(nearest.frame_id)
            source_width = max(source_width, nearest.source_width)
            source_height = max(source_height, nearest.source_height)
            actual_offset_ms = int(round((nearest.monotonic_at - confirmed_monotonic) * 1000))
            timing_error_ms = int(round(abs(nearest.monotonic_at - target) * 1000))
            frames.append(
                KeyframeItem(
                    role=self._role(offset_ms),
                    offset_ms=offset_ms,
                    frame_id=nearest.frame_id,
                    frame_seq=nearest.frame_seq,
                    timestamp=nearest.timestamp,
                    actual_offset_ms=actual_offset_ms,
                    timing_error_ms=timing_error_ms,
                )
            )
            resolved_offsets.append(offset_ms)
        status = "ready" if not missing_offsets else "degraded"
        return KeyframePackage(
            incident_id=incident_id,
            camera_id=camera_id,
            confirmed_at=confirmed_at,
            source_width=source_width,
            source_height=source_height,
            frames=frames,
            fall_probability_summary=fall_probability_summary,
            status=status,
            requested_offsets_ms=list(self.offsets_ms),
            resolved_offsets_ms=resolved_offsets,
            missing_offsets_ms=missing_offsets,
            max_offset_error_ms=self.tolerance_ms,
        )

    def _missing(self, offset_ms: int, reason: str) -> KeyframeItem:
        return KeyframeItem(
            role=self._role(offset_ms),
            offset_ms=offset_ms,
            frame_id=None,
            frame_seq=None,
            timestamp=None,
            missing_reason=reason,
        )

    @staticmethod
    def _role(offset_ms: int) -> str:
        if offset_ms < -1000:
            return "pre_context"
        if offset_ms < 0:
            return "pre_fall"
        if offset_ms == 0:
            return "trigger"
        if offset_ms <= 3000:
            return "post_fall"
        return "post_check"
