from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import benchmark_pose_providers as benchmark_module
from scripts.benchmark_pose_providers import (
    ProviderVideoResult,
    _active_pose_model_path,
    _evaluate_video,
    _parse_providers,
    _pose_has_visible_keypoints,
    _summarize,
)


class BenchmarkPoseProvidersTest(unittest.TestCase):
    def test_parse_providers_deduplicates_and_preserves_order(self) -> None:
        providers = _parse_providers(" yolo11_legacy, yolo, yolo11_legacy, branch4_legacy ")

        self.assertEqual(providers, ["yolo11_legacy", "yolo", "branch4_legacy"])

    def test_active_pose_model_path_uses_provider_specific_setting(self) -> None:
        settings = SimpleNamespace(
            yolo11_pose_model_path="models/yolo11.pt",
            yolo_pose_model_path="models/yolo8.pt",
            rtmpose_onnx_model_path="models/rtmpose.onnx",
            rtmpose_checkpoint_path="models/rtmpose.pth",
        )

        self.assertEqual(_active_pose_model_path(settings, "yolo11_legacy"), "models/yolo11.pt")
        self.assertEqual(_active_pose_model_path(settings, "yolo"), "models/yolo8.pt")
        self.assertEqual(_active_pose_model_path(settings, "rtmpose_onnx"), "models/rtmpose.onnx")
        self.assertEqual(_active_pose_model_path(settings, "mmpose_finetuned"), "models/rtmpose.pth")

    def test_pose_has_visible_keypoints_rejects_empty_or_rejected_payload(self) -> None:
        self.assertFalse(_pose_has_visible_keypoints({"keypoints": []}))
        self.assertFalse(
            _pose_has_visible_keypoints(
                {
                    "keypoints": [{"name": "nose", "confidence": 0.9}],
                    "debug": {"rejected_reason": "pose_track_mismatch"},
                }
            )
        )
        self.assertTrue(
            _pose_has_visible_keypoints(
                {
                    "keypoints": [
                        {"name": "nose", "confidence": 0.1},
                        {"name": "left_shoulder", "confidence": 0.9},
                    ]
                }
            )
        )

    def test_summary_uses_attached_pose_rate_and_skip_reasons(self) -> None:
        summary = _summarize(
            [
                ProviderVideoResult(
                    provider="yolo11_legacy",
                    video_id="fall-01.mp4",
                    label="fall",
                    split="val",
                    sampled_frames=10,
                    pose_frames=6,
                    pose_object_frames=7,
                    inference_attempt_count=8,
                    inference_success_count=8,
                    pose_target_object_count=10,
                    pose_attached_object_count=6,
                    skip_reasons={"no_pose_attached": 2},
                    pose_quality_counts={"high_confidence": 4, "valid": 2, "low_quality": 1},
                ),
                ProviderVideoResult(
                    provider="yolo11_legacy",
                    video_id="adl-01.mp4",
                    label="non_fall",
                    split="val",
                    sampled_frames=5,
                    pose_frames=1,
                    pose_object_frames=2,
                    inference_attempt_count=4,
                    inference_success_count=4,
                    pose_target_object_count=5,
                    pose_attached_object_count=1,
                    skip_reasons={"no_pose_attached": 3},
                    pose_quality_counts={"valid": 1, "low_quality": 1},
                ),
            ]
        )

        provider = summary["yolo11_legacy"]
        self.assertEqual(provider["pose_frames"], 7)
        self.assertEqual(provider["pose_object_frames"], 9)
        self.assertEqual(provider["pose_target_object_count"], 15)
        self.assertEqual(provider["pose_attached_object_count"], 7)
        self.assertEqual(provider["pose_valid_rate"], 0.4667)
        self.assertEqual(provider["skip_reasons"]["no_pose_attached"], 5)
        self.assertEqual(provider["pose_quality_counts"]["high_confidence"], 4)
        self.assertEqual(provider["pose_quality_counts"]["valid"], 3)
        self.assertEqual(provider["pose_quality_counts"]["low_quality"], 2)

    def test_evaluate_video_max_frames_counts_sampled_frames_not_raw_index(self) -> None:
        class FakeCapture:
            def __init__(self, path: str) -> None:
                self.index = 0

            def isOpened(self) -> bool:
                return True

            def read(self):
                if self.index >= 8:
                    return False, None
                self.index += 1
                return True, SimpleNamespace()

            def release(self) -> None:
                pass

        class FakeDetector:
            def detect(self, frame):
                return [SimpleNamespace(pose=None, label="person", track_id=1)]

        class FakeTracker:
            def enrich(self, camera_id, objects, frame=None):
                return objects

        class FakePose:
            def enrich(self, camera_id, frame, objects, frame_seq=None, tracking_frame_seq=None):
                for obj in objects:
                    obj.pose = {
                        "pose_quality_level": "high_confidence",
                        "skeleton_confidence": 0.8,
                        "keypoints": [{"name": "nose", "confidence": 0.9}],
                    }
                return objects

            def status(self, camera_id):
                return SimpleNamespace(
                    inference_attempt_count=3,
                    inference_success_count=3,
                    pose_target_object_count=3,
                    pose_attached_object_count=3,
                    pose_valid_rate=1.0,
                    skip_reasons={},
                )

        with patch.object(benchmark_module.cv2, "VideoCapture", FakeCapture):
            result = _evaluate_video(
                detector=FakeDetector(),
                tracker=FakeTracker(),
                pose=FakePose(),
                provider="fake",
                row={"video_id": "ur_fall/fall-01.mp4", "binary_label": "fall", "split": "val"},
                frame_stride=2,
                max_frames=3,
            )

        self.assertEqual(result.sampled_frames, 3)
        self.assertEqual(result.pose_frames, 3)


if __name__ == "__main__":
    unittest.main()
