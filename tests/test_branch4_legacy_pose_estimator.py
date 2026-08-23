from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from app.pose.branch4_legacy_pose_estimator import Branch4LegacyPoseEstimator
from app.schemas.vision_result import DetectedObject


class _FakeTensor:
    def __init__(self, values) -> None:
        self._values = np.array(values, dtype=np.float32)

    def __len__(self) -> int:
        return len(self._values)

    def cpu(self):
        return self

    def numpy(self):
        return self._values


class _FakeKeypoints:
    def __init__(self, xy, conf) -> None:
        self.xy = _FakeTensor(xy)
        self.conf = _FakeTensor(conf)


class _FakePrediction:
    def __init__(self, xy, conf) -> None:
        self.keypoints = _FakeKeypoints(xy, conf)


class _FakeModel:
    def __init__(self, xy, conf) -> None:
        self._prediction = _FakePrediction(xy, conf)
        self.calls: list[dict[str, object]] = []

    def predict(self, image, **kwargs):
        self.calls.append(
            {
                "shape": tuple(image.shape),
                "kwargs": kwargs,
            }
        )
        return [self._prediction]


def _estimator() -> Branch4LegacyPoseEstimator:
    estimator = Branch4LegacyPoseEstimator.__new__(Branch4LegacyPoseEstimator)
    estimator.settings = SimpleNamespace(
        yolo11_pose_model_path="D:/Program/health(5-12)/pose_detection_model_bundle/yolo11n-pose.pt",
        yolo11_pose_device=None,
        yolo11_pose_smoothing=True,
        yolo11_pose_max_jump_ratio=0.18,
        branch4_pose_confidence=0.2,
        branch4_pose_imgsz=640,
        branch4_pose_half=True,
        branch4_pose_crop_padding_ratio=0.18,
    )
    estimator._model = None
    estimator._last_error = None
    estimator._last_debug = {}
    estimator._last_debug_by_track = {}
    estimator._session_states = {}
    estimator._max_state_age_ms = 1600
    estimator._resolved_model_path = "D:/Program/health(5-12)/pose_detection_model_bundle/yolo11n-pose.pt"
    return estimator


def _keypoints(base_x: float, base_y: float) -> tuple[list[list[list[float]]], list[list[float]]]:
    xy = [[
        [base_x + 10, base_y + 10],
        [base_x + 18, base_y + 10],
        [base_x + 14, base_y + 20],
        [base_x + 10, base_y + 25],
        [base_x + 22, base_y + 25],
        [base_x + 8, base_y + 60],
        [base_x + 24, base_y + 60],
        [base_x + 6, base_y + 92],
        [base_x + 26, base_y + 92],
        [base_x + 5, base_y + 125],
        [base_x + 28, base_y + 125],
        [base_x + 10, base_y + 122],
        [base_x + 22, base_y + 122],
        [base_x + 10, base_y + 158],
        [base_x + 22, base_y + 158],
        [base_x + 12, base_y + 192],
        [base_x + 20, base_y + 192],
    ]]
    conf = [[0.95] * 17]
    return xy, conf


class Branch4LegacyPoseEstimatorTest(unittest.TestCase):
    def test_crop_roi_uses_branch4_padding_ratio(self) -> None:
        estimator = _estimator()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        crop = estimator._crop_target_roi(frame, [100.0, 120.0, 200.0, 320.0])

        self.assertIsNotNone(crop)
        _, left, top, roi_bbox = crop
        self.assertEqual(left, 82)
        self.assertEqual(top, 84)
        self.assertEqual(roi_bbox, [82.0, 84.0, 218.0, 356.0])

    def test_estimate_restores_global_coordinates_for_target_only_track(self) -> None:
        estimator = _estimator()
        xy, conf = _keypoints(0.0, 0.0)
        estimator._model = _FakeModel(xy, conf)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        objects = [
            DetectedObject(label="person", confidence=0.9, bbox=[40.0, 80.0, 90.0, 180.0], track_id=1, is_target=False),
            DetectedObject(label="person", confidence=0.95, bbox=[100.0, 120.0, 200.0, 320.0], track_id=7, is_target=True),
        ]

        result = estimator.estimate(frame, objects)

        self.assertEqual(list(result.keys()), [7])
        pose = result[7]
        self.assertEqual(pose.track_id, 7)
        self.assertEqual(pose.source_track_id, 7)
        self.assertEqual(pose.keypoints[0].x, 92.0)
        self.assertEqual(pose.keypoints[0].y, 94.0)
        self.assertEqual(estimator.last_debug["selected_track_id"], 7)
        self.assertEqual(estimator.last_debug["mode"], "target-only crop pose")
        self.assertEqual(estimator.last_debug["roi_bbox"], [82.0, 84.0, 218.0, 356.0])
        self.assertEqual(pose.visible_keypoint_count, 17)
        self.assertEqual(pose.filtered_keypoints_count, 17)
        self.assertEqual(pose.dropped_keypoints_count, 0)

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

    def test_filters_low_conf_legs_and_edge_points_from_pose_bounds(self) -> None:
        estimator = _estimator()
        points = [
            {"index": 0, "name": "nose", "x": 34.2, "y": 165.8, "score": 0.9926},
            {"index": 1, "name": "left_eye", "x": 42.0, "y": 156.8, "score": 0.9876},
            {"index": 5, "name": "left_shoulder", "x": 78.2, "y": 213.5, "score": 0.9875},
            {"index": 6, "name": "right_shoulder", "x": 0.0, "y": 213.0, "score": 0.9316},
            {"index": 8, "name": "right_elbow", "x": 2.4, "y": 274.1, "score": 0.4820},
            {"index": 11, "name": "left_hip", "x": 73.2, "y": 342.1, "score": 0.7729},
            {"index": 12, "name": "right_hip", "x": 22.4, "y": 341.0, "score": 0.6038},
            {"index": 13, "name": "left_knee", "x": 70.6, "y": 360.0, "score": 0.0174},
            {"index": 14, "name": "right_knee", "x": 22.7, "y": 360.0, "score": 0.0084},
            {"index": 15, "name": "left_ankle", "x": 49.8, "y": 360.0, "score": 0.0011},
            {"index": 16, "name": "right_ankle", "x": 29.0, "y": 360.0, "score": 0.0007},
        ]

        filtered, dropped, dropped_reasons = estimator._filter_valid_points(points, frame_width=640, frame_height=360)
        pose_bounds = estimator._pose_bounds(filtered)

        self.assertEqual(pose_bounds, [2.4, 156.8, 78.2, 342.1])
        self.assertEqual(len(filtered), 6)
        self.assertEqual(len(dropped), 5)
        self.assertEqual(dropped_reasons["edge_point"], 1)
        self.assertEqual(dropped_reasons["low_confidence_lower_body"], 4)

    def test_estimate_exposes_debug_counts_for_filtered_points(self) -> None:
        estimator = _estimator()
        xy = [[
            [34.23, 97.82],
            [41.97, 88.75],
            [24.41, 89.15],
            [52.71, 94.25],
            [9.62, 95.38],
            [78.22, 145.50],
            [0.00, 144.96],
            [99.99, 216.00],
            [2.36, 206.10],
            [79.86, 251.48],
            [7.46, 216.50],
            [73.21, 274.12],
            [22.39, 272.95],
            [70.56, 292.00],
            [22.69, 292.00],
            [49.76, 292.00],
            [29.02, 292.00],
        ]]
        conf = [[
            0.9926, 0.9876, 0.9618, 0.8114, 0.4034,
            0.9875, 0.9316, 0.8961, 0.4820, 0.7384, 0.4281,
            0.7729, 0.6038, 0.0174, 0.0084, 0.0011, 0.0007,
        ]]
        estimator._model = _FakeModel(xy, conf)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        objects = [
            DetectedObject(label="person", confidence=0.95, bbox=[0.04, 111.8, 110.65, 353.32], track_id=7, is_target=True),
        ]

        result = estimator.estimate(frame, objects)

        pose = result[7]
        self.assertEqual(pose.visible_keypoint_count, 12)
        self.assertEqual(pose.filtered_keypoints_count, 12)
        self.assertEqual(pose.dropped_keypoints_count, 5)
        self.assertEqual(pose.dropped_reasons, {"edge_point": 1, "low_confidence_lower_body": 4})
        self.assertEqual(pose.pose_bbox, [2.4, 156.8, 100.0, 342.1])
        self.assertEqual(estimator.last_debug["filtered_keypoints_count"], 12)
        self.assertEqual(estimator.last_debug["dropped_keypoints_count"], 5)
        self.assertEqual(estimator.last_debug["dropped_reasons"], {"edge_point": 1, "low_confidence_lower_body": 4})
        self.assertEqual(len(estimator.last_debug["raw_keypoints"]), 17)
        self.assertEqual(len(estimator.last_debug["pose_bounds_input_points"]), 12)


if __name__ == "__main__":
    unittest.main()
