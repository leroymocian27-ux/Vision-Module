from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject
from app.services.temporal_service import TemporalService


class TemporalServiceTest(unittest.TestCase):
    def test_disabled_pose_runtime_produces_bbox_only_temporal_features(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            enable_pose=False,
            pose_provider="disabled_placeholder",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
            pose={
                "pose_provider": "disabled_placeholder",
                "keypoints": [],
                "debug": {"pose_disabled": True},
            },
        )

        enriched = service.enrich("camera_01", [obj])

        temporal = enriched[0].temporal or {}
        features = temporal.get("features") or {}
        self.assertFalse(features["pose_available"])
        self.assertEqual(features["pose_confidence"], 0.0)
        self.assertIsNone(features["torso_angle"])
        self.assertIsNone(features["head_height_ratio"])
        self.assertIsNone(features["hip_height_ratio"])

    def test_objects_empty_resets_temporal_state_after_threshold(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            temporal_no_object_reset_frames=3,
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 240.0, 340.0],
            track_id=1,
            is_target=True,
        )

        service.enrich("camera_01", [obj])
        self.assertEqual(service.status("camera_01").active_tracks, 1)

        service.enrich("camera_01", [])
        service.enrich("camera_01", [])
        service.enrich("camera_01", [])
        status = service.status("camera_01")

        self.assertEqual(status.active_tracks, 0)
        self.assertEqual(status.fall_state, "normal")
        self.assertEqual(status.no_object_reset_count, 1)
        self.assertEqual(status.last_reset_reason, "no_objects_reset_temporal")

    def test_v6_scoring_shadow_payload_does_not_take_over_decision(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            enable_pose=False,
            pose_provider="disabled_placeholder",
            temporal_model_provider="mock",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
            fall_v6_scoring_enabled=True,
            fall_v6_decision_enabled=False,
            fall_v6_debug_payload=True,
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
        )

        enriched = service.enrich("camera_01", [obj])

        temporal = enriched[0].temporal or {}
        decision = enriched[0].fall_decision or {}
        self.assertIn("fall_evidence_score", temporal)
        self.assertIn("adl_suppression_score", temporal)
        self.assertEqual(temporal["motion_path"], "legacy_shadow")
        self.assertEqual(decision["motion_path"], "legacy_shadow")
        self.assertEqual(decision["fall_state"], "normal")

    def test_sc_tan_shadow_payload_is_attached_without_taking_over_decision(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            enable_pose=False,
            pose_provider="disabled_placeholder",
            temporal_model_provider="mock",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
            fall_v6_scoring_enabled=True,
            fall_v6_decision_enabled=False,
            fall_v6_debug_payload=True,
            sc_tan_shadow_enabled=True,
            sc_tan_min_window=2,
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
            temporal={"scene_context": {"scene_type": "floor_risk_zone"}},
        )

        first = service.enrich("camera_01", [obj])[0]
        second = service.enrich("camera_01", [obj.model_copy(update={"bbox": [100.0, 185.0, 310.0, 345.0]})])[0]

        first_temporal = first.temporal or {}
        second_temporal = second.temporal or {}
        decision = second.fall_decision or {}
        alarm = second.alarm_preview or {}
        self.assertIn("sc_tan", first_temporal)
        self.assertFalse(first_temporal["sc_tan"]["window_ready"])
        self.assertTrue(second_temporal["sc_tan"]["window_ready"])
        self.assertIn("fall_risk", second_temporal["sc_tan"])
        self.assertIn("adl_risk", second_temporal["sc_tan"])
        self.assertIn("top_attention_frames", second_temporal["sc_tan"])
        self.assertIn("sc_tan_shadow", decision)
        self.assertIn("sc_tan_shadow", alarm)
        self.assertEqual(decision["source"], "temporal_state_machine")
        self.assertEqual(decision["fall_state"], "normal")
        self.assertTrue(service.status("camera_01").sc_tan_shadow_enabled)
        self.assertIsNone(service.status("camera_01").sc_tan_last_error)

    def test_sc_tan_shadow_can_be_disabled(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            temporal_model_provider="mock",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
            sc_tan_shadow_enabled=False,
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
        )

        enriched = service.enrich("camera_01", [obj])[0]

        self.assertNotIn("sc_tan", enriched.temporal or {})
        self.assertNotIn("sc_tan_shadow", enriched.fall_decision or {})
        self.assertFalse(service.status("camera_01").sc_tan_shadow_enabled)

    def test_random_forest_fusion_shadow_payload_is_attached_without_taking_over_decision(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            enable_pose=False,
            pose_provider="disabled_placeholder",
            temporal_model_provider="mock",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
            fall_v6_scoring_enabled=True,
            fall_v6_decision_enabled=False,
            fall_v6_debug_payload=True,
            rf_fusion_shadow_enabled=True,
            rf_fusion_min_window=2,
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
            temporal={"scene_context": {"scene_type": "floor_risk_zone"}},
        )

        first = service.enrich("camera_01", [obj])[0]
        second = service.enrich("camera_01", [obj.model_copy(update={"bbox": [100.0, 185.0, 310.0, 345.0]})])[0]

        first_temporal = first.temporal or {}
        second_temporal = second.temporal or {}
        decision = second.fall_decision or {}
        alarm = second.alarm_preview or {}
        self.assertIn("rf_fusion", first_temporal)
        self.assertFalse(first_temporal["rf_fusion"]["window_ready"])
        self.assertTrue(second_temporal["rf_fusion"]["window_ready"])
        self.assertIn("fall_risk", second_temporal["rf_fusion"])
        self.assertIn("adl_risk", second_temporal["rf_fusion"])
        self.assertIn("top_feature_votes", second_temporal["rf_fusion"])
        self.assertIn("rf_fusion_shadow", decision)
        self.assertIn("rf_fusion_shadow", alarm)
        self.assertEqual(decision["source"], "temporal_state_machine")
        self.assertEqual(decision["fall_state"], "normal")
        self.assertTrue(service.status("camera_01").rf_fusion_shadow_enabled)
        self.assertIsNone(service.status("camera_01").rf_fusion_last_error)

    def test_random_forest_fusion_shadow_can_be_disabled(self) -> None:
        settings = replace(
            Settings(),
            enable_temporal=True,
            temporal_model_provider="mock",
            temporal_track_mode="all_tracks",
            temporal_sequence_key_mode="identity",
            rf_fusion_shadow_enabled=False,
        )
        service = TemporalService(settings)
        obj = DetectedObject(
            label="person",
            confidence=0.95,
            bbox=[100.0, 100.0, 260.0, 340.0],
            track_id=1,
            is_target=True,
        )

        enriched = service.enrich("camera_01", [obj])[0]

        self.assertNotIn("rf_fusion", enriched.temporal or {})
        self.assertNotIn("rf_fusion_shadow", enriched.fall_decision or {})
        self.assertFalse(service.status("camera_01").rf_fusion_shadow_enabled)


if __name__ == "__main__":
    unittest.main()
