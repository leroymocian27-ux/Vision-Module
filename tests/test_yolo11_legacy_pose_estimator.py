from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from app.pose.yolo11_legacy_pose_estimator import LegacyPoseCandidate, Yolo11LegacyPoseEstimator
from app.schemas.vision_result import DetectedObject


def _estimator() -> Yolo11LegacyPoseEstimator:
    estimator = Yolo11LegacyPoseEstimator.__new__(Yolo11LegacyPoseEstimator)
    estimator.settings = SimpleNamespace(
        yolo11_pose_confidence=0.12,
        yolo11_pose_smoothing=True,
        yolo11_pose_max_jump_ratio=0.18,
        yolo11_pose_min_match_iou=0.12,
        yolo11_pose_max_center_distance_ratio=0.65,
        yolo11_pose_match_score_threshold=0.30,
    )
    estimator._session_states = {}
    estimator._max_state_age_ms = 1600
    estimator._last_track_keys = set()
    estimator._resolved_model_path = "D:/Program/health(5-12)/pose_detection_model_bundle/yolo11n-pose.pt"
    return estimator


def _candidate(pose_bbox: list[float], skeleton_confidence: float = 0.9) -> LegacyPoseCandidate:
    points = np.array(
        [
            [pose_bbox[0] + 10, pose_bbox[1] + 10],
            [pose_bbox[0] + 20, pose_bbox[1] + 10],
            [pose_bbox[0] + 15, pose_bbox[1] + 20],
            [pose_bbox[0] + 12, pose_bbox[1] + 25],
            [pose_bbox[2] - 12, pose_bbox[1] + 25],
            [pose_bbox[0] + 20, pose_bbox[1] + 60],
            [pose_bbox[2] - 20, pose_bbox[1] + 60],
            [pose_bbox[0] + 15, pose_bbox[1] + 90],
            [pose_bbox[2] - 15, pose_bbox[1] + 90],
            [pose_bbox[0] + 10, pose_bbox[1] + 120],
            [pose_bbox[2] - 10, pose_bbox[1] + 120],
            [pose_bbox[0] + 30, pose_bbox[2] - 90],
            [pose_bbox[2] - 30, pose_bbox[2] - 90],
            [pose_bbox[0] + 30, pose_bbox[3] - 60],
            [pose_bbox[2] - 30, pose_bbox[3] - 60],
            [pose_bbox[0] + 30, pose_bbox[3] - 15],
            [pose_bbox[2] - 30, pose_bbox[3] - 15],
        ],
        dtype=float,
    )
    conf = np.ones((17,), dtype=float) * skeleton_confidence
    return LegacyPoseCandidate(
        index=0,
        keypoints=points,
        confidences=conf,
        pose_bbox=pose_bbox,
        skeleton_confidence=skeleton_confidence,
        box_confidence=0.8,
    )


class Yolo11LegacyPoseEstimatorTest(unittest.TestCase):
    def test_matches_best_candidate_to_track(self) -> None:
        estimator = _estimator()
        obj = DetectedObject(label="person", confidence=0.9, bbox=[100, 100, 200, 320], track_id=7)
        near = _candidate([105, 105, 195, 315], 0.92)
        far = _candidate([380, 120, 470, 320], 0.95)

        matched = estimator._match_candidates([obj], [near, far])

        self.assertIn(7, matched)
        chosen, debug = matched[7]
        self.assertEqual(chosen.pose_bbox, near.pose_bbox)
        self.assertGreater(debug["pose_track_match_score"], 0.30)
        self.assertGreater(debug["pose_match_iou"], 0.12)

    def test_rejects_low_score_candidate(self) -> None:
        estimator = _estimator()
        obj = DetectedObject(label="person", confidence=0.9, bbox=[100, 100, 200, 320], track_id=8)
        far = _candidate([420, 120, 520, 340], 0.95)

        matched = estimator._match_candidates([obj], [far])

        self.assertNotIn(8, matched)

    def test_smoothing_limits_large_jump(self) -> None:
        estimator = _estimator()
        first = [
            {"index": 11, "name": "left_hip", "x": 120.0, "y": 210.0, "score": 0.9, "tracked": False, "estimated": False},
        ]
        second = [
            {"index": 11, "name": "left_hip", "x": 260.0, "y": 330.0, "score": 0.92, "tracked": False, "estimated": False},
        ]

        initial = estimator._smooth_points(track_id=1, points=first, bbox=[100, 100, 200, 320])
        smoothed = estimator._smooth_points(track_id=1, points=second, bbox=[100, 100, 200, 320])

        self.assertEqual(initial[0]["x"], 120.0)
        self.assertLess(smoothed[0]["x"], 260.0)
        self.assertLess(smoothed[0]["y"], 330.0)
        self.assertTrue(smoothed[0]["tracked"])

    def test_origin_like_keypoint_is_zeroed(self) -> None:
        estimator = _estimator()
        candidate = _candidate([100, 100, 200, 320], 0.9)
        candidate.keypoints[15] = np.array([0.0, 0.0], dtype=float)
        candidate.confidences[15] = 0.4

        points = estimator._candidate_points(candidate)

        self.assertEqual(points[15]["score"], 0.0)

    def test_low_confidence_leg_keypoint_is_zeroed(self) -> None:
        estimator = _estimator()
        candidate = _candidate([100, 100, 200, 320], 0.9)
        candidate.confidences[13] = 0.24

        points = estimator._candidate_points(candidate)

        self.assertEqual(points[13]["name"], "left_knee")
        self.assertEqual(points[13]["score"], 0.0)


if __name__ == "__main__":
    unittest.main()
