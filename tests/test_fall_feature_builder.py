from __future__ import annotations

import time
import unittest

from app.detection.realtime_result_store import ObjectSnapshot
from app.fall.feature_builder import FallFeatureBuilder, FallFeatureContext
from app.schemas.vision_result import DetectedObject


class FallFeatureBuilderTest(unittest.TestCase):
    def test_pose_missing_still_outputs_motion_and_empty_hint(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 50.0, 120.0],
            track_id=3,
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=None),
        )

        features = enriched.features or {}
        self.assertEqual(features["motion"]["bbox_width"], 40.0)
        self.assertFalse(features["pose"]["pose_available"])
        self.assertFalse(features["fall_hint"]["strong_hint"])
        self.assertEqual(features["fall_hint"]["reason"], "no_fall_detection")

    def test_fall_hint_matches_track_by_iou(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 60.0, 120.0],
            track_id=7,
        )
        fall_detection = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=1,
            frame_width=100,
            frame_height=200,
            timestamp="2026-06-27T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(label="fall", confidence=0.8, bbox=[12.0, 22.0, 62.0, 122.0]),
            ],
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=fall_detection),
        )

        hint = (enriched.features or {})["fall_hint"]
        self.assertTrue(hint["available"])
        self.assertTrue(hint["strong_hint"])
        self.assertEqual(hint["strongest_label"], "fall")
        self.assertEqual(hint["matched_track_id"], 7)

    def test_rejected_pose_quality_is_not_available(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 50.0, 120.0],
            track_id=3,
            pose={
                "pose_quality_level": "pose_track_mismatch",
                "keypoints": [{"name": "nose", "confidence": 0.95}],
                "skeleton_confidence": 0.95,
                "debug": {"rejected_reason": "pose_track_mismatch"},
            },
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=None),
        )

        pose_features = (enriched.features or {})["pose"]
        self.assertFalse(pose_features["pose_available"])
        self.assertEqual(pose_features["pose_quality_level"], "pose_track_mismatch")

    def test_weak_lying_hint_is_marked_weak_not_strong(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 60.0, 120.0],
            track_id=8,
        )
        fall_detection = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=1,
            frame_width=100,
            frame_height=200,
            timestamp="2026-06-27T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(label="lying", confidence=0.7, bbox=[10.0, 20.0, 60.0, 120.0]),
            ],
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=fall_detection),
        )

        hint = (enriched.features or {})["fall_hint"]
        self.assertFalse(hint["strong_hint"])
        self.assertTrue(hint["weak_hint"])

    def test_falling_hint_is_marked_transition_not_strong(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 60.0, 120.0],
            track_id=9,
        )
        fall_detection = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=1,
            frame_width=100,
            frame_height=200,
            timestamp="2026-06-27T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(label="falling", confidence=0.75, bbox=[10.0, 20.0, 60.0, 120.0]),
            ],
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=fall_detection),
        )

        hint = (enriched.features or {})["fall_hint"]
        self.assertFalse(hint["strong_hint"])
        self.assertTrue(hint["transition_hint"])
        self.assertTrue(hint["weak_hint"])
        self.assertEqual(hint["strongest_label"], "falling")

    def test_fallen_hint_is_marked_strong(self) -> None:
        obj = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[10.0, 20.0, 60.0, 120.0],
            track_id=9,
        )
        fall_detection = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=1,
            frame_width=100,
            frame_height=200,
            timestamp="2026-06-27T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(label="fallen", confidence=0.75, bbox=[10.0, 20.0, 60.0, 120.0]),
            ],
        )

        enriched = FallFeatureBuilder().build_for_object(
            obj,
            context=FallFeatureContext(frame_width=100, frame_height=200, fall_detection=fall_detection),
        )

        hint = (enriched.features or {})["fall_hint"]
        self.assertTrue(hint["strong_hint"])
        self.assertFalse(hint.get("transition_hint", False))
        self.assertFalse(hint["weak_hint"])
        self.assertEqual(hint["strongest_label"], "fallen")


if __name__ == "__main__":
    unittest.main()
