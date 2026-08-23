from __future__ import annotations

from typing import Any

from app.schemas.vision_result import DetectedObject

POSE_DISABLED_PROVIDER = "disabled_placeholder"
POSE_DISABLED_REASON = "pose_pipeline_removed_pending_reconfiguration"


def pose_runtime_enabled(enable_pose: bool, pose_provider: str | None) -> bool:
    provider = str(pose_provider or "").strip().lower()
    return bool(enable_pose) and provider != POSE_DISABLED_PROVIDER


def effective_pose_provider(enable_pose: bool, pose_provider: str | None) -> str:
    provider = str(pose_provider or "").strip().lower()
    if not pose_runtime_enabled(enable_pose, provider):
        return POSE_DISABLED_PROVIDER
    return provider or POSE_DISABLED_PROVIDER


def is_pose_placeholder_payload(pose: dict[str, Any] | None) -> bool:
    if not isinstance(pose, dict):
        return False
    if str(pose.get("pose_provider") or "").strip().lower() == POSE_DISABLED_PROVIDER:
        return True
    debug = pose.get("debug")
    return isinstance(debug, dict) and bool(debug.get("pose_disabled"))


def pose_has_visible_keypoints(pose: dict[str, Any] | None, threshold: float = 0.2) -> bool:
    if not isinstance(pose, dict) or is_pose_placeholder_payload(pose):
        return False
    quality_level = str(pose.get("pose_quality_level") or "").strip().lower()
    if quality_level in {"pose_absent", "low_quality", "pose_track_mismatch"}:
        return False
    debug = pose.get("debug")
    if isinstance(debug, dict) and debug.get("rejected_reason"):
        return False
    keypoints = pose.get("keypoints")
    if not isinstance(keypoints, list):
        return False
    for point in keypoints:
        if not isinstance(point, dict):
            continue
        try:
            if float(point.get("confidence") or 0.0) >= threshold:
                return True
        except (TypeError, ValueError):
            continue
    return False


def build_pose_placeholder(
    item: DetectedObject | None = None,
    *,
    frame_seq: int | None = None,
    frame_timestamp: str | None = None,
    tracking_frame_seq: int | None = None,
    frame_age_ms: float | None = None,
    extra_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_bbox = None
    track_id = None
    if item is not None:
        source_bbox = [float(value) for value in item.bbox]
        track_id = item.track_id
    debug = {
        "pose_disabled": True,
        "pose_pipeline_removed": True,
        "placeholder": True,
        "reason": POSE_DISABLED_REASON,
        "pose_provider": POSE_DISABLED_PROVIDER,
        "pose_frame_seq": frame_seq,
        "tracking_frame_seq": tracking_frame_seq,
        "pose_frame_age_ms": round(frame_age_ms, 2) if frame_age_ms is not None else None,
    }
    if isinstance(extra_debug, dict):
        debug.update(extra_debug)
    return {
        "track_id": track_id,
        "source_track_id": track_id,
        "source_bbox": source_bbox,
        "pose_bbox": None,
        "pose_track_match_score": None,
        "pose_frame_seq": frame_seq,
        "pose_timestamp": frame_timestamp,
        "pose_provider": POSE_DISABLED_PROVIDER,
        "keypoints": [],
        "skeleton_confidence": None,
        "visible_keypoint_count": 0,
        "filtered_keypoints_count": 0,
        "dropped_keypoints_count": 0,
        "dropped_reasons": {},
        "debug": debug,
    }
