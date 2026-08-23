from __future__ import annotations

import time
import unittest
from dataclasses import replace

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.fall.unified_decision import UnifiedFallDecisionEngine
from app.schemas.vision_result import DetectedObject
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.result_publisher_service import ResultPublisherService


class _ResultChannelSpy:
    def publish(self, result) -> None:
        del result


def _settings(*, primary: bool = False, shadow: bool = True) -> Settings:
    return replace(
        Settings(),
        unified_decision_enabled=True,
        unified_decision_shadow=shadow,
        unified_decision_primary_enabled=primary,
        enable_pose=False,
        pose_provider="disabled_placeholder",
        enable_temporal=False,
        field_fall_candidate_enabled=False,
    )


def _person(**updates) -> DetectedObject:
    payload = {
        "label": "person",
        "confidence": 0.92,
        "bbox": [100.0, 200.0, 340.0, 340.0],
        "track_id": 7,
        "features": {
            "motion": {
                "tracking_stable": True,
                "delta_y": 80.0,
                "velocity_y": 300.0,
                "speed": 0.0,
                "aspect_ratio": 1.5,
                "bbox_center_y_norm": 0.72,
            },
            "pose": {
                "pose_available": True,
                "low_posture": True,
                "torso_angle": 18.0,
            },
            "fall_hint": {
                "available": True,
                "strong_hint": True,
                "weak_hint": False,
                "strongest_label": "fall",
                "confidence": 0.9,
            },
        },
        "temporal": {
            "fall_probability": 0.8,
            "window_size": 18,
            "stillness": True,
            "low_posture": True,
            "v6_scores": {
                "fall": {
                    "floor_contact_score": 0.7,
                },
                "adl": {
                    "adl_suppression_score": 0.0,
                },
            },
        },
        "fusion_debug": {
            "candidate_frames": 3,
            "candidate_duration_ms": 1100.0,
            "evidence_freshness": {
                "detection": "fresh",
                "tracking": "fresh",
                "fall_hint": "fresh",
                "pose": "fresh",
            },
        },
        "alarm_preview": {
            "confirmed": False,
            "risk_level": "low",
            "fall_probability": 0.0,
        },
    }
    payload.update(updates)
    return DetectedObject(**payload)


class UnifiedFallDecisionEngineTest(unittest.TestCase):
    def test_score_breakdown_matches_weighted_formula(self) -> None:
        engine = UnifiedFallDecisionEngine(_settings())

        payload = engine.evaluate("camera_01", _person()).model_payload()

        breakdown = payload["confidence_breakdown"]
        expected = (
            0.20 * 0.9
            + 0.18 * 0.8
            + 0.16 * 1.0
            + 0.14 * 1.0
            + 0.12 * 1.0
            + 0.10 * 1.0
            + 0.06 * 0.7
            + 0.04 * 1.0
        )
        self.assertAlmostEqual(breakdown["final_fall_score"], expected, places=4)
        self.assertEqual(payload["decision"]["status"], "fallen_confirmed")
        self.assertTrue(payload["decision"]["shadow"])
        self.assertEqual(payload["decision"]["decision_source"], "unified_fall_score_v1")

    def test_single_visual_hint_is_not_shadow_confirmed(self) -> None:
        engine = UnifiedFallDecisionEngine(_settings())
        item = _person(
            features={
                "motion": {"tracking_stable": True, "speed": 45.0, "aspect_ratio": 0.45},
                "pose": {"pose_available": False, "low_posture": False},
                "fall_hint": {"strong_hint": True, "strongest_label": "fall", "confidence": 0.95},
            },
            temporal={},
            fusion_debug={"candidate_frames": 0, "candidate_duration_ms": 0.0},
        )

        decision = engine.evaluate("camera_01", item).decision

        self.assertNotEqual(decision["status"], "fallen_confirmed")
        self.assertNotEqual(decision["status"], "alarm_preview")
        self.assertFalse(decision["required_evidence_passed"])

    def test_adl_suppression_blocks_shadow_confirmed(self) -> None:
        engine = UnifiedFallDecisionEngine(_settings())
        item = _person(
            temporal={
                "fall_probability": 0.8,
                "stillness": True,
                "low_posture": True,
                "v6_scores": {
                    "fall": {"floor_contact_score": 0.7},
                    "adl": {"adl_suppression_score": 0.9},
                },
            }
        )

        decision = engine.evaluate("camera_01", item).decision

        self.assertEqual(decision["status"], "suppressed")
        self.assertFalse(decision["adl_suppression_passed"])

    def test_primary_write_back_confirms_and_reporter_can_detect(self) -> None:
        engine = UnifiedFallDecisionEngine(_settings(primary=True))

        result = engine.enrich("camera_01", [_person()])[0]

        self.assertEqual(result.fall_decision["fall_state"], "fallen_confirmed")
        self.assertEqual(result.fall_decision["source"], "unified_fall_score_v1")
        self.assertTrue(result.alarm_preview["confirmed"])
        self.assertEqual(result.alarm_preview["confirm_source"], "unified_fall_score_v1")
        self.assertIn("unified_primary_decision", result.fusion_debug)
        self.assertTrue(FallEventReporterService._is_confirmed_fall(result))

    def test_primary_core_stale_blocks_confirmed_write_back(self) -> None:
        engine = UnifiedFallDecisionEngine(_settings(primary=True))
        item = _person(
            fusion_debug={
                "candidate_frames": 3,
                "candidate_duration_ms": 1100.0,
                "confirm_blocked_by": ["tracking_stale"],
                "evidence_freshness": {
                    "detection": "fresh",
                    "tracking": "stale",
                    "fall_hint": "fresh",
                    "pose": "fresh",
                },
            }
        )

        result = engine.enrich("camera_01", [item])[0]

        self.assertEqual(result.fall_decision["fall_state"], "fallen_candidate")
        self.assertFalse(result.alarm_preview["confirmed"])
        self.assertEqual(result.fall_decision["rejected_reason"], "core_evidence_stale")
        self.assertFalse(FallEventReporterService._is_confirmed_fall(result))

    def test_primary_mode_requires_unified_decision_enabled(self) -> None:
        with self.assertRaises(ValueError):
            replace(
                Settings(),
                unified_decision_enabled=False,
                unified_decision_primary_enabled=True,
            )

    def test_shadow_payload_does_not_change_alarm_preview_in_publisher(self) -> None:
        settings = _settings()
        realtime_store = RealtimeResultStore()
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=realtime_store,
            result_channels=_ResultChannelSpy(),
        )
        now = time.monotonic()
        person = _person(
            alarm_preview={"confirmed": False, "risk_level": "low", "fall_probability": 0.0},
            fall_decision={"fall_state": "normal", "fall_probability": 0.0},
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-08T00:00:00Z",
            monotonic_at=now,
            frame=None,  # type: ignore[arg-type]
            objects=[person],
            detector={"name": "person"},
        )
        tracking = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-08T00:00:00Z",
            monotonic_at=now,
            objects=[person],
        )
        realtime_store.update_detection(detection)
        realtime_store.update_tracking(tracking)

        result = publisher._build_result("camera_01")  # type: ignore[attr-defined]

        self.assertIsNotNone(result)
        published = result.objects[0]
        self.assertIn("unified_shadow_decision", published.fusion_debug)
        self.assertFalse(published.alarm_preview["confirmed"])
        self.assertEqual(published.fall_decision["fall_state"], "normal")
        self.assertTrue(result.detector["unified_decision_shadow_enabled"])

    def test_publisher_primary_mode_writes_official_fields(self) -> None:
        settings = _settings(primary=True)
        realtime_store = RealtimeResultStore()
        publisher = ResultPublisherService(
            settings=settings,
            realtime_store=realtime_store,
            result_channels=_ResultChannelSpy(),
        )
        now = time.monotonic()
        person = _person(
            alarm_preview={"confirmed": False, "risk_level": "low", "fall_probability": 0.0},
            fall_decision={"fall_state": "normal", "fall_probability": 0.0},
        )
        snapshot = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-08T00:00:00Z",
            monotonic_at=now,
            objects=[person],
        )
        realtime_store.update_detection(
            DetectionSnapshot(
                camera_id="camera_01",
                frame_seq=10,
                frame_width=640,
                frame_height=360,
                timestamp="2026-07-08T00:00:00Z",
                monotonic_at=now,
                frame=None,  # type: ignore[arg-type]
                objects=[person],
                detector={"name": "person"},
            )
        )
        realtime_store.update_tracking(snapshot)
        realtime_store.update_fall_detection(
            DetectionSnapshot(
                camera_id="camera_01",
                frame_seq=10,
                frame_width=640,
                frame_height=360,
                timestamp="2026-07-08T00:00:00Z",
                monotonic_at=now,
                frame=None,  # type: ignore[arg-type]
                objects=[
                    DetectedObject(
                        label="fall",
                        confidence=0.9,
                        bbox=[100.0, 200.0, 340.0, 340.0],
                    )
                ],
                detector={"name": "fall"},
            )
        )

        result = publisher._build_result("camera_01")  # type: ignore[attr-defined]

        self.assertIsNotNone(result)
        published = result.objects[0]
        self.assertEqual(published.fall_decision["source"], "unified_fall_score_v1")
        self.assertTrue(published.alarm_preview["confirmed"])
        self.assertTrue(result.detector["unified_decision_primary_enabled"])


if __name__ == "__main__":
    unittest.main()
