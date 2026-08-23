from __future__ import annotations

import math
import time

from app.schemas.common import utc_now_iso
from app.schemas.vision_result import DetectedObject
from app.pose.placeholders import pose_has_visible_keypoints
from app.temporal.schemas import TargetFeature


class TargetFeatureExtractor:
    def __init__(self, pose_enabled: bool = True) -> None:
        self.pose_enabled = pose_enabled

    def extract(
        self,
        camera_id: str,
        target_object: DetectedObject,
        timestamp: float | None = None,
        previous_feature: TargetFeature | None = None,
    ) -> TargetFeature:
        del camera_id  # Reserved for future camera-specific normalization.
        now = timestamp if timestamp is not None else time.monotonic()
        x1, y1, x2, y2 = target_object.bbox
        width = max(0.0, float(x2 - x1))
        height = max(0.0, float(y2 - y1))
        center_x = float(x1 + x2) / 2
        center_y = float(y1 + y2) / 2
        delta_x = 0.0
        delta_y = 0.0
        velocity_x = 0.0
        velocity_y = 0.0
        speed = 0.0
        if previous_feature is not None:
            elapsed = max(now - previous_feature.monotonic_time, 1e-6)
            delta_x = center_x - previous_feature.bbox_center_x
            delta_y = center_y - previous_feature.bbox_center_y
            velocity_x = delta_x / elapsed
            velocity_y = delta_y / elapsed
            speed = math.hypot(velocity_x, velocity_y)

        pose_metrics = self._pose_metrics(target_object.pose, y1=y1, height=height)

        return TargetFeature(
            track_id=target_object.track_id,
            timestamp=utc_now_iso(),
            monotonic_time=now,
            object_confidence=round(float(target_object.confidence), 4),
            bbox_center_x=round(center_x, 4),
            bbox_center_y=round(center_y, 4),
            bbox_width=round(width, 4),
            bbox_height=round(height, 4),
            aspect_ratio=round(width / height, 4) if height > 0 else 0.0,
            delta_x=round(delta_x, 4),
            delta_y=round(delta_y, 4),
            velocity_x=round(velocity_x, 4),
            velocity_y=round(velocity_y, 4),
            speed=round(speed, 4),
            **pose_metrics,
        )

    def _pose_metrics(self, pose: dict | None, y1: float, height: float) -> dict:
        if not self.pose_enabled:
            return self._empty_pose_metrics(quality_level="pose_absent", rejected_reason="pose_disabled")
        if not pose:
            return self._empty_pose_metrics()
        quality_level = str(pose.get("pose_quality_level") or "valid")
        rejected_reason = self._pose_rejected_reason(pose)
        if not pose_has_visible_keypoints(pose):
            return self._empty_pose_metrics(
                quality_level=quality_level if quality_level else "low_quality",
                rejected_reason=rejected_reason,
            )

        keypoints = self._keypoints_by_name(pose)
        if not keypoints:
            return self._empty_pose_metrics(
                quality_level=quality_level if quality_level else "low_quality",
                rejected_reason=rejected_reason or "no_visible_keypoints",
            )

        shoulder = self._mean_point(keypoints, ["left_shoulder", "right_shoulder"])
        hip = self._mean_point(keypoints, ["left_hip", "right_hip"])
        head_y = self._mean_y(keypoints, ["nose", "left_eye", "right_eye", "left_ear", "right_ear"])
        hip_y = hip[1] if hip is not None else None
        confidence = self._mean_confidence(keypoints)
        torso_angle = self._torso_angle(shoulder, hip)

        return {
            "pose_available": True,
            "pose_confidence": round(confidence, 4),
            "torso_angle": torso_angle,
            "hip_height_ratio": self._height_ratio(hip_y, y1, height),
            "head_height_ratio": self._height_ratio(head_y, y1, height),
            "pose_quality_level": quality_level,
            "pose_rejected_reason": None,
        }

    @staticmethod
    def _empty_pose_metrics(
        *,
        quality_level: str = "pose_absent",
        rejected_reason: str | None = None,
    ) -> dict:
        return {
            "pose_available": False,
            "pose_confidence": 0.0,
            "torso_angle": None,
            "hip_height_ratio": None,
            "head_height_ratio": None,
            "pose_quality_level": quality_level,
            "pose_rejected_reason": rejected_reason,
        }

    @staticmethod
    def _pose_rejected_reason(pose: dict) -> str | None:
        debug = pose.get("debug")
        if isinstance(debug, dict) and debug.get("rejected_reason"):
            return str(debug.get("rejected_reason"))
        return None

    @staticmethod
    def _keypoints_by_name(pose: dict) -> dict[str, dict]:
        raw_keypoints = pose.get("keypoints") or []
        return {
            item.get("name"): item
            for item in raw_keypoints
            if item.get("name") and item.get("confidence", 0.0) >= 0.2
        }

    @staticmethod
    def _mean_point(keypoints: dict[str, dict], names: list[str]) -> tuple[float, float] | None:
        points = [keypoints[name] for name in names if name in keypoints]
        if not points:
            return None
        x = sum(float(item["x"]) for item in points) / len(points)
        y = sum(float(item["y"]) for item in points) / len(points)
        return x, y

    @staticmethod
    def _mean_y(keypoints: dict[str, dict], names: list[str]) -> float | None:
        points = [keypoints[name] for name in names if name in keypoints]
        if not points:
            return None
        return sum(float(item["y"]) for item in points) / len(points)

    @staticmethod
    def _mean_confidence(keypoints: dict[str, dict]) -> float:
        values = [float(item.get("confidence", 0.0)) for item in keypoints.values()]
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _torso_angle(
        shoulder: tuple[float, float] | None,
        hip: tuple[float, float] | None,
    ) -> float | None:
        if shoulder is None or hip is None:
            return None
        dx = hip[0] - shoulder[0]
        dy = hip[1] - shoulder[1]
        if abs(dy) < 1e-6:
            return 90.0
        return round(math.degrees(math.atan2(dx, dy)), 4)

    @staticmethod
    def _height_ratio(y: float | None, y1: float, height: float) -> float | None:
        if y is None or height <= 0:
            return None
        return round((y - y1) / height, 4)
