from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.events.ring_frame_buffer import KeyframeSelection
from app.events.schemas import EvidenceKeyframe, EvidencePackage, FallEventRecord


class EvidencePackageBuilder:
    """Build an immutable event evidence description from buffered frames."""

    def __init__(self, image_path_resolver: Callable[[KeyframeSelection], str | None] | None = None) -> None:
        self._image_path_resolver = image_path_resolver

    def build(
        self,
        event: FallEventRecord,
        selections: list[KeyframeSelection],
        *,
        feature_json: dict[str, Any] | None = None,
        fusion_debug: dict[str, Any] | None = None,
        pose_quality: str | None = None,
        decision_reason: str | None = None,
    ) -> EvidencePackage:
        features = feature_json or {}
        degradation_used: list[str] = []
        keyframes: list[EvidenceKeyframe] = []
        for selection in selections:
            if selection.frame is None:
                degradation_used.append(f"missing_{selection.role}_{selection.offset_ms}ms")
                keyframes.append(
                    EvidenceKeyframe(
                        role=selection.role,  # type: ignore[arg-type]
                        offset_ms=selection.offset_ms,
                        bbox=event.bbox,
                        fall_state=event.fall_state,
                        missing_reason=selection.missing_reason or "frame_unavailable",
                    )
                )
                continue
            image_path = self._image_path_resolver(selection) if self._image_path_resolver else None
            keyframes.append(
                EvidenceKeyframe(
                    role=selection.role,  # type: ignore[arg-type]
                    offset_ms=selection.offset_ms,
                    frame_seq=selection.frame.frame_seq,
                    timestamp=selection.frame.timestamp,
                    bbox=event.bbox,
                    fall_state=event.fall_state,
                    image_path=image_path,
                )
            )
        bbox_sequence = _as_bbox_sequence(features, event.bbox)
        fall_states = _as_string_sequence(features.get("fall_state_sequence"), event.fall_state)
        return EvidencePackage(
            incident_id=event.incident_id,
            camera_id=event.camera_id,
            track_id=event.track_id,
            trigger_frame_seq=event.trigger_frame_seq,
            trigger_timestamp=event.trigger_timestamp,
            keyframes=keyframes,
            bbox_sequence=bbox_sequence,
            fall_state_sequence=fall_states,
            fall_probability=event.fall_probability,
            fall_evidence_score=event.fall_evidence_score,
            adl_suppression_score=event.adl_suppression_score,
            pose_quality=pose_quality or _as_text(features.get("pose_quality")),
            fusion_debug=fusion_debug or {},
            decision_reason=decision_reason or _as_text(features.get("decision_reason")),
            degradation_used=degradation_used,
        )


def _as_bbox_sequence(value: Any, fallback: list[float] | None) -> list[list[float]]:
    if isinstance(value, list) and all(isinstance(item, list) for item in value):
        return [[float(point) for point in item] for item in value]
    return [list(fallback)] if fallback else []


def _as_string_sequence(value: Any, fallback: str) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return [fallback]


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None
