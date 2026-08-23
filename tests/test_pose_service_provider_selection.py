from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from app.pose.branch4_legacy_pose_estimator import Branch4LegacyPoseEstimator
from app.pose.rtmpose_onnx_estimator import RTMPoseOnnxEstimator
from app.pose.yolo11_legacy_pose_estimator import Yolo11LegacyPoseEstimator
from app.pose.yolo_pose_estimator import YoloPoseEstimator
from app.schemas.vision_result import DetectedObject
from app.services.pose_service import PoseService


class PoseServiceProviderSelectionTest(unittest.TestCase):
    def test_selects_yolo_provider(self) -> None:
        service = PoseService.__new__(PoseService)
        service.settings = SimpleNamespace(
            pose_provider="yolo",
            rtmpose_onnx_model_path="models/rtmpose/rtmpose-x-body7-384x288.onnx",
            rtmpose_onnx_input_width=288,
            rtmpose_onnx_input_height=384,
        )
        service._estimator = None
        with patch.object(YoloPoseEstimator, "__init__", return_value=None):
            estimator = service._get_estimator()
        self.assertIsInstance(estimator, YoloPoseEstimator)

    def test_selects_rtmpose_provider(self) -> None:
        service = PoseService.__new__(PoseService)
        service.settings = SimpleNamespace(
            pose_provider="rtmpose",
            rtmpose_onnx_model_path="models/rtmpose/rtmpose-x-body7-384x288.onnx",
            rtmpose_onnx_input_width=288,
            rtmpose_onnx_input_height=384,
        )
        service._estimator = None
        with patch.object(RTMPoseOnnxEstimator, "__init__", return_value=None):
            estimator = service._get_estimator()
        self.assertIsInstance(estimator, RTMPoseOnnxEstimator)

    def test_selects_yolo11_legacy_provider(self) -> None:
        service = PoseService.__new__(PoseService)
        service.settings = SimpleNamespace(
            pose_provider="yolo11_legacy",
            yolo11_pose_model_path="D:/Program/health(5-12)/pose_detection_model_bundle/yolo11n-pose.pt",
        )
        service._estimator = None
        with patch.object(Yolo11LegacyPoseEstimator, "__init__", return_value=None):
            estimator = service._get_estimator()
        self.assertIsInstance(estimator, Yolo11LegacyPoseEstimator)

    def test_selects_branch4_legacy_provider(self) -> None:
        service = PoseService.__new__(PoseService)
        service.settings = SimpleNamespace(
            pose_provider="branch4_legacy",
            yolo11_pose_model_path="D:/Program/health(5-12)/pose_detection_model_bundle/yolo11n-pose.pt",
        )
        service._estimator = None
        with patch.object(Branch4LegacyPoseEstimator, "__init__", return_value=None):
            estimator = service._get_estimator()
        self.assertIsInstance(estimator, Branch4LegacyPoseEstimator)

    def test_branch4_targets_only_selected_target(self) -> None:
        service = PoseService.__new__(PoseService)
        service.settings = SimpleNamespace(pose_provider="branch4_legacy")
        objects = [
            DetectedObject(label="person", confidence=0.9, bbox=[0, 0, 120, 220], track_id=1, is_target=False),
            DetectedObject(label="person", confidence=0.95, bbox=[10, 20, 180, 320], track_id=2, is_target=True),
        ]

        selected = service._select_pose_targets(objects)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].track_id, 2)


if __name__ == "__main__":
    unittest.main()
