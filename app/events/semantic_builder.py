from __future__ import annotations

from typing import Any

from app.events.schemas import EvidencePackage, EventSemantics, FallEventRecord


class EventSemanticBuilder:
    """Translate detector evidence into a stable, model-independent event view."""

    def __init__(self, camera_scene_rules: dict[str, dict[str, Any]] | None = None) -> None:
        self.camera_scene_rules = camera_scene_rules or {}

    def build(
        self,
        event: FallEventRecord,
        evidence: EvidencePackage,
        *,
        features: dict[str, Any] | None = None,
        temporal: dict[str, Any] | None = None,
        pose: dict[str, Any] | None = None,
        fusion_debug: dict[str, Any] | None = None,
    ) -> EventSemantics:
        features = features or {}
        temporal = temporal or {}
        pose = pose or {}
        fusion_debug = fusion_debug or evidence.fusion_debug
        motion = _nested(features, "motion")
        fall_hint = _nested(features, "fall_hint")
        scene_rule = self.camera_scene_rules.get(event.camera_id, {})
        tracking_stable = bool(motion.get("tracking_stable") is True)
        stillness_ms = _number(
            temporal.get("post_event_stillness_ms")
            or temporal.get("stillness_ms")
            or motion.get("post_event_stillness_ms")
            or motion.get("stillness_ms")
        )
        adl_score = (
            evidence.adl_suppression_score
            if evidence.adl_suppression_score is not None
            else event.adl_suppression_score
        )
        evidence_strong = _strong_evidence(event, evidence, stillness_ms)
        if (adl_score or 0.0) >= 0.65:
            decision = "need_review"
            advice = "建议人工查看关键帧和实时画面，排除坐下、弯腰或正常躺卧。"
        elif event.event_type == "fallen_confirmed":
            decision = "urgent_attention"
            advice = "建议立即查看现场并按照照护流程确认老人状态。"
        elif evidence_strong:
            decision = "need_attention"
            advice = "建议立即查看实时画面并确认老人状态。"
        else:
            decision = "need_review"
            advice = "建议结合实时画面进一步复核。"
        uncertainty = list(evidence.degradation_used)
        if not tracking_stable:
            uncertainty.append("tracking_not_stable")
        if not evidence.keyframes:
            uncertainty.append("no_keyframes")
        return EventSemantics(
            incident_id=event.incident_id,
            actor={
                "target_type": "elder",
                "track_id": event.track_id,
                "person_id": event.person_id,
                "tracking_stable": tracking_stable,
            },
            scene={
                "camera_id": event.camera_id,
                "scene_type": scene_rule.get("scene_type", "unknown"),
                "location_hint": scene_rule.get("location_hint", "unknown"),
                "visibility": scene_rule.get("visibility", "unknown"),
            },
            motion={
                "main_transition": _transition(event, temporal, motion),
                "vertical_drop_detected": bool(motion.get("rapid_descent") or temporal.get("vertical_drop_detected")),
                "post_event_stillness_ms": stillness_ms,
            },
            posture={
                "pre_state": temporal.get("pre_state", "unknown"),
                "trigger_state": "falling" if event.fall_state in {"falling", "fallen_candidate", "fallen_confirmed"} else event.fall_state,
                "post_state": temporal.get("post_state", "lying_or_fallen" if event.event_type == "fallen_confirmed" else "low_posture"),
                "pose_quality": evidence.pose_quality or pose.get("pose_quality_level") or "unavailable",
            },
            evidence={
                "fall_hint": fall_hint.get("label") or fall_hint.get("fall_hint") or fusion_debug.get("fall_hint_label"),
                "fall_probability": evidence.fall_probability
                if evidence.fall_probability is not None
                else event.fall_probability,
                "fall_evidence_score": evidence.fall_evidence_score
                if evidence.fall_evidence_score is not None
                else event.fall_evidence_score,
                "adl_suppression_score": adl_score,
                "keyframe_count": len([frame for frame in evidence.keyframes if frame.missing_reason is None]),
            },
            risk={
                "event_type": event.event_type,
                "risk_level": event.risk_level,
                "confidence": event.risk_score or event.fall_evidence_score or event.fall_probability or 0.0,
                "decision": decision,
                "advice": advice,
            },
            uncertainty=uncertainty,
            degradation_used=list(evidence.degradation_used),
        )


def _nested(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _strong_evidence(event: FallEventRecord, evidence: EvidencePackage, stillness_ms: float | None) -> bool:
    return bool(
        event.event_type == "fallen_confirmed"
        or (event.fall_evidence_score or 0.0) >= 0.7
        or ((event.fall_probability or 0.0) >= 0.7 and (stillness_ms or 0.0) >= 1000)
    )


def _transition(event: FallEventRecord, temporal: dict[str, Any], motion: dict[str, Any]) -> str:
    if temporal.get("main_transition"):
        return str(temporal["main_transition"])
    if motion.get("rapid_descent") or event.fall_state in {"falling", "fallen_candidate", "fallen_confirmed"}:
        return "standing_to_low_posture"
    return "unknown"
