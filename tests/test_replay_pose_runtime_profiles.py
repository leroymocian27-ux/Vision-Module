from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.replay_pose_runtime_profiles import active_pose_model_path, parse_profiles, recommend_profile, runtime_gate


class ReplayPoseRuntimeProfilesTest(unittest.TestCase):
    def test_parse_profiles_supports_defaults_and_custom_overrides(self) -> None:
        profiles = parse_profiles("A;wide:pose_result_ttl_ms=1000,pose_worker_fps=3.5,pose_skip_when_inference_busy=false")

        self.assertEqual(profiles[0][0], "A")
        self.assertEqual(profiles[0][1]["pose_result_ttl_ms"], 500)
        self.assertEqual(profiles[1][0], "wide")
        self.assertEqual(profiles[1][1]["pose_result_ttl_ms"], 1000)
        self.assertEqual(profiles[1][1]["pose_worker_fps"], 3.5)
        self.assertFalse(profiles[1][1]["pose_skip_when_inference_busy"])

    def test_parse_profiles_splits_comma_separated_default_names(self) -> None:
        profiles = parse_profiles("A,B,C")

        self.assertEqual([name for name, _ in profiles], ["A", "B", "C"])
        self.assertEqual(profiles[2][1]["pose_result_ttl_ms"], 1000)

    def test_runtime_gate_flags_stale_desync_and_low_publish_ratio(self) -> None:
        gate = runtime_gate(
            pose_valid_rate=0.9,
            published_pose_available_ratio=0.2,
            skip_reasons={"pose_frame_stale": 2, "frame_tracking_desync": 1},
            busy_skip_count=0,
        )

        self.assertFalse(gate["passed"])
        self.assertIn("published_pose_available_ratio_below_0.60", gate["blockers"])
        self.assertIn("pose_frame_stale", gate["blockers"])
        self.assertIn("frame_tracking_desync", gate["blockers"])

    def test_runtime_gate_blocks_detection_lag_but_not_source_eof(self) -> None:
        detection_lag = runtime_gate(
            pose_valid_rate=0.9,
            published_pose_available_ratio=0.8,
            skip_reasons={"pose_frame_stale_detection_lag": 1},
            busy_skip_count=0,
        )
        source_eof = runtime_gate(
            pose_valid_rate=0.9,
            published_pose_available_ratio=0.8,
            skip_reasons={"pose_frame_stale_source_eof": 1},
            busy_skip_count=0,
        )

        self.assertIn("pose_frame_stale_detection_lag", detection_lag["blockers"])
        self.assertFalse(detection_lag["passed"])
        self.assertEqual(source_eof["blockers"], [])
        self.assertTrue(source_eof["passed"])

    def test_recommend_profile_prefers_passed_profile_with_better_publish_ratio(self) -> None:
        recommendation = recommend_profile(
            [
                {
                    "profile_name": "A",
                    "pose_valid_rate": 1.0,
                    "published_pose_available_ratio": 0.5,
                    "avg_frame_process_ms": 100,
                    "gate": {"passed": False, "recommendation": "raise ttl"},
                },
                {
                    "profile_name": "B",
                    "pose_valid_rate": 0.9,
                    "published_pose_available_ratio": 0.8,
                    "avg_frame_process_ms": 140,
                    "gate": {"passed": True, "recommendation": "ok"},
                },
            ]
        )

        self.assertEqual(recommendation["selected_profile"], "B")
        self.assertTrue(recommendation["passed"])

    def test_active_pose_model_path_follows_provider(self) -> None:
        settings = SimpleNamespace(
            yolo11_pose_model_path="yolo11n-pose.pt",
            yolo_pose_model_path="yolov8n-pose.pt",
            rtmpose_onnx_model_path="rtmpose.onnx",
            rtmpose_checkpoint_path="rtmpose.pth",
        )

        self.assertEqual(active_pose_model_path(settings, "yolo11_legacy"), "yolo11n-pose.pt")
        self.assertEqual(active_pose_model_path(settings, "yolo"), "yolov8n-pose.pt")
        self.assertEqual(active_pose_model_path(settings, "rtmpose_onnx"), "rtmpose.onnx")
        self.assertEqual(active_pose_model_path(settings, "mmpose"), "rtmpose.pth")


if __name__ == "__main__":
    unittest.main()
