from __future__ import annotations

import math
import time

from app.behavior.schemas import BehaviorFeatures
from app.core.config import Settings
from app.schemas.vision_result import DetectedObject


class BehaviorFeatureExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._history: dict[tuple[str, int], tuple[float, tuple[float, float]]] = {}
        self._still_since: dict[tuple[str, int], float] = {}

    def extract(self, camera_id: str, obj: DetectedObject, now: float | None = None) -> BehaviorFeatures:
        now = now or time.monotonic()
        keypoints = self._keypoints_by_name(obj.pose)
        x1, y1, x2, y2 = obj.bbox
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        center = ((x1 + x2) / 2, (y1 + y2) / 2)

        head_y = self._mean_y(keypoints, ["nose", "left_eye", "right_eye", "left_ear", "right_ear"])
        shoulder_y = self._mean_y(keypoints, ["left_shoulder", "right_shoulder"])
        hip_y = self._mean_y(keypoints, ["left_hip", "right_hip"])
        ankle_y = self._mean_y(keypoints, ["left_ankle", "right_ankle"])
        shoulder_center = self._mean_point(keypoints, ["left_shoulder", "right_shoulder"])
        hip_center = self._mean_point(keypoints, ["left_hip", "right_hip"])
        torso_angle = self._torso_angle(shoulder_center, hip_center)
        velocity, vertical_velocity, still_duration = self._motion_features(camera_id, obj, center, now)

        return BehaviorFeatures(
            head_y=head_y,
            shoulder_y=shoulder_y,
            hip_y=hip_y,
            ankle_y=ankle_y,
            torso_angle=torso_angle,
            bbox_aspect_ratio=round(width / height, 4) if height > 0 else None,
            body_center=[round(center[0], 2), round(center[1], 2)],
            velocity=velocity,
            still_duration=still_duration,
            vertical_velocity=vertical_velocity,
        )

    def reset_track(self, camera_id: str, track_id: int) -> None:
        key = (camera_id, track_id)
        self._history.pop(key, None)
        self._still_since.pop(key, None)

    def _motion_features(
        self,
        camera_id: str,
        obj: DetectedObject,
        center: tuple[float, float],
        now: float,
    ) -> tuple[float | None, float | None, float]:
        if obj.track_id is None:
            return None, None, 0.0
        key = (camera_id, obj.track_id)
        previous = self._history.get(key)
        self._history[key] = (now, center)
        if previous is None:
            self._still_since[key] = now
            return None, None, 0.0

        prev_time, prev_center = previous
        elapsed = max(now - prev_time, 1e-6)
        dx = center[0] - prev_center[0]
        dy = center[1] - prev_center[1]
        velocity = math.hypot(dx, dy) / elapsed
        vertical_velocity = dy / elapsed
        if velocity <= self.settings.behavior_still_velocity_px_per_sec:
            still_since = self._still_since.setdefault(key, prev_time)
        else:
            still_since = now
            self._still_since[key] = now
        return round(velocity, 2), round(vertical_velocity, 2), round(max(0.0, now - still_since), 2)

    @staticmethod
    def _keypoints_by_name(pose: dict | None) -> dict[str, dict]:
        if not pose:
            return {}
        raw_keypoints = pose.get("keypoints") or []
        return {
            item.get("name"): item
            for item in raw_keypoints
            if item.get("name") and item.get("confidence", 0.0) >= 0.2
        }

    @staticmethod
    def _mean_y(keypoints: dict[str, dict], names: list[str]) -> float | None:
        points = [keypoints[name] for name in names if name in keypoints]
        if not points:
            return None
        return round(sum(float(item["y"]) for item in points) / len(points), 2)

    @staticmethod
    def _mean_point(keypoints: dict[str, dict], names: list[str]) -> tuple[float, float] | None:
        points = [keypoints[name] for name in names if name in keypoints]
        if not points:
            return None
        x = sum(float(item["x"]) for item in points) / len(points)
        y = sum(float(item["y"]) for item in points) / len(points)
        return x, y

    @staticmethod
    def _torso_angle(
        shoulder_center: tuple[float, float] | None,
        hip_center: tuple[float, float] | None,
    ) -> float | None:
        if shoulder_center is None or hip_center is None:
            return None
        dx = hip_center[0] - shoulder_center[0]
        dy = hip_center[1] - shoulder_center[1]
        if abs(dy) < 1e-6:
            return 90.0
        return round(math.degrees(math.atan2(dx, dy)), 2)
