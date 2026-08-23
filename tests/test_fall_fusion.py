from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.fall.fusion import FallFusionService
from app.schemas.vision_result import DetectedObject


def _person(
    *,
    track_id: int | None = 1,
    strong_hint: bool = False,
    transition_hint: bool = False,
    weak_hint: bool = False,
    low_posture: bool = False,
    rapid_descent: bool = False,
    stillness: bool = True,
    probability: float = 0.0,
    behavior_state: str | None = None,
    temporal_confirmed: bool = False,
    v6_low_floor_contact: bool = False,
    field_confirmed: bool = False,
) -> DetectedObject:
    fall_decision = None
    alarm_preview = None
    if temporal_confirmed:
        fall_decision = {
            "fall_state": "fallen_confirmed",
            "risk_level": "critical",
            "fall_probability": probability,
            "fall_latched": True,
            "motion_path": "fast_fall_path",
        }
        alarm_preview = {"confirmed": True, "risk_level": "critical", "fall_probability": probability}
    elif v6_low_floor_contact:
        fall_decision = {
            "fall_state": "fallen_confirmed" if field_confirmed else "normal",
            "risk_level": "low",
            "fall_probability": probability,
            "fall_evidence_score": 0.42,
            "adl_suppression_score": 0.22,
            "motion_path": "normal",
            "source": "field_fall_candidate_fusion" if field_confirmed else "temporal_state_machine",
        }
        if field_confirmed:
            alarm_preview = {"confirmed": True, "risk_level": "critical", "fall_probability": probability}
    return DetectedObject(
        label="person",
        confidence=0.9,
        bbox=[100.0, 200.0, 260.0, 340.0],
        track_id=track_id,
        behavior={"behavior_state": behavior_state} if behavior_state else None,
        temporal={
            "fall_probability": probability,
            "low_posture": low_posture,
            "stillness": stillness,
            "v6_scores": {
                "fall": {
                    "floor_contact_score": 0.18 if v6_low_floor_contact else 0.55,
                    "post_fall_stillness_score": 0.70 if v6_low_floor_contact else 0.30,
                }
            },
            "features": {
                "delta_y": 55.0 if rapid_descent else 0.0,
                "velocity_y": 260.0 if rapid_descent else 0.0,
                "speed": 12.0 if stillness else 90.0,
                "pose_available": low_posture,
                "aspect_ratio": 1.1 if low_posture else 0.45,
            },
        },
        fall_decision=fall_decision,
        alarm_preview=alarm_preview,
        features={
            "motion": {
                "tracking_stable": track_id is not None,
                "delta_y": 55.0 if rapid_descent else 0.0,
                "velocity_y": 260.0 if rapid_descent else 0.0,
                "speed": 12.0 if stillness else 90.0,
            },
            "pose": {
                "pose_available": low_posture,
                "low_posture": low_posture,
            },
            "fall_hint": {
                "strong_hint": strong_hint,
                "transition_hint": transition_hint,
                "weak_hint": weak_hint or transition_hint,
                "strongest_label": "fall" if strong_hint else ("falling" if transition_hint else ("lying" if weak_hint else None)),
                "confidence": 0.82 if strong_hint else (0.76 if transition_hint else (0.64 if weak_hint else 0.0)),
            },
        },
    )


class FallFusionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = replace(
            Settings(),
            falling_prob_threshold=0.65,
            fall_confirm_frames=1,
            fall_still_ms=0,
            fall_v6_decision_enabled=True,
        )

    def test_single_fall_hint_does_not_confirm(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(strong_hint=True, low_posture=False, rapid_descent=False, probability=0.0)],
        )[0]

        self.assertNotEqual((result.fall_decision or {}).get("fall_state"), "fallen_confirmed")
        self.assertFalse((result.alarm_preview or {}).get("confirmed"))

    def test_weak_lying_without_descent_is_suppressed(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(weak_hint=True, low_posture=True, rapid_descent=False, probability=0.0)],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertEqual((result.fall_decision or {}).get("suppressed_reason"), "weak_lying_hint_without_descent")

    def test_falling_transition_without_low_posture_does_not_confirm(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(transition_hint=True, low_posture=False, rapid_descent=True, stillness=False, probability=0.2)],
        )[0]

        self.assertNotEqual((result.fall_decision or {}).get("fall_state"), "fallen_confirmed")
        self.assertFalse((result.alarm_preview or {}).get("confirmed"))
        self.assertIsNone(result.fall_decision)
        self.assertFalse((result.fusion_debug or {}).get("candidate_evidence"))

    def test_rapid_descent_low_posture_and_strong_hint_can_confirm(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(strong_hint=True, low_posture=True, rapid_descent=True, probability=0.2)],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "fallen_confirmed")
        self.assertTrue((result.alarm_preview or {}).get("confirmed"))
        self.assertIn("fall_hint", (result.fall_decision or {}).get("evidence_sources"))

    def test_track_unstable_blocks_confirmed(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(track_id=None, strong_hint=True, low_posture=True, rapid_descent=True, probability=0.9)],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertEqual((result.fall_decision or {}).get("suppressed_reason"), "track_unstable")

    def test_adl_like_posture_is_suppressed_without_descent(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(low_posture=True, rapid_descent=False, probability=0.9, behavior_state="sitting")],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertEqual((result.fall_decision or {}).get("suppressed_reason"), "adl_like_posture_suppressed")

    def test_adl_like_posture_is_suppressed_even_with_transition_motion(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [
                _person(
                    transition_hint=True,
                    low_posture=True,
                    rapid_descent=True,
                    stillness=False,
                    probability=0.7,
                    behavior_state="sitting",
                )
            ],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertEqual((result.fall_decision or {}).get("suppressed_reason"), "adl_like_posture_suppressed")

    def test_temporal_confirmed_passthrough_is_not_downgraded(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [_person(low_posture=True, rapid_descent=True, probability=0.88, temporal_confirmed=True)],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "fallen_confirmed")
        self.assertTrue((result.alarm_preview or {}).get("confirmed"))
        self.assertEqual((result.fall_decision or {}).get("confirm_source"), "temporal_state_machine")

    def test_v6_low_floor_contact_blocks_fusion_upgrade(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [
                _person(
                    low_posture=True,
                    rapid_descent=True,
                    stillness=True,
                    probability=0.74,
                    v6_low_floor_contact=True,
                )
            ],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertFalse((result.alarm_preview or {}).get("confirmed"))
        self.assertEqual(
            (result.fall_decision or {}).get("suppressed_reason"),
            "v6_low_fall_evidence_low_floor_contact",
        )

    def test_v6_low_floor_contact_blocks_non_temporal_existing_confirmed(self) -> None:
        service = FallFusionService(self.settings)
        result = service.enrich(
            "camera_01",
            [
                _person(
                    low_posture=True,
                    rapid_descent=True,
                    stillness=True,
                    probability=0.74,
                    v6_low_floor_contact=True,
                    field_confirmed=True,
                )
            ],
        )[0]

        self.assertEqual((result.fall_decision or {}).get("fall_state"), "suppressed")
        self.assertFalse((result.alarm_preview or {}).get("confirmed"))
        self.assertEqual(
            (result.fall_decision or {}).get("suppressed_reason"),
            "v6_low_fall_evidence_low_floor_contact",
        )


if __name__ == "__main__":
    unittest.main()
