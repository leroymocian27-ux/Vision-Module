from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from app.pose.yolo_pose_estimator import YoloPoseEstimator


def _estimator() -> YoloPoseEstimator:
    estimator = YoloPoseEstimator.__new__(YoloPoseEstimator)
    estimator.settings = SimpleNamespace(
        yolo_pose_confidence=0.25,
        pose_min_skeleton_confidence=0.35,
        pose_min_keypoint_inside_ratio=0.65,
        pose_min_fallen_keypoint_inside_ratio=0.60,
        pose_min_candidate_iou=0.25,
        pose_min_fallen_candidate_iou=0.15,
    )
    return estimator


class YoloPoseCandidateSelectionTest(unittest.TestCase):
    def test_rejects_pose_that_only_fits_expanded_bbox(self) -> None:
        estimator = _estimator()
        xy = np.array([[[10, 10], [20, 10], [30, 10], [40, 10], [50, 10], [60, 10]]], dtype=float)
        conf = np.ones((1, 6), dtype=float) * 0.9

        selected, debug = estimator._select_candidate(
            xy_all=xy,
            conf_all=conf,
            box_xyxy=None,
            box_conf=None,
            left=0,
            top=0,
            source_bbox=[100, 100, 200, 240],
            expanded_bbox=[0, 0, 220, 260],
        )

        self.assertIsNone(selected)
        self.assertEqual(debug["rejected_reason"], "keypoints_outside_bbox")

    def test_accepts_aligned_seated_pose_candidate(self) -> None:
        estimator = _estimator()
        xy = np.array(
            [[
                [130, 115],
                [128, 112],
                [132, 112],
                [126, 113],
                [134, 113],
                [125, 145],
                [165, 145],
                [120, 175],
                [170, 175],
                [118, 205],
                [172, 205],
                [128, 210],
                [162, 210],
                [122, 250],
                [168, 250],
                [120, 285],
                [170, 285],
            ]],
            dtype=float,
        )
        conf = np.ones((1, 17), dtype=float) * 0.85

        selected, debug = estimator._select_candidate(
            xy_all=xy,
            conf_all=conf,
            box_xyxy=np.array([[115, 105, 180, 295]], dtype=float),
            box_conf=np.array([0.8], dtype=float),
            left=0,
            top=0,
            source_bbox=[110, 100, 190, 300],
            expanded_bbox=[100, 90, 200, 310],
        )

        self.assertEqual(selected, 0)
        self.assertIsNone(debug["rejected_reason"])
        self.assertGreaterEqual(debug["candidate_iou"], 0.25)
        self.assertTrue(debug["torso_inside_bbox"])

    def test_rejects_candidate_with_torso_outside_bbox(self) -> None:
        estimator = _estimator()
        xy = np.array(
            [[
                [130, 120],
                [132, 120],
                [134, 120],
                [136, 120],
                [138, 120],
                [120, 145],
                [45, 40],
                [42, 80],
                [47, 80],
                [135, 160],
                [140, 160],
                [40, 95],
                [45, 95],
                [135, 210],
                [145, 210],
                [135, 250],
                [145, 250],
            ]],
            dtype=float,
        )
        conf = np.ones((1, 17), dtype=float) * 0.9

        selected, debug = estimator._select_candidate(
            xy_all=xy,
            conf_all=conf,
            box_xyxy=np.array([[110, 100, 190, 300]], dtype=float),
            box_conf=np.array([0.8], dtype=float),
            left=0,
            top=0,
            source_bbox=[110, 100, 190, 300],
            expanded_bbox=[90, 80, 210, 320],
        )

        self.assertIsNone(selected)
        self.assertEqual(debug["rejected_reason"], "torso_outside_bbox")


if __name__ == "__main__":
    unittest.main()
