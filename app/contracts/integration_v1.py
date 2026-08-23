from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


INTEGRATION_CONTRACT_VERSION = "eldercare.integration.v1"
VISION_EVENT_EXTENSION_SCHEMA = "eldercare.vision-event-extension.v1"
QWEN_ADVISORY_SCHEMA = "eldercare.qwen-advisory.v1"
ROBOT_ASSIST_TASK_SCHEMA = "eldercare.robot-assist-task.v1"
ROBOT_TASK_EVENT_SCHEMA = "eldercare.robot-task-event.v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class EvidenceReference(StrictContractModel):
    evidence_status: Literal["collecting", "complete", "degraded"]
    keyframe_count: int = Field(ge=0, le=6)
    keyframe_urls: list[str] = Field(default_factory=list, max_length=6)
    missing_reasons: list[str] = Field(default_factory=list)

    @field_validator("keyframe_urls")
    @classmethod
    def only_relative_keyframe_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("/events/"):
                raise ValueError("keyframe URLs must be relative event API paths")
            if ".." in value or "://" in value or "\\" in value:
                raise ValueError("keyframe URL is unsafe")
        return values


class RuleAnalysisSummary(StrictContractModel):
    support_fall_alarm: bool
    final_event_type: str = Field(min_length=1, max_length=80)
    final_risk_level: Literal["low", "medium", "high", "critical"]
    explanation: str = Field(min_length=1, max_length=1000)
    uncertainty: list[str] = Field(default_factory=list, max_length=20)
    qwen_keyframe_advisory: Optional["QwenKeyframeAdvisorySummary"] = None


class QwenKeyframeAdvisorySummary(StrictContractModel):
    """Safe advisory summary that may accompany an existing main-system alarm."""

    advisory_only: Literal[True] = True
    analysis_status: Literal["completed", "degraded", "failed"]
    model_name: Optional[str] = Field(default=None, max_length=160)
    image_count: int = Field(default=0, ge=0, le=6)
    scene_summary: Optional[str] = Field(default=None, max_length=600)
    posture_description: Optional[str] = Field(default=None, max_length=400)
    movement_description: Optional[str] = Field(default=None, max_length=400)
    possible_false_positive_reasons: list[str] = Field(default_factory=list, max_length=8)
    care_advice: list[str] = Field(default_factory=list, max_length=8)
    confidence_explanation: Optional[str] = Field(default=None, max_length=600)
    advisory_confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    error_code: Optional[str] = Field(default=None, max_length=120)


class RobotAdvisory(StrictContractModel):
    robot_assist_recommended: bool
    reason: str = Field(default="", max_length=1000)
    advisory_only: Literal[True] = True


class VisionEventMetadataExtension(StrictContractModel):
    """Additive payload placed in legacy `metadata`, never at its top level."""

    extension_schema: Literal["eldercare.vision-event-extension.v1"] = VISION_EVENT_EXTENSION_SCHEMA
    evidence: EvidenceReference
    semantic_analysis: RuleAnalysisSummary
    # Vision no longer emits robot guidance. This remains optional only so an
    # independently owned main-system robot module can preserve compatibility.
    robot_advisory: Optional[RobotAdvisory] = None


class QwenAdvisoryInput(StrictContractModel):
    """Whitelisted, single-use semantic input. It deliberately has no identity or media."""

    schema_version: Literal["eldercare.qwen-advisory-input.v1"] = "eldercare.qwen-advisory-input.v1"
    fall_state: Literal["fallen_confirmed"]
    risk_level: Literal["low", "medium", "high", "critical"]
    duration_on_ground_seconds: Optional[float] = Field(default=None, ge=0, le=3600)
    posture: Optional[str] = Field(default=None, max_length=80)
    movement_state: Optional[str] = Field(default=None, max_length=80)
    evidence_completeness: Literal["collecting", "complete", "degraded"]
    missing_reasons: list[str] = Field(default_factory=list, max_length=20)
    rule_signals: list[str] = Field(default_factory=list, max_length=30)
    camera_zone_code: Optional[str] = Field(default=None, max_length=64)


class QwenAdvisoryOutput(StrictContractModel):
    schema_version: Literal["eldercare.qwen-advisory.v1"] = QWEN_ADVISORY_SCHEMA
    summary: str = Field(min_length=1, max_length=1000)
    possible_false_positive_reasons: list[str] = Field(default_factory=list, max_length=10)
    care_recommendations: list[str] = Field(default_factory=list, max_length=10)
    robot_assist_recommended: bool
    robot_assist_reason: str = Field(default="", max_length=1000)
    uncertainty_notes: list[str] = Field(default_factory=list, max_length=10)
    advisory_confidence: Literal["low", "medium", "high"]


class RobotTaskState(str, Enum):
    CREATED = "CREATED"
    POLICY_CHECKED = "POLICY_CHECKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    QUEUED = "QUEUED"
    DISPATCHING = "DISPATCHING"
    EXECUTING = "EXECUTING"
    ARRIVED = "ARRIVED"
    CHECKING = "CHECKING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


TERMINAL_TASK_STATES = frozenset(
    {
        RobotTaskState.COMPLETED,
        RobotTaskState.FAILED,
        RobotTaskState.CANCELLED,
        RobotTaskState.TIMED_OUT,
        RobotTaskState.SAFETY_BLOCKED,
    }
)

_NORMAL_TASK_TRANSITIONS: dict[RobotTaskState, frozenset[RobotTaskState]] = {
    RobotTaskState.CREATED: frozenset({RobotTaskState.POLICY_CHECKED}),
    RobotTaskState.POLICY_CHECKED: frozenset({RobotTaskState.AWAITING_APPROVAL}),
    RobotTaskState.AWAITING_APPROVAL: frozenset({RobotTaskState.QUEUED}),
    RobotTaskState.QUEUED: frozenset({RobotTaskState.DISPATCHING}),
    RobotTaskState.DISPATCHING: frozenset({RobotTaskState.EXECUTING}),
    RobotTaskState.EXECUTING: frozenset({RobotTaskState.ARRIVED}),
    RobotTaskState.ARRIVED: frozenset({RobotTaskState.CHECKING}),
    RobotTaskState.CHECKING: frozenset({RobotTaskState.COMPLETED}),
}


def allowed_task_transitions(state: RobotTaskState) -> frozenset[RobotTaskState]:
    if state in TERMINAL_TASK_STATES:
        return frozenset()
    return _NORMAL_TASK_TRANSITIONS.get(state, frozenset()).union(
        {
            RobotTaskState.FAILED,
            RobotTaskState.CANCELLED,
            RobotTaskState.TIMED_OUT,
            RobotTaskState.SAFETY_BLOCKED,
        }
    )


class RobotTaskTransitionError(ValueError):
    code = "ROBOT_TASK_INVALID_STATE_TRANSITION"


class RobotAssistTask(StrictContractModel):
    schema_version: Literal["eldercare.robot-assist-task.v1"] = ROBOT_ASSIST_TASK_SCHEMA
    task_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=256)
    task_type: Literal["fall_scene_check"] = "fall_scene_check"
    incident_id: str = Field(min_length=1, max_length=256)
    alarm_id: str = Field(min_length=1, max_length=256)
    elder_id: str = Field(min_length=1, max_length=256)
    target_room: str = Field(min_length=1, max_length=128)
    observation_point_id: str = Field(min_length=1, max_length=128)
    priority: Literal["low", "normal", "high", "critical"] = "high"
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    approved_by: Optional[str] = Field(default=None, max_length=256)
    approved_at: Optional[datetime] = None
    state: RobotTaskState = RobotTaskState.CREATED
    adapter_mode: Literal["mock", "go2"] = "mock"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_approval_audit_fields(self) -> "RobotAssistTask":
        approved = self.approval_status == "approved"
        if approved != bool(self.approved_by and self.approved_at):
            raise ValueError("approved tasks require approved_by and approved_at; pending tasks must not include them")
        return self

    @field_validator("approved_at", "created_at", "updated_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value


def validate_task_transition(task: RobotAssistTask, next_state: RobotTaskState) -> None:
    if next_state not in allowed_task_transitions(task.state):
        raise RobotTaskTransitionError(f"{task.state} -> {next_state} is not allowed")
    if next_state == RobotTaskState.QUEUED and task.approval_status != "approved":
        raise RobotTaskTransitionError("QUEUED requires approved task")


class RobotAssistTaskEvent(StrictContractModel):
    schema_version: Literal["eldercare.robot-task-event.v1"] = ROBOT_TASK_EVENT_SCHEMA
    event_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["state_changed", "adapter_status", "safety", "audit"]
    previous_state: Optional[RobotTaskState] = None
    current_state: RobotTaskState
    timestamp: datetime = Field(default_factory=utc_now)
    source: Literal["main_system", "robot_assist_service", "mock_adapter", "go2_adapter"]
    message: str = Field(min_length=1, max_length=1000)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value


def contract_json_schemas() -> dict[str, dict[str, Any]]:
    return {
        "vision_event_metadata_extension": VisionEventMetadataExtension.model_json_schema(),
        "qwen_advisory_input": QwenAdvisoryInput.model_json_schema(),
        "qwen_advisory_output": QwenAdvisoryOutput.model_json_schema(),
        "robot_assist_task": RobotAssistTask.model_json_schema(),
        "robot_assist_task_event": RobotAssistTaskEvent.model_json_schema(),
    }
