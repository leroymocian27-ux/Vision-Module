from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


EventType = Literal["fall_candidate", "fallen_confirmed"]
EventStatus = Literal[
    "pending",
    "processing",
    "evidence_ready",
    "semantic_ready",
    "reviewed",
    "delivery_pending",
    "sent",
    "retry",
    "failed",
]
RiskLevel = Literal["low", "medium", "high", "critical"]
QwenKeyframeAnalysisStatus = Literal["disabled", "pending", "processing", "completed", "degraded", "failed"]


def event_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FallEventRecord(BaseModel):
    schema_version: str = "fall_event_record.v1"
    incident_id: str
    camera_id: str
    stream_name: str = "primary"
    track_id: int | None = None
    person_id: str | None = None
    event_type: EventType
    fall_state: str
    risk_level: RiskLevel = "medium"
    risk_score: float | None = Field(default=None, ge=0.0, le=1.0)
    trigger_frame_seq: int | None = None
    trigger_timestamp: str
    bbox: list[float] | None = None
    fall_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    fall_evidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    adl_suppression_score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: EventStatus = "pending"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=event_now_iso)
    updated_at: str = Field(default_factory=event_now_iso)


class EvidenceKeyframe(BaseModel):
    role: Literal["pre_context", "pre_fall", "trigger", "post_fall", "post_check"]
    offset_ms: int
    frame_seq: int | None = None
    timestamp: str | None = None
    bbox: list[float] | None = None
    fall_state: str | None = None
    image_path: str | None = None
    snapshot_url: str | None = None
    missing_reason: str | None = None


class EvidencePackage(BaseModel):
    schema_version: str = "evidence_package.v1"
    incident_id: str
    camera_id: str
    track_id: int | None = None
    trigger_frame_seq: int | None = None
    trigger_timestamp: str
    keyframes: list[EvidenceKeyframe] = Field(default_factory=list)
    bbox_sequence: list[list[float]] = Field(default_factory=list)
    fall_state_sequence: list[str] = Field(default_factory=list)
    fall_probability: float | None = None
    fall_evidence_score: float | None = None
    adl_suppression_score: float | None = None
    pose_quality: str | None = None
    fusion_debug: dict[str, Any] = Field(default_factory=dict)
    decision_reason: str | None = None
    degradation_used: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=event_now_iso)


class EventSemantics(BaseModel):
    schema_version: str = "event_semantics.v1"
    incident_id: str
    actor: dict[str, Any] = Field(default_factory=dict)
    scene: dict[str, Any] = Field(default_factory=dict)
    motion: dict[str, Any] = Field(default_factory=dict)
    posture: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    uncertainty: list[str] = Field(default_factory=list)
    degradation_used: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=event_now_iso)


class TrustedEventResult(BaseModel):
    schema_version: str = "trusted_event_result.v1"
    incident_id: str
    support_fall_alarm: bool
    final_event_type: str
    final_risk_level: RiskLevel
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    uncertainty: list[str] = Field(default_factory=list)
    alarm_title: str
    alarm_body: str
    recommended_action: str
    review_result: str = "rule_only"
    degradation_used: list[str] = Field(default_factory=list)
    vlm_provider: str | None = None
    vlm_latency_ms: float | None = Field(default=None, ge=0.0)
    observed_process: str | None = None
    risk_interpretation: str | None = None
    adl_likelihood: str | None = None
    scene_summary: str | None = None
    possible_false_positive_reason: str | None = None
    care_advice: str | None = None
    confidence_explanation: str | None = None
    advisory_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: str = Field(default_factory=event_now_iso)


class QwenKeyframeAdvisory(BaseModel):
    """Non-authoritative description produced from locally processed event frames."""

    schema_version: str = "qwen_keyframe_advisory.v1"
    analysis_status: QwenKeyframeAnalysisStatus = "disabled"
    provider: str = "ollama_qwen"
    model_name: str | None = None
    image_count: int = Field(default=0, ge=0)
    analyzed_offsets_ms: list[int] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)
    scene_summary: str | None = Field(default=None, max_length=600)
    posture_description: str | None = Field(default=None, max_length=400)
    movement_description: str | None = Field(default=None, max_length=400)
    possible_false_positive_reasons: list[str] = Field(default_factory=list, max_length=8)
    care_advice: list[str] = Field(default_factory=list, max_length=8)
    confidence_explanation: str | None = Field(default=None, max_length=600)
    advisory_confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    latency_ms: float | None = Field(default=None, ge=0.0)
    error_code: str | None = Field(default=None, max_length=120)
    created_at: str = Field(default_factory=event_now_iso)
    completed_at: str | None = None


class DeliveryRecord(BaseModel):
    schema_version: str = "delivery_record.v1"
    delivery_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: str
    camera_id: str = ""
    target_url: str
    payload_json: dict[str, Any]
    delivery_mode: Literal["dry_run", "post"] = "post"
    dry_run: bool = False
    delivery_status: Literal["pending", "sending", "sent", "dry_run_sent", "retry", "failed"] = "pending"
    attempt_count: int = Field(default=0, ge=0)
    last_http_status: int | None = None
    last_error: str | None = None
    next_retry_at: str | None = None
    lock_owner: str | None = None
    lock_token: str | None = None
    lock_until: str | None = None
    delivered_at: str | None = None
    created_at: str = Field(default_factory=event_now_iso)
    updated_at: str = Field(default_factory=event_now_iso)


class EventOutboxRecord(BaseModel):
    schema_version: str = "event_outbox_record.v1"
    event: FallEventRecord
    status: EventStatus = "pending"
    lock_owner: str | None = None
    lock_token: str | None = None
    lock_until: str | None = None
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: str | None = None
    last_error: str | None = None
    evidence_package: EvidencePackage | None = None
    event_semantics: EventSemantics | None = None
    trusted_result: TrustedEventResult | None = None
    qwen_advisory: QwenKeyframeAdvisory | None = None
    archive_path: str | None = None
    archive_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=event_now_iso)
    updated_at: str = Field(default_factory=event_now_iso)

    @property
    def incident_id(self) -> str:
        return self.event.incident_id
