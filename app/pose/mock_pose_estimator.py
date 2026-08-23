from __future__ import annotations

import numpy as np

from app.pose.schemas import PoseKeypoint, PoseResult
from app.pose.yolo_pose_estimator import COCO_KEYPOINT_NAMES
from app.schemas.vision_result import DetectedObject


class MockPoseEstimator:
    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        del frame
        results: dict[int, PoseResult] = {}
        for item in objects:
            if not item.is_target or item.track_id is None:
                continue
            x1, y1, x2, y2 = item.bbox
            width = x2 - x1
            height = y2 - y1
            points = [
                (0.50, 0.10),
                (0.43, 0.08),
                (0.57, 0.08),
                (0.36, 0.11),
                (0.64, 0.11),
                (0.34, 0.26),
                (0.66, 0.26),
                (0.25, 0.43),
                (0.75, 0.43),
                (0.20, 0.60),
                (0.80, 0.60),
                (0.42, 0.56),
                (0.58, 0.56),
                (0.38, 0.76),
                (0.62, 0.76),
                (0.35, 0.96),
                (0.65, 0.96),
            ]
            results[item.track_id] = PoseResult(
                track_id=item.track_id,
                skeleton_confidence=0.75,
                keypoints=[
                    PoseKeypoint(
                        name=COCO_KEYPOINT_NAMES[index],
                        x=round(x1 + width * px, 2),
                        y=round(y1 + height * py, 2),
                        confidence=0.75,
                    )
                    for index, (px, py) in enumerate(points)
                ],
            )
        return results
