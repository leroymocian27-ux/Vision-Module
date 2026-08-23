from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


NEW_POSE_PROVIDER = "new_pose_v1"
NEW_POSE_KEYPOINT_FORMAT = "coco17"
NEW_POSE_KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]


class NewPoseKeypoint(BaseModel):
    index: int = Field(ge=0, le=16)
    name: str
    x: float
    y: float
    confidence: float = Field(ge=0.0, le=1.0)
    visible: bool = False
    valid: bool = False
    reason: str | None = None


class NewPoseDebug(BaseModel):
    adapter: str = "new_pose_adapter"
    adapter_version: str = "v1"
    model_name: str = "TBD"
    model_version: str = "TBD"
    roi_crop: bool = True
    coordinate_restored: bool = True
    postprocess_version: str = "v1"
    shadow_only: bool = True
    use_for_fall: bool = False
    fallback_used: bool = False
    inference_ms: float | None = None
    error: str | None = None


class NewPoseResult(BaseModel):
    pose_provider: Literal["new_pose_v1"] = NEW_POSE_PROVIDER
    pose_enabled: bool = True
    pose_available: bool = False
    track_id: int | None = None
    source_track_id: int | None = None
    source_bbox: list[float] | None = None
    crop_bbox: list[float] | None = None
    pose_bbox: list[float] | None = None
    keypoint_format: Literal["coco17"] = NEW_POSE_KEYPOINT_FORMAT
    keypoint_count: int = 17
    valid_keypoint_count: int = 0
    visible_keypoint_count: int = 0
    filtered_keypoints_count: int = 0
    dropped_keypoints_count: int = 0
    dropped_reasons: dict[str, int] = Field(default_factory=dict)
    keypoints: list[NewPoseKeypoint] = Field(default_factory=list)
    skeleton_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    pose_frame_seq: int | None = None
    pose_timestamp: str | None = None
    debug: NewPoseDebug = Field(default_factory=NewPoseDebug)


def build_new_pose_unavailable(
    *,
    track_id: int | None = None,
    source_track_id: int | None = None,
    source_bbox: list[float] | None = None,
    crop_bbox: list[float] | None = None,
    pose_frame_seq: int | None = None,
    pose_timestamp: str | None = None,
    error: str | None = None,
) -> NewPoseResult:
    debug = NewPoseDebug(error=error)
    return NewPoseResult(
        pose_available=False,
        track_id=track_id,
        source_track_id=source_track_id,
        source_bbox=source_bbox,
        crop_bbox=crop_bbox,
        pose_frame_seq=pose_frame_seq,
        pose_timestamp=pose_timestamp,
        debug=debug,
    )
