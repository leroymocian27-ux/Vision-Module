from __future__ import annotations

import unittest

from app.schemas.vision_result import DetectedObject
from app.temporal.target_feature_extractor import TargetFeatureExtractor


class TargetFeatureExtractorPoseQualityTest(unittest.TestCase):
    def test_valid_pose_quality_flows_into_target_feature(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[100.0, 100.0, 200.0, 300.0],
            track_id=1,
            pose={
                "pose_quality_level": "high_confidence",
                "skeleton_confidence": 0.88,
                "keypoints": [
                    {"name": "left_shoulder", "x": 120.0, "y": 140.0, "confidence": 0.9},
                    {"name": "right_shoulder", "x": 180.0, "y": 140.0, "confidence": 0.9},
                    {"name": "left_hip", "x": 125.0, "y": 230.0, "confidence": 0.9},
                    {"name": "right_hip", "x": 175.0, "y": 230.0, "confidence": 0.9},
                    {"name": "nose", "x": 150.0, "y": 115.0, "confidence": 0.9},
                ],
            },
        )

        feature = TargetFeatureExtractor().extract("camera_01", obj, timestamp=1.0)

        self.assertTrue(feature.pose_available)
        self.assertEqual(feature.pose_quality_level, "high_confidence")
        self.assertIsNone(feature.pose_rejected_reason)
        self.assertGreater(feature.pose_confidence, 0.0)
        self.assertIsNotNone(feature.torso_angle)

    def test_rejected_pose_is_recorded_but_not_available(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[100.0, 100.0, 200.0, 300.0],
            track_id=1,
            pose={
                "pose_quality_level": "pose_track_mismatch",
                "skeleton_confidence": 0.9,
                "keypoints": [{"name": "nose", "x": 150.0, "y": 115.0, "confidence": 0.9}],
                "debug": {"rejected_reason": "pose_track_mismatch"},
            },
        )

        feature = TargetFeatureExtractor().extract("camera_01", obj, timestamp=1.0)

        self.assertFalse(feature.pose_available)
        self.assertEqual(feature.pose_quality_level, "pose_track_mismatch")
        self.assertEqual(feature.pose_rejected_reason, "pose_track_mismatch")
        self.assertEqual(feature.pose_confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
