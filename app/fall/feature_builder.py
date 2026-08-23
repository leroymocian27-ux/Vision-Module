from __future__ import annotations

import time
from dataclasses import dataclass

from app.detection.realtime_result_store import ObjectSnapshot
from app.pose.placeholders import pose_has_visible_keypoints
from app.schemas.vision_result import DetectedObject

STRONG_FALL_LABELS = {"fall", "fallen"}
TRANSITION_FALL_LABELS = {"falling"}
WEAK_FALL_LABELS = {"lying"}


@dataclass(frozen=True)
class FallFeatureContext:
    frame_width: int
    frame_height: int
    fall_detection: ObjectSnapshot | None = None


class FallFeatureBuilder:
    """Builds one shared evidence payload for temporal, fusion, debug, and UI."""

    def build_for_objects(
        self,
        *,
        objects: list[DetectedObject],
        context: FallFeatureContext,
    ) -> list[DetectedObject]:
        return [self.build_for_object(item, context=context) for item in objects]

    def build_for_object(self, item: DetectedObject, *, context: FallFeatureContext) -> DetectedObject:
        if item.label != "person":
            return item
        features = dict(item.features or {})
        temporal = item.temporal if isinstance(item.temporal, dict) else {}
        temporal_features = temporal.get("features") if isinstance(temporal.get("features"), dict) else {}
        features["motion"] = self._motion_features(item, temporal_features, context)
        features["pose"] = self._pose_features(item, temporal_features)
        features["fall_hint"] = self._fall_hint_features(item, context.fall_detection)
        return item.model_copy(update={"features": features})

    @staticmethod
    def _motion_features(
        item: DetectedObject,
        temporal_features: dict,
        context: FallFeatureContext,
    ) -> dict[str, object]:
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        frame_width = max(1.0, float(context.frame_width or 1))
        frame_height = max(1.0, float(context.frame_height or 1))
        aspect_ratio = width / height if height > 0 else 0.0
        source = "temporal_features" if temporal_features else "bbox"
        return {
            "bbox_center_x": round((x1 + x2) / 2, 4),
            "bbox_center_y": round((y1 + y2) / 2, 4),
            "bbox_center_x_norm": round(((x1 + x2) / 2) / frame_width, 4),
            "bbox_center_y_norm": round(((y1 + y2) / 2) / frame_height, 4),
            "bbox_width": round(width, 4),
            "bbox_height": round(height, 4),
            "bbox_width_norm": round(width / frame_width, 4),
            "bbox_height_norm": round(height / frame_height, 4),
            "aspect_ratio": round(aspect_ratio, 4),
            "delta_x": float(temporal_features.get("delta_x") or 0.0),
            "delta_y": float(temporal_features.get("delta_y") or 0.0),
            "velocity_x": float(temporal_features.get("velocity_x") or 0.0),
            "velocity_y": float(temporal_features.get("velocity_y") or 0.0),
            "speed": float(temporal_features.get("speed") or 0.0),
            "tracking_stable": item.track_id is not None,
            "tracking_source": (item.fusion_debug or {}).get("tracking_source") or "tracked",
            "source": source,
        }

    @staticmethod
    def _pose_features(item: DetectedObject, temporal_features: dict) -> dict[str, object]:
        pose = item.pose if isinstance(item.pose, dict) else None
        pose_available = bool(temporal_features.get("pose_available") is True) or pose_has_visible_keypoints(pose)
        pose_quality_level = (pose or {}).get("pose_quality_level") if pose else None
        pose_confidence = temporal_features.get("pose_confidence")
        if pose_confidence is None and pose is not None:
            pose_confidence = pose.get("skeleton_confidence")
        head_ratio = temporal_features.get("head_height_ratio")
        hip_ratio = temporal_features.get("hip_height_ratio")
        aspect_ratio = float(temporal_features.get("aspect_ratio") or 0.0)
        low_by_pose = (
            head_ratio is not None
            and hip_ratio is not None
            and float(head_ratio) > 0.45
            and float(hip_ratio) > 0.65
        )
        low_by_bbox = aspect_ratio >= 0.95
        return {
            "pose_available": pose_available,
            "pose_quality_level": pose_quality_level,
            "pose_confidence": float(pose_confidence or 0.0),
            "torso_angle": temporal_features.get("torso_angle"),
            "head_height_ratio": head_ratio,
            "hip_height_ratio": hip_ratio,
            "low_posture": bool(low_by_pose or low_by_bbox),
            "low_posture_source": "pose" if low_by_pose else ("bbox" if low_by_bbox else None),
            "rejected_reason": (pose or {}).get("debug", {}).get("rejected_reason") if pose else None,
        }

    @staticmethod
    def _fall_hint_features(item: DetectedObject, fall_detection: ObjectSnapshot | None) -> dict[str, object]:
        if fall_detection is None or not fall_detection.objects:
            return {
                "available": False,
                "strong_hint": False,
                "weak_hint": False,
                "reason": "no_fall_detection",
            }
        best = None
        best_iou = 0.0
        for candidate in fall_detection.objects:
            iou = FallFeatureBuilder._iou(item.bbox, candidate.bbox)
            if best is None or iou > best_iou or (iou == best_iou and candidate.confidence > best.confidence):
                best = candidate
                best_iou = iou
        if best is None:
            return {
                "available": False,
                "strong_hint": False,
                "weak_hint": False,
                "reason": "no_match",
            }
        label = str(best.label).lower()
        age_ms = round((time.monotonic() - fall_detection.monotonic_at) * 1000, 2)
        is_matched = best_iou >= 0.05
        transition_hint = label in TRANSITION_FALL_LABELS and is_matched
        return {
            "available": is_matched,
            "strongest_label": label,
            "confidence": float(best.confidence),
            "matched_track_id": item.track_id,
            "iou_with_track": round(best_iou, 4),
            "age_ms": age_ms,
            "strong_hint": label in STRONG_FALL_LABELS and is_matched,
            "transition_hint": transition_hint,
            "weak_hint": (label in WEAK_FALL_LABELS and is_matched) or transition_hint,
            "source": "yolo_fall_detector",
            "bbox": [float(value) for value in best.bbox],
        }

    @staticmethod
    def _iou(a: list[float], b: list[float]) -> float:
        ax1, ay1, ax2, ay2 = [float(value) for value in a]
        bx1, by1, bx2, by2 = [float(value) for value in b]
        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter = inter_w * inter_h
        if inter <= 0:
            return 0.0
        area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
        area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0
