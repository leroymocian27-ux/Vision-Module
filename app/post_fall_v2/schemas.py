from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Literal

import numpy as np


FULL_FRAME_TRAIN_MATCHED = "FULL_FRAME_TRAIN_MATCHED"
EXPERIMENTAL_PERSON_ROI = "EXPERIMENTAL_PERSON_ROI"
BINARY_CANDIDATE_THRESHOLD_OOF = "BINARY_CANDIDATE_THRESHOLD_OOF"
POST_FALL_V2_INPUT_MODE_FULL_FRAME = "full_frame"
POST_FALL_V2_INPUT_MODE_FOLLOW_TARGET_ROI = "follow_target_roi"
POST_FALL_V2_INPUT_MODE_AUTO = "auto"

InputPolicy = Literal["FULL_FRAME_TRAIN_MATCHED", "EXPERIMENTAL_PERSON_ROI"]
PostFallV2InputMode = Literal["full_frame", "follow_target_roi", "auto"]
BinaryDecisionLabel = Literal["FALL", "NON_FALL", "UNKNOWN"]
FallVerdict = Literal[
    "normal_activity",
    "intentional_low_posture",
    "non_fall",
    "confirmed_fall",
    "unclear",
    "uncertain",
    "insufficient_visual_evidence",
]
SafetyOutcome = Literal["alert", "observe", "dismiss"]
SafetyPath = Literal[
    "transition_fall",
    "post_fall_abnormality",
    "explicit_non_fall",
    "uncertain_evidence",
]
BinaryAggregateState = Literal[
    "NORMAL",
    "FALL_CANDIDATE",
    "FALL_CONFIRMED",
    "EVENT_ACTIVE",
    "RECOVERY_PENDING",
    "COOLDOWN",
]
VLMAnalysisStatus = Literal[
    "disabled",
    "pending",
    "collecting_keyframes",
    "running",
    "completed",
    "failed",
    "timeout",
    "parse_failed",
]
KeyframePackageStatus = Literal["collecting", "ready", "degraded"]


def monotonic_to_utc_iso(monotonic_ts: float) -> str:
    wall_clock = time.time() - (time.monotonic() - monotonic_ts)
    return datetime.fromtimestamp(wall_clock, timezone.utc).isoformat(timespec="milliseconds")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass(frozen=True)
class SampledFrame:
    camera_id: str
    frame_id: str
    frame_seq: int
    captured_at: str
    sampled_at: str
    captured_monotonic: float
    sampled_monotonic: float
    source_width: int
    source_height: int
    source_generation: int
    frame: np.ndarray = field(repr=False)
    target_binding: dict[str, Any] | None = None


@dataclass(frozen=True)
class ThresholdInfo:
    value: float
    type: str = BINARY_CANDIDATE_THRESHOLD_OOF
    production_validated: bool = False


@dataclass(frozen=True)
class ModelInfo:
    name: str
    format: str
    sha256: str
    provider: str | None = None


@dataclass(frozen=True)
class InputInfo:
    policy: str
    source_width: int
    source_height: int
    model_width: int
    model_height: int


@dataclass(frozen=True)
class PerformanceInfo:
    queue_delay_ms: float | None
    preprocess_ms: float | None
    inference_ms: float | None
    total_ms: float | None


@dataclass(frozen=True)
class BinaryFallResult:
    frame_id: str
    camera_id: str
    captured_at: str
    sampled_at: str
    inferred_at: str
    prediction: str | None
    class_index: int | None
    fall_probability: float | None
    nofall_probability: float | None
    shadow_candidate_hint: bool
    threshold: ThresholdInfo
    model: ModelInfo
    input: InputInfo
    performance: PerformanceInfo
    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    human_label: str | None = None
    scenario_label: str | None = None
    analysis_only: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BinaryFrameResult:
    frame_id: str
    camera_id: str
    frame_seq: int
    captured_at: str
    inferred_at: str
    fall_probability: float | None
    non_fall_probability: float | None
    raw_label: str | None
    decision_label: BinaryDecisionLabel
    threshold: float
    model_name: str
    model_version: str
    valid: bool
    source_width: int
    source_height: int
    target_binding: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_classifier_result(cls, result: BinaryFallResult) -> "BinaryFrameResult":
        fall_probability = result.fall_probability
        decision_label: BinaryDecisionLabel = "UNKNOWN"
        if result.valid and fall_probability is not None:
            decision_label = "FALL" if fall_probability >= result.threshold.value else "NON_FALL"
        return cls(
            frame_id=result.frame_id,
            camera_id=result.camera_id,
            frame_seq=int(result.frame_id.rsplit("_", 1)[-1]) if result.frame_id.rsplit("_", 1)[-1].isdigit() else 0,
            captured_at=result.captured_at,
            inferred_at=result.inferred_at,
            fall_probability=fall_probability,
            non_fall_probability=result.nofall_probability,
            raw_label=result.prediction,
            decision_label=decision_label,
            threshold=result.threshold.value,
            model_name=result.model.name,
            model_version=result.model.sha256[:12],
            valid=result.valid,
            source_width=result.input.source_width,
            source_height=result.input.source_height,
            target_binding=result.analysis_only.get("target_binding") if result.analysis_only else None,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BinaryDecisionEvidence:
    window_size: int
    positive_count: int
    consecutive_positive_count: int
    mean_fall_probability: float | None
    max_fall_probability: float | None
    candidate_duration_ms: int
    threshold: float
    probability_window: list[float] = field(default_factory=list)
    persistent_strong_candidate: bool = False

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BinaryAggregateDecision:
    state: BinaryAggregateState
    camera_id: str
    frame_id: str | None
    frame_seq: int | None
    decision_label: BinaryDecisionLabel
    fall_probability: float | None
    incident_id: str | None
    event_created: bool
    rearmed: bool
    evidence: BinaryDecisionEvidence
    reason: str
    updated_at: str

    @property
    def fall_state(self) -> str:
        if self.state == "FALL_CANDIDATE":
            return "candidate"
        if self.state in {"FALL_CONFIRMED", "EVENT_ACTIVE", "RECOVERY_PENDING"}:
            return "confirmed"
        return "normal"

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BufferedFrame:
    camera_id: str
    frame_id: str
    frame_seq: int
    timestamp: str
    monotonic_at: float
    source_width: int
    source_height: int
    frame: np.ndarray = field(repr=False)
    target_binding: dict[str, Any] | None = None


@dataclass(frozen=True)
class KeyframeItem:
    role: str
    offset_ms: int
    frame_id: str | None
    frame_seq: int | None
    timestamp: str | None
    image_path: str | None = None
    missing_reason: str | None = None
    actual_offset_ms: int | None = None
    timing_error_ms: int | None = None
    target_binding: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KeyframePackage:
    incident_id: str
    camera_id: str
    confirmed_at: str
    source_width: int
    source_height: int
    frames: list[KeyframeItem]
    fall_probability_summary: dict[str, Any]
    status: KeyframePackageStatus = "ready"
    requested_offsets_ms: list[int] = field(default_factory=list)
    resolved_offsets_ms: list[int] = field(default_factory=list)
    missing_offsets_ms: list[int] = field(default_factory=list)
    max_offset_error_ms: int | None = None
    target_binding: dict[str, Any] | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FallDetailResult:
    incident_id: str
    analysis_status: VLMAnalysisStatus
    fall_verdict: FallVerdict = "unclear"
    high_risk_fall: int = 0
    scene_type: str = "unknown"
    recommended_action: str = "manual_review"
    positive_evidence: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    posture: str = "unknown"
    movement_level: str = "unknown"
    attempt_to_stand: str = "unknown"
    persistent_ground_state: str = "unknown"
    visibility: str = "unknown"
    occlusion: str = "unknown"
    scene_risks: list[str] = field(default_factory=list)
    possible_help_gesture: str = "unknown"
    summary: str = ""
    review_points: list[str] = field(default_factory=list)
    confidence: float | None = None
    latency_ms: float | None = None
    model_name: str | None = None
    error_message: str | None = None
    raw_fall_verdict: str | None = None
    consistency_status: str = "unchanged"
    consistency_reason: str | None = None
    activity: str = "unknown"
    posture_state: str = "unknown"
    fall_transition_visible: bool | None = None
    intentional_action_evidence: bool | None = None
    recovery_observed: bool | None = None
    semantic_event: str | None = None
    visible_distress: str = "unclear"
    vlm_is_true_fall: bool | None = None
    last_frame_description: str | None = None
    raw_compact_json: dict[str, Any] | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    fusion_version: str | None = None
    failure_reason: str | None = None
    timing: dict[str, Any] = field(default_factory=dict)
    request_started_at: str | None = None
    completed_at: str | None = None
    qwen_start_frames_received: int | None = None
    qwen_end_frames_received: int | None = None
    frames_received_during_qwen: int | None = None

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FallSafetyDecision:
    outcome: SafetyOutcome
    path: SafetyPath
    alert_level: str
    reason: str
    observation_elapsed_ms: int
    qwen_verdict: str | None = None
    review_required: bool = False
    updated_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FallEvent:
    incident_id: str
    camera_id: str
    # This is a binary-model candidate, not a confirmed fall.
    state: str
    started_at: str
    confirmed_at: str
    binary_evidence: dict[str, Any]
    keyframes: KeyframePackage | None = None
    vlm_status: VLMAnalysisStatus = "disabled"
    vlm_analysis: FallDetailResult | None = None
    vlm_reviews: list[FallDetailResult] = field(default_factory=list)
    safety_decision: FallSafetyDecision | None = None
    target_binding: dict[str, Any] | None = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
