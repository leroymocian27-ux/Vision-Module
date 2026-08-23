from __future__ import annotations

from pydantic import BaseModel, Field


class PoseKeypoint(BaseModel):
    name: str
    x: float
    y: float
    confidence: float


class PoseResult(BaseModel):
    track_id: int | None = None
    source_track_id: int | None = None
    source_bbox: list[float] | None = None
    pose_bbox: list[float] | None = None
    pose_track_match_score: float | None = None
    pose_frame_seq: int | None = None
    pose_timestamp: str | None = None
    keypoints: list[PoseKeypoint]
    skeleton_confidence: float
    visible_keypoint_count: int | None = None
    filtered_keypoints_count: int | None = None
    dropped_keypoints_count: int | None = None
    dropped_reasons: dict[str, int] | None = None
    pose_quality_level: str | None = None


class PoseStatus(BaseModel):
    pose_enabled: bool = False
    pose_provider: str = "disabled_placeholder"
    pose_pipeline_removed: bool = False
    placeholder_reason: str | None = None
    pose_fps: float = 0.0
    last_inference_latency_ms: float | None = None
    slow_inference_count: int = 0
    skipped_due_to_busy: int = 0
    worker_tick_count: int = 0
    inference_attempt_count: int = 0
    inference_success_count: int = 0
    pose_target_object_count: int = 0
    pose_attached_object_count: int = 0
    pose_valid_rate: float = 0.0
    inference_success_rate: float = 0.0
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    circuit_open: bool = False
    circuit_cooldown_remaining_ms: float | None = None
    last_error: str | None = None
    selected_track_id: int | None = None
    keypoint_inside_bbox_ratio: float | None = None
    keypoint_inside_source_bbox_ratio: float | None = None
    candidate_iou: float | None = None
    pose_track_match_score: float | None = None
    pose_match_iou: float | None = None
    pose_match_center_distance_ratio: float | None = None
    pose_bounds: list[float] | None = None
    torso_inside_bbox: bool | None = None
    skeleton_confidence: float | None = None
    rejected_reason: str | None = None
    pose_frame_seq: int | None = None
    tracking_frame_seq: int | None = None
    pose_tracking_seq_delta: int | None = None
    pose_frame_age_ms: float | None = None
    pose_model_path: str | None = None
    pose_quality_level: str | None = None
