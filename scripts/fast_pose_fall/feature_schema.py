from __future__ import annotations

from datetime import datetime
from typing import Any


FEATURE_SCHEMA_VERSION = "fast_pose_fall_features_v1"
FEATURE_SCHEMA_DATE = "20260622"


FEATURE_FIELDS = [
    "asset_id",
    "video_id",
    "dataset",
    "source",
    "split",
    "label",
    "group_id",
    "frame_index",
    "time_sec",
    "track_id",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "bbox_width",
    "bbox_height",
    "bbox_area",
    "bbox_center_x",
    "bbox_center_y",
    "bbox_aspect_ratio",
    "bbox_center_y_delta",
    "bbox_height_delta",
    "velocity_y",
    "speed",
    "track_age_sec",
    "stillness_duration_sec",
    "fall_score",
    "person_confidence",
    "pose_keypoint_count",
    "pose_confidence_mean",
    "torso_angle",
    "hip_height_ratio",
    "is_partial_body",
    "is_edge_person",
    "is_occluded",
    "scene_tags",
    "hard_negative",
]


NULLABLE_FIELDS = {
    "track_id",
    "bbox_x1",
    "bbox_y1",
    "bbox_x2",
    "bbox_y2",
    "bbox_width",
    "bbox_height",
    "bbox_area",
    "bbox_center_x",
    "bbox_center_y",
    "bbox_aspect_ratio",
    "bbox_center_y_delta",
    "bbox_height_delta",
    "velocity_y",
    "speed",
    "track_age_sec",
    "stillness_duration_sec",
    "fall_score",
    "person_confidence",
    "pose_keypoint_count",
    "pose_confidence_mean",
    "torso_angle",
    "hip_height_ratio",
}


def feature_schema() -> dict[str, Any]:
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "schema_date": FEATURE_SCHEMA_DATE,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "level": "frame",
        "fields": FEATURE_FIELDS,
        "nullable_fields": sorted(NULLABLE_FIELDS),
        "notes": [
            "Frame-level offline feature schema for fast pose fall dataset preparation.",
            "Pose fields are nullable; missing pose must not fail extraction or evaluation.",
            "Pseudo labels are excluded by clean split policy and must not be used as ground truth.",
            "fall_score is a baseline heuristic score in this stage, not a trained final model output.",
        ],
    }


def empty_feature_record() -> dict[str, Any]:
    return {field: None for field in FEATURE_FIELDS}
