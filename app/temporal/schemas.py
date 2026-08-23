from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field

from app.temporal.scene_context import SceneContext


class FallState(StrEnum):
    NORMAL = "normal"
    UNSTABLE = "unstable"
    FALLING = "falling"
    FALLEN_CANDIDATE = "fallen_candidate"
    FALLEN_CONFIRMED = "fallen_confirmed"
    COOLDOWN = "cooldown"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    COOLDOWN = "cooldown"


class TargetFeature(BaseModel):
    track_id: int | None = None
    timestamp: str
    monotonic_time: float
    object_confidence: float = 0.0
    bbox_center_x: float = 0.0
    bbox_center_y: float = 0.0
    bbox_width: float = 0.0
    bbox_height: float = 0.0
    aspect_ratio: float = 0.0
    delta_x: float = 0.0
    delta_y: float = 0.0
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    speed: float = 0.0
    pose_available: bool = False
    pose_confidence: float = 0.0
    torso_angle: float | None = None
    hip_height_ratio: float | None = None
    head_height_ratio: float | None = None
    pose_quality_level: str = "pose_absent"
    pose_rejected_reason: str | None = None


class SequencePrediction(BaseModel):
    source: str = "mock"
    fall_probability: float = Field(ge=0.0, le=1.0)
    model_name: str | None = None
    model_available: bool = True
    window_ready: bool = True
    window_size: int | None = None
    feature_dim: int | None = None
    action_class: str | None = None
    confidence: float | None = None
    action_probs: dict[str, float] = Field(default_factory=dict)
    temporal_stage: str | None = None
    latency_ms: float | None = None


class TemporalMotionSummary(BaseModel):
    cumulative_drop_8f: float = 0.0
    cumulative_drop_16f: float = 0.0
    cumulative_drop_32f: float = 0.0
    max_downward_delta_16f: float = 0.0
    max_downward_velocity_16f: float = 0.0
    center_y_trend_score: float = 0.0
    continuous_descent_score: float = 0.0
    aspect_ratio_change_16f: float = 0.0
    bbox_bottom_stability_16f: float = 0.0
    low_posture_duration_ms: int = 0
    horizontal_posture_duration_ms: int = 0
    recovery_upward_score_16f: float = 0.0
    post_drop_speed_min_16f: float = 0.0
    track_quality_score: float = 1.0


class FallEvidenceScores(BaseModel):
    fall_evidence_score: float = 0.0
    vertical_drop_score: float = 0.0
    aspect_ratio_change_score: float = 0.0
    low_posture_score: float = 0.0
    impact_proxy_score: float = 0.0
    post_fall_stillness_score: float = 0.0
    floor_contact_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class ADLSuppressionScores(BaseModel):
    adl_suppression_score: float = 0.0
    sitting_score: float = 0.0
    bending_score: float = 0.0
    normal_lying_score: float = 0.0
    squatting_score: float = 0.0
    controlled_descent_score: float = 0.0
    support_surface_score: float = 0.0
    recovery_score: float = 0.0
    track_instability_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class TemporalV6Scores(BaseModel):
    motion: TemporalMotionSummary = Field(default_factory=TemporalMotionSummary)
    fall: FallEvidenceScores = Field(default_factory=FallEvidenceScores)
    adl: ADLSuppressionScores = Field(default_factory=ADLSuppressionScores)
    scene: SceneContext = Field(default_factory=SceneContext)


class FallDecision(BaseModel):
    fall_state: str = FallState.NORMAL.value
    risk_level: str = RiskLevel.LOW.value
    countdown_ms: int = 0
    fall_probability: float | None = None
    low_posture: bool | None = None
    stillness: bool | None = None
    body_angle: float | None = None
    bbox_aspect_ratio: float | None = None
    velocity_y: float | None = None
    candidate_duration_ms: int = 0
    confirm_duration_ms: int = 0
    confirm_frames: int = 0
    rejected_reason: str | None = None
    debug_reason: str | None = None
    motion_path: str | None = None
    fall_evidence_score: float | None = None
    adl_suppression_score: float | None = None
    suppressed_by_adl: bool = False
    uncertain_review: bool = False
    fall_latched: bool = False
    decision_reason: list[str] = Field(default_factory=list)


class TemporalStatus(BaseModel):
    enabled: bool = False
    feature_extractor_ok: bool = True
    window_size: int = 32
    active_tracks: int = 0
    fall_state: str = FallState.NORMAL.value
    fall_probability: float = 0.0
    risk_level: str = RiskLevel.LOW.value
    last_error: str | None = None
    model_provider: str = "mock"
    model_loaded: bool = True
    model_path: str | None = None
    model_input_size: int | None = None
    feature_schema_version: str | None = None
    feature_schema_hash: str | None = None
    model_last_error: str | None = None
    fallback_active: bool = False
    sc_tan_shadow_enabled: bool = False
    sc_tan_last_error: str | None = None
    rf_fusion_shadow_enabled: bool = False
    rf_fusion_last_error: str | None = None
    no_object_reset_count: int = 0
    last_reset_reason: str | None = None
