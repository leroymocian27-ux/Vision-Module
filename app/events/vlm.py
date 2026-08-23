from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.events.schemas import EvidencePackage, EventSemantics


VLMProvider = Literal[
    "disabled",
    "dummy",
    "http_mock",
    "http",
    "qwen_http",
    "ollama",
    "qwen_ollama",
    "ollama_qwen",
]
ADLLikelihood = Literal["low", "medium", "high", "unknown"]


class VLMReviewInput(BaseModel):
    """Stable event-level VLM request contract.

    The adapter receives archived evidence and event semantics after the rule
    pipeline has already built them. It is never a realtime first decision path.
    """

    schema_version: str = "event_vlm_input.v1"
    incident_id: str
    camera_id: str
    keyframe_image_paths: list[str] = Field(default_factory=list)
    timeline_image_path: str | None = None
    event_semantics: dict[str, Any] = Field(default_factory=dict)
    feature_json: dict[str, Any] = Field(default_factory=dict)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str = "fall_event_review_v1"
    output_schema_version: str = "vlm_review_result_v1"


class VLMReviewResult(BaseModel):
    """Stable event-level VLM response contract."""

    schema_version: str = "vlm_review_result_v1"
    support_fall_alarm: bool | None = None
    semantic_event_type: str = "unknown"
    observed_process: str = ""
    adl_likelihood: ADLLikelihood = "unknown"
    uncertainty: list[str] = Field(default_factory=list)
    risk_interpretation: str = ""
    alarm_title: str = ""
    alarm_body: str = ""
    recommended_action: str = ""
    scene_summary: str = ""
    possible_false_positive_reason: str = ""
    care_advice: str = ""
    confidence_explanation: str = ""
    advisory_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_response: str | None = None
    parse_error: str | None = None
    provider: VLMProvider = "disabled"
    latency_ms: float | None = Field(default=None, ge=0.0)


# Backward-compatible names used by the first contract tests.
VLMInput = VLMReviewInput
VLMOutput = VLMReviewResult


def build_vlm_input(
    semantics: EventSemantics,
    evidence: EvidencePackage,
    *,
    prompt_version: str = "fall_event_review_v1",
    output_schema_version: str = "vlm_review_result_v1",
    feature_json: dict[str, Any] | None = None,
    timeline_image_path: str | None = None,
) -> VLMReviewInput:
    image_paths = [
        frame.image_path
        for frame in evidence.keyframes
        if isinstance(frame.image_path, str) and frame.image_path
    ]
    default_features = {
        "fall_probability": evidence.fall_probability,
        "fall_evidence_score": evidence.fall_evidence_score,
        "adl_suppression_score": evidence.adl_suppression_score,
        "pose_quality": evidence.pose_quality,
        "bbox_sequence": evidence.bbox_sequence,
        "fall_state_sequence": evidence.fall_state_sequence,
        "fusion_debug": evidence.fusion_debug,
        "degradation_used": evidence.degradation_used,
    }
    evidence_summary = {
        "incident_id": evidence.incident_id,
        "camera_id": evidence.camera_id,
        "track_id": evidence.track_id,
        "trigger_frame_seq": evidence.trigger_frame_seq,
        "trigger_timestamp": evidence.trigger_timestamp,
        "fall_probability": evidence.fall_probability,
        "fall_evidence_score": evidence.fall_evidence_score,
        "adl_suppression_score": evidence.adl_suppression_score,
        "keyframes": [
            {
                "role": frame.role,
                "offset_ms": frame.offset_ms,
                "frame_seq": frame.frame_seq,
                "fall_state": frame.fall_state,
                "image_path": frame.image_path,
                "missing_reason": frame.missing_reason,
            }
            for frame in evidence.keyframes
        ],
        "degradation_used": list(evidence.degradation_used),
    }
    return VLMReviewInput(
        incident_id=semantics.incident_id,
        camera_id=evidence.camera_id,
        keyframe_image_paths=image_paths,
        timeline_image_path=timeline_image_path,
        event_semantics=semantics.model_dump(mode="json"),
        feature_json=feature_json or default_features,
        evidence_summary=evidence_summary,
        prompt_version=prompt_version,
        output_schema_version=output_schema_version,
    )


def adl_likelihood_from_score(value: Any) -> ADLLikelihood:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.65:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"
