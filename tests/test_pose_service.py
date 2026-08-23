from __future__ import annotations

import unittest
from dataclasses import replace
from contextlib import contextmanager
from unittest.mock import patch

import numpy as np

from app.core.config import Settings
from app.pose.placeholders import pose_has_visible_keypoints
from app.pose.schemas import PoseKeypoint, PoseResult
from app.services.pose_service import PoseService
from app.schemas.vision_result import DetectedObject


class PoseServiceDisabledPlaceholderTest(unittest.TestCase):
    def test_disabled_mode_returns_placeholder_without_loading_estimator(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=False,
            pose_provider="disabled_placeholder",
        )
        service = PoseService(settings=settings)
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]

        with patch.object(service, "_get_estimator", side_effect=AssertionError("estimator should not load")):
            enriched = service.enrich(
                camera_id="camera_01",
                frame=np.zeros((16, 16, 3), dtype=np.uint8),
                objects=objects,
                frame_seq=12,
                tracking_frame_seq=12,
                frame_age_ms=22.3,
                frame_timestamp="2026-06-21T08:00:00Z",
            )

        self.assertEqual(len(enriched), 1)
        pose = enriched[0].pose
        self.assertIsInstance(pose, dict)
        self.assertEqual(pose["pose_provider"], "disabled_placeholder")
        self.assertEqual(pose["keypoints"], [])
        self.assertIsNone(pose["pose_bbox"])
        self.assertIsNone(pose["skeleton_confidence"])
        self.assertTrue(pose["debug"]["placeholder"])
        self.assertTrue(pose["debug"]["pose_disabled"])

    def test_status_reports_disabled_placeholder(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=False,
            pose_provider="mock",
        )
        service = PoseService(settings=settings)

        status = service.status("camera_01")

        self.assertFalse(status.pose_enabled)
        self.assertEqual(status.pose_provider, "disabled_placeholder")
        self.assertTrue(status.pose_pipeline_removed)
        self.assertEqual(status.placeholder_reason, "pose_pipeline_removed_pending_reconfiguration")


class _FakePoseEstimator:
    def __init__(self) -> None:
        self.last_debug = {
            "selected_track_id": 7,
            "skeleton_confidence": 0.88,
            "rejected_reason": None,
        }
        self.last_debug_by_track = {
            7: {
                "selected_track_id": 7,
                "skeleton_confidence": 0.88,
                "rejected_reason": None,
            }
        }

    def estimate(self, frame, objects):
        return {
            7: PoseResult(
                track_id=7,
                keypoints=[
                    PoseKeypoint(name="nose", x=12.0, y=20.0, confidence=0.9),
                    PoseKeypoint(name="left_shoulder", x=10.0, y=35.0, confidence=0.85),
                ],
                skeleton_confidence=0.88,
            )
        }


class PoseServiceDiagnosticsTest(unittest.TestCase):
    def test_status_accumulates_pose_runtime_diagnostics(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=30,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]

        service.record_worker_tick("camera_01")
        enriched = service.enrich(
            camera_id="camera_01",
            frame=np.zeros((16, 16, 3), dtype=np.uint8),
            objects=objects,
            frame_seq=12,
            tracking_frame_seq=12,
            frame_age_ms=22.3,
        )
        status = service.status("camera_01")

        self.assertIsNotNone(enriched[0].pose)
        self.assertEqual(status.worker_tick_count, 1)
        self.assertEqual(status.inference_attempt_count, 1)
        self.assertEqual(status.inference_success_count, 1)
        self.assertEqual(status.pose_target_object_count, 1)
        self.assertEqual(status.pose_attached_object_count, 1)
        self.assertEqual(status.pose_valid_rate, 1.0)
        self.assertEqual(status.inference_success_rate, 1.0)
        self.assertEqual(status.pose_quality_level, "valid")
        self.assertEqual(enriched[0].pose["pose_quality_level"], "valid")

    def test_status_reports_configured_pose_model_path_without_recent_pose_context(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="yolo11_legacy",
            yolo11_pose_model_path="models/runtime_pose.pt",
        )
        service = PoseService(settings=settings)

        status = service.status("camera_01")

        self.assertEqual(status.pose_provider, "yolo11_legacy")
        self.assertEqual(status.pose_model_path, "models/runtime_pose.pt")

    def test_pose_fps_throttle_uses_inference_start_time_not_completion_time(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=3.0,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]

        with patch(
            "app.services.pose_service.time.monotonic",
            side_effect=[
                100.0,
                100.0,
                100.0,
                100.3,
                100.3,
                100.34,
                100.34,
                100.34,
                100.64,
                100.64,
            ],
        ):
            service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)
            service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)

        status = service.status("camera_01")

        self.assertEqual(status.inference_attempt_count, 2)
        self.assertNotIn("pose_fps_throttle", status.skip_reasons)

    def test_busy_skip_does_not_refresh_pose_fps_throttle_window(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=3.0,
            pose_skip_when_inference_busy=True,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]

        @contextmanager
        def busy_lock(*, blocking=True, owner=None, timeout=None):
            yield False

        with patch("app.services.pose_service.ultralytics_inference_lock", busy_lock):
            service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)

        service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)
        status = service.status("camera_01")

        self.assertEqual(status.skipped_due_to_busy, 1)
        self.assertEqual(status.skip_reasons["busy"], 1)
        self.assertEqual(status.inference_attempt_count, 1)
        self.assertNotIn("pose_fps_throttle", status.skip_reasons)

    def test_busy_skip_records_current_inference_lock_owner(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=30.0,
            pose_skip_when_inference_busy=True,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]

        with patch("app.services.pose_service.current_ultralytics_inference_owner", return_value="person_detector"):
            @contextmanager
            def busy_lock(*, blocking=True, owner=None, timeout=None):
                yield False

            with patch("app.services.pose_service.ultralytics_inference_lock", busy_lock):
                service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)

        status = service.status("camera_01")

        self.assertEqual(status.skip_reasons["busy"], 1)
        self.assertEqual(status.skip_reasons["busy_by_person_detector"], 1)

    def test_busy_skip_uses_bounded_lock_wait_when_configured(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=30.0,
            pose_skip_when_inference_busy=True,
            pose_inference_lock_wait_ms=75,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]
        calls = []

        @contextmanager
        def busy_lock(*, blocking=True, owner=None, timeout=None):
            calls.append({"blocking": blocking, "owner": owner, "timeout": timeout})
            yield False

        with patch("app.services.pose_service.ultralytics_inference_lock", busy_lock):
            service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)

        self.assertEqual(calls, [{"blocking": True, "owner": "pose:mock", "timeout": 0.075}])

    def test_busy_skip_uses_nonblocking_lock_when_wait_disabled(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=30.0,
            pose_skip_when_inference_busy=True,
            pose_inference_lock_wait_ms=0,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()
        objects = [
            DetectedObject(
                label="person",
                confidence=0.93,
                bbox=[100.0, 120.0, 280.0, 420.0],
                track_id=7,
                is_target=True,
            )
        ]
        calls = []

        @contextmanager
        def busy_lock(*, blocking=True, owner=None, timeout=None):
            calls.append({"blocking": blocking, "owner": owner, "timeout": timeout})
            yield False

        with patch("app.services.pose_service.ultralytics_inference_lock", busy_lock):
            service.enrich("camera_01", np.zeros((16, 16, 3), dtype=np.uint8), objects)

        self.assertEqual(calls, [{"blocking": False, "owner": "pose:mock", "timeout": None}])

    def test_status_records_no_target_skip_reason(self) -> None:
        settings = replace(
            Settings(),
            enable_pose=True,
            pose_provider="mock",
            pose_fps=30,
        )
        service = PoseService(settings=settings)
        service._estimator = _FakePoseEstimator()

        service.enrich(
            camera_id="camera_01",
            frame=np.zeros((16, 16, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="chair",
                    confidence=0.93,
                    bbox=[100.0, 120.0, 280.0, 420.0],
                    track_id=None,
                    is_target=False,
                )
            ],
        )

        status = service.status("camera_01")

        self.assertEqual(status.inference_attempt_count, 0)
        self.assertEqual(status.skip_reasons["no_pose_targets"], 1)

    def test_classifies_pose_quality_levels(self) -> None:
        high_confidence = {
            "keypoints": [{"name": f"kp_{index}", "confidence": 0.8} for index in range(8)],
            "skeleton_confidence": 0.75,
        }
        low_quality = {
            "keypoints": [{"name": "nose", "confidence": 0.0}],
            "skeleton_confidence": 0.1,
        }
        mismatch = {
            "keypoints": [],
            "skeleton_confidence": 0.8,
            "debug": {"rejected_reason": "pose_track_mismatch"},
        }

        self.assertEqual(PoseService._classify_pose_payload(high_confidence), "high_confidence")
        self.assertEqual(PoseService._classify_pose_payload(low_quality), "low_quality")
        self.assertEqual(PoseService._classify_pose_payload(mismatch), "pose_track_mismatch")

    def test_pose_visible_helper_rejects_low_quality_and_rejected_payloads(self) -> None:
        self.assertFalse(
            pose_has_visible_keypoints(
                {
                    "pose_quality_level": "low_quality",
                    "keypoints": [{"name": "nose", "confidence": 0.95}],
                }
            )
        )
        self.assertFalse(
            pose_has_visible_keypoints(
                {
                    "keypoints": [{"name": "nose", "confidence": 0.95}],
                    "debug": {"rejected_reason": "keypoints_outside_bbox"},
                }
            )
        )
        self.assertTrue(
            pose_has_visible_keypoints(
                {
                    "pose_quality_level": "valid",
                    "keypoints": [{"name": "nose", "confidence": 0.95}],
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
