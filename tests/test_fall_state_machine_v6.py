from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.temporal.fall_state_machine import FallStateMachine
from app.temporal.scene_context import SceneContext
from app.temporal.schemas import (
    ADLSuppressionScores,
    FallEvidenceScores,
    SequencePrediction,
    TargetFeature,
    TemporalMotionSummary,
    TemporalV6Scores,
)


class FallStateMachineV6Test(unittest.TestCase):
    def test_fast_fall_path_confirms_when_v6_decision_enabled(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=1, fall_still_ms=0))
        feature = self._feature(delta_y=70.0, aspect_ratio=1.2, speed=4.0)
        prediction = SequencePrediction(fall_probability=0.9, window_size=32)
        scores = self._scores(
            fall_evidence=0.86,
            adl_suppression=0.12,
            vertical_drop=0.82,
            low_posture=0.9,
            stillness=0.8,
            floor_contact=0.8,
            low_posture_ms=2000,
        )

        decision = machine.update("track:camera_01:1", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")
        self.assertTrue(decision.fall_latched)

    def test_slow_fall_path_confirms_after_low_posture_hold(self) -> None:
        machine = FallStateMachine(self._settings())
        feature = self._feature(delta_y=12.0, aspect_ratio=1.15, speed=3.0)
        prediction = SequencePrediction(fall_probability=0.58, window_size=32)
        scores = self._scores(
            fall_evidence=0.66,
            adl_suppression=0.28,
            vertical_drop=0.25,
            low_posture=0.82,
            stillness=0.82,
            floor_contact=0.75,
            continuous_descent=0.72,
            low_posture_ms=6200,
        )

        decision = machine.update("track:camera_01:2", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "slow_fall_path")
        self.assertTrue(decision.fall_latched)

    def test_fast_fall_strong_evidence_confirms_despite_few_frames(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=80.0, aspect_ratio=1.25, speed=2.0)
        prediction = SequencePrediction(fall_probability=0.9, window_size=32)
        scores = self._scores(
            fall_evidence=0.88,
            adl_suppression=0.18,
            vertical_drop=0.85,
            low_posture=0.92,
            stillness=0.92,
            floor_contact=0.82,
            low_posture_ms=950,
        )

        decision = machine.update("track:camera_01:22", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_fast_fall_strong_evidence_can_confirm_after_short_hold(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=78.0, aspect_ratio=1.22, speed=3.0)
        prediction = SequencePrediction(fall_probability=0.88, window_size=32)
        scores = self._scores(
            fall_evidence=0.82,
            adl_suppression=0.20,
            vertical_drop=0.90,
            low_posture=0.94,
            stillness=0.66,
            floor_contact=0.48,
            low_posture_ms=650,
        )

        decision = machine.update("track:camera_01:23", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_fast_fall_grounded_evidence_can_confirm_with_low_stillness(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=78.0, aspect_ratio=1.22, speed=22.0)
        prediction = SequencePrediction(fall_probability=0.88, window_size=32)
        scores = self._scores(
            fall_evidence=0.82,
            adl_suppression=0.20,
            vertical_drop=0.90,
            low_posture=0.94,
            stillness=0.18,
            floor_contact=0.50,
            impact=0.65,
            low_posture_ms=650,
        )

        decision = machine.update("track:camera_01:24", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_context_allows_strong_fast_fall_with_low_floor_contact(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=82.0, aspect_ratio=1.24, speed=16.0)
        prediction = SequencePrediction(fall_probability=0.90, window_size=32)
        scores = self._scores(
            fall_evidence=0.86,
            adl_suppression=0.20,
            vertical_drop=0.96,
            low_posture=0.96,
            stillness=0.20,
            floor_contact=0.34,
            impact=0.78,
            low_posture_ms=650,
            floor_risk_score=1.0,
        )

        decision = machine.update("track:camera_01:25", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_short_window_can_confirm_when_adl_evidence_is_low(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=82.0, aspect_ratio=1.24, speed=16.0)
        prediction = SequencePrediction(fall_probability=0.88, window_size=32)
        scores = self._scores(
            fall_evidence=0.785,
            adl_suppression=0.31,
            vertical_drop=1.0,
            low_posture=1.0,
            stillness=0.30,
            floor_contact=0.41,
            impact=0.74,
            low_posture_ms=640,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:27", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_single_frame_impact_can_confirm_with_strict_context(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=90.0, aspect_ratio=1.28, speed=20.0)
        prediction = SequencePrediction(fall_probability=0.90, window_size=32)
        scores = self._scores(
            fall_evidence=0.805,
            adl_suppression=0.44,
            vertical_drop=1.0,
            low_posture=1.0,
            stillness=0.0,
            floor_contact=0.50,
            impact=0.65,
            low_posture_ms=0,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:28", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_single_frame_impact_waits_with_support_surface(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=90.0, aspect_ratio=1.28, speed=20.0)
        prediction = SequencePrediction(fall_probability=0.90, window_size=32)
        scores = self._scores(
            fall_evidence=0.805,
            adl_suppression=0.44,
            vertical_drop=1.0,
            low_posture=1.0,
            stillness=0.0,
            floor_contact=0.50,
            impact=0.65,
            low_posture_ms=0,
            floor_risk_score=1.0,
            support_surface=0.90,
        )

        decision = machine.update("track:camera_01:29", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_short_observation_grounded_can_confirm(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=72.0, aspect_ratio=1.26, speed=18.0)
        prediction = SequencePrediction(fall_probability=0.82, window_size=32)
        scores = self._scores(
            fall_evidence=0.71,
            adl_suppression=0.49,
            vertical_drop=0.69,
            low_posture=1.0,
            stillness=0.0,
            floor_contact=0.46,
            impact=0.55,
            low_posture_ms=0,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:33", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_short_observation_grounded_waits_when_adl_counterevidence_is_high(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=72.0, aspect_ratio=1.26, speed=18.0)
        prediction = SequencePrediction(fall_probability=0.82, window_size=32)
        scores = self._scores(
            fall_evidence=0.71,
            adl_suppression=0.50,
            vertical_drop=0.69,
            low_posture=1.0,
            stillness=0.0,
            floor_contact=0.46,
            impact=0.55,
            low_posture_ms=0,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:34", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_short_observation_grounded_waits_with_support_surface(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=72.0, aspect_ratio=1.26, speed=18.0)
        prediction = SequencePrediction(fall_probability=0.82, window_size=32)
        scores = self._scores(
            fall_evidence=0.71,
            adl_suppression=0.49,
            vertical_drop=0.69,
            low_posture=1.0,
            stillness=0.0,
            floor_contact=0.46,
            impact=0.55,
            low_posture_ms=0,
            floor_risk_score=1.0,
            support_surface=0.20,
        )

        decision = machine.update("track:camera_01:35", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_partial_grounded_drop_can_confirm(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=84.0, aspect_ratio=1.18, speed=17.0)
        prediction = SequencePrediction(fall_probability=0.78, window_size=32)
        scores = self._scores(
            fall_evidence=0.68,
            adl_suppression=0.22,
            vertical_drop=0.95,
            low_posture=0.60,
            stillness=0.0,
            floor_contact=0.39,
            impact=0.63,
            floor_risk_score=1.0,
            support_surface=0.12,
            recovery=0.02,
        )

        decision = machine.update("track:camera_01:36", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_partial_grounded_drop_waits_with_support_surface(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=84.0, aspect_ratio=1.18, speed=17.0)
        prediction = SequencePrediction(fall_probability=0.78, window_size=32)
        scores = self._scores(
            fall_evidence=0.68,
            adl_suppression=0.22,
            vertical_drop=0.95,
            low_posture=0.60,
            stillness=0.0,
            floor_contact=0.39,
            impact=0.63,
            floor_risk_score=1.0,
            support_surface=0.20,
            recovery=0.02,
        )

        decision = machine.update("track:camera_01:37", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_medium_grounded_hold_can_confirm(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=58.0, aspect_ratio=1.12, speed=12.0)
        prediction = SequencePrediction(fall_probability=0.62, window_size=32)
        scores = self._scores(
            fall_evidence=0.57,
            adl_suppression=0.27,
            vertical_drop=0.59,
            low_posture=0.50,
            stillness=0.15,
            floor_contact=0.42,
            impact=0.44,
            low_posture_ms=640,
            floor_risk_score=1.0,
            support_surface=0.19,
            recovery=0.07,
        )

        decision = machine.update("track:camera_01:38", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_medium_grounded_hold_waits_with_support_surface(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=58.0, aspect_ratio=1.12, speed=12.0)
        prediction = SequencePrediction(fall_probability=0.62, window_size=32)
        scores = self._scores(
            fall_evidence=0.57,
            adl_suppression=0.27,
            vertical_drop=0.59,
            low_posture=0.50,
            stillness=0.15,
            floor_contact=0.42,
            impact=0.44,
            low_posture_ms=640,
            floor_risk_score=1.0,
            support_surface=0.20,
            recovery=0.07,
        )

        decision = machine.update("track:camera_01:39", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "motion_observe")

    def test_floor_risk_vertical_impact_drop_can_confirm(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=92.0, aspect_ratio=1.02, speed=18.0)
        prediction = SequencePrediction(fall_probability=0.58, window_size=32)
        scores = self._scores(
            fall_evidence=0.50,
            adl_suppression=0.26,
            vertical_drop=1.0,
            low_posture=0.04,
            stillness=0.0,
            floor_contact=0.35,
            impact=0.59,
            floor_risk_score=1.0,
            support_surface=0.35,
            recovery=0.0,
        )

        decision = machine.update("track:camera_01:40", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")

    def test_floor_risk_vertical_impact_drop_waits_when_impact_is_weak(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=92.0, aspect_ratio=1.02, speed=18.0)
        prediction = SequencePrediction(fall_probability=0.58, window_size=32)
        scores = self._scores(
            fall_evidence=0.50,
            adl_suppression=0.26,
            vertical_drop=1.0,
            low_posture=0.04,
            stillness=0.0,
            floor_contact=0.35,
            impact=0.57,
            floor_risk_score=1.0,
            support_surface=0.35,
            recovery=0.0,
        )

        decision = machine.update("track:camera_01:41", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "motion_observe")

    def test_low_floor_contact_still_waits_without_floor_risk_context(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=5, fall_still_ms=1500))
        feature = self._feature(delta_y=82.0, aspect_ratio=1.24, speed=16.0)
        prediction = SequencePrediction(fall_probability=0.90, window_size=32)
        scores = self._scores(
            fall_evidence=0.86,
            adl_suppression=0.20,
            vertical_drop=0.96,
            low_posture=0.96,
            stillness=0.20,
            floor_contact=0.34,
            impact=0.78,
            low_posture_ms=650,
        )

        decision = machine.update("track:camera_01:26", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "fast_fall_path")
        self.assertEqual(decision.rejected_reason, "awaiting_fast_confirm")

    def test_slow_fall_path_waits_before_hold_threshold(self) -> None:
        machine = FallStateMachine(self._settings())
        feature = self._feature(delta_y=10.0, aspect_ratio=1.1, speed=4.0)
        prediction = SequencePrediction(fall_probability=0.58, window_size=32)
        scores = self._scores(
            fall_evidence=0.66,
            adl_suppression=0.28,
            vertical_drop=0.25,
            low_posture=0.82,
            stillness=0.82,
            floor_contact=0.75,
            continuous_descent=0.72,
            low_posture_ms=2000,
        )

        decision = machine.update("track:camera_01:3", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_candidate")
        self.assertEqual(decision.motion_path, "slow_fall_path")
        self.assertEqual(decision.rejected_reason, "awaiting_slow_low_posture_hold")

    def test_slow_fall_short_clip_confirms_with_floor_risk_grounded_hold(self) -> None:
        machine = FallStateMachine(self._settings())
        feature = self._feature(delta_y=18.0, aspect_ratio=1.18, speed=2.0)
        prediction = SequencePrediction(fall_probability=0.60, window_size=32)
        scores = self._scores(
            fall_evidence=0.58,
            adl_suppression=0.33,
            vertical_drop=0.77,
            low_posture=1.0,
            stillness=0.83,
            floor_contact=0.33,
            impact=0.75,
            continuous_descent=0.70,
            low_posture_ms=960,
            recovery=0.0,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:31", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "slow_fall_path")

    def test_slow_fall_short_clip_waits_without_grounded_hold(self) -> None:
        machine = FallStateMachine(self._settings())
        feature = self._feature(delta_y=14.0, aspect_ratio=1.08, speed=3.0)
        prediction = SequencePrediction(fall_probability=0.58, window_size=32)
        scores = self._scores(
            fall_evidence=0.60,
            adl_suppression=0.36,
            vertical_drop=0.88,
            low_posture=1.0,
            stillness=0.20,
            floor_contact=0.52,
            impact=0.65,
            continuous_descent=0.70,
            low_posture_ms=0,
            recovery=0.0,
            floor_risk_score=1.0,
            support_surface=0.0,
        )

        decision = machine.update("track:camera_01:32", feature, prediction, v6_scores=scores)

        self.assertEqual(decision.fall_state, "fallen_candidate")
        self.assertEqual(decision.motion_path, "slow_fall_path")

    def test_adl_suppression_blocks_confirmation(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=1, fall_still_ms=0))
        feature = self._feature(delta_y=8.0, aspect_ratio=0.68, speed=8.0, torso_angle=48.0)
        prediction = SequencePrediction(fall_probability=0.82, window_size=32)
        scores = self._scores(
            fall_evidence=0.70,
            adl_suppression=0.76,
            vertical_drop=0.20,
            impact=0.20,
            low_posture=0.45,
            recovery=0.65,
            adl_reasons=["bending_like_motion", "quick_recovery"],
        )

        decision = machine.update("track:camera_01:4", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "recovery_observed")
        self.assertIn("quick_recovery", decision.decision_reason)

    def test_adl_suppression_without_recovery_uses_adl_path(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=1, fall_still_ms=0))
        feature = self._feature(delta_y=12.0, aspect_ratio=0.72, speed=6.0, torso_angle=42.0)
        prediction = SequencePrediction(fall_probability=0.78, window_size=32)
        scores = self._scores(
            fall_evidence=0.69,
            adl_suppression=0.72,
            vertical_drop=0.20,
            impact=0.18,
            low_posture=0.42,
            recovery=0.20,
            adl_reasons=["bending_like_motion", "controlled_descent"],
        )

        decision = machine.update("track:camera_01:44", feature, prediction, v6_scores=scores)

        self.assertNotEqual(decision.fall_state, "fallen_confirmed")
        self.assertEqual(decision.motion_path, "adl_suppressed")
        self.assertTrue(decision.suppressed_by_adl)
        self.assertEqual(decision.rejected_reason, "adl_suppression")

    def test_confirmed_event_enters_cooldown_without_repeating(self) -> None:
        machine = FallStateMachine(self._settings(fall_confirm_frames=1, fall_still_ms=0))
        feature = self._feature(delta_y=80.0, aspect_ratio=1.25, speed=2.0)
        prediction = SequencePrediction(fall_probability=0.92, window_size=32)
        scores = self._scores(
            fall_evidence=0.88,
            adl_suppression=0.10,
            vertical_drop=0.9,
            low_posture=0.9,
            stillness=0.9,
            floor_contact=0.9,
            low_posture_ms=2500,
        )

        confirmed = machine.update("track:camera_01:5", feature, prediction, v6_scores=scores)
        cooldown = machine.update("track:camera_01:5", feature, prediction, v6_scores=scores)

        self.assertEqual(confirmed.fall_state, "fallen_confirmed")
        self.assertEqual(cooldown.fall_state, "cooldown")
        self.assertEqual(cooldown.motion_path, "cooldown_active")
        self.assertTrue(cooldown.fall_latched)

    @staticmethod
    def _settings(**kwargs) -> Settings:
        return replace(
            Settings(),
            fall_v6_scoring_enabled=True,
            fall_v6_decision_enabled=True,
            slow_fall_enabled=True,
            **kwargs,
        )

    @staticmethod
    def _feature(
        *,
        delta_y: float,
        aspect_ratio: float,
        speed: float,
        torso_angle: float = 8.0,
    ) -> TargetFeature:
        return TargetFeature(
            track_id=1,
            timestamp="2026-07-03T00:00:00Z",
            monotonic_time=1.0,
            object_confidence=0.95,
            bbox_center_x=320.0,
            bbox_center_y=480.0,
            bbox_width=220.0,
            bbox_height=180.0,
            aspect_ratio=aspect_ratio,
            delta_x=0.0,
            delta_y=delta_y,
            velocity_x=0.0,
            velocity_y=delta_y * 10,
            speed=speed,
            pose_available=True,
            pose_confidence=0.9,
            torso_angle=torso_angle,
            hip_height_ratio=0.75,
            head_height_ratio=0.55,
        )

    @staticmethod
    def _scores(
        *,
        fall_evidence: float,
        adl_suppression: float,
        vertical_drop: float = 0.0,
        impact: float = 0.7,
        low_posture: float = 0.0,
        stillness: float = 0.0,
        floor_contact: float = 0.0,
        continuous_descent: float = 0.0,
        low_posture_ms: int = 0,
        recovery: float = 0.0,
        adl_reasons: list[str] | None = None,
        floor_risk_score: float = 0.0,
        support_surface: float = 0.05,
    ) -> TemporalV6Scores:
        return TemporalV6Scores(
            motion=TemporalMotionSummary(
                continuous_descent_score=continuous_descent,
                low_posture_duration_ms=low_posture_ms,
                track_quality_score=0.95,
            ),
            fall=FallEvidenceScores(
                fall_evidence_score=fall_evidence,
                vertical_drop_score=vertical_drop,
                low_posture_score=low_posture,
                impact_proxy_score=impact,
                post_fall_stillness_score=stillness,
                floor_contact_score=floor_contact,
                reasons=["test_fall_evidence"],
            ),
            adl=ADLSuppressionScores(
                adl_suppression_score=adl_suppression,
                recovery_score=recovery,
                support_surface_score=support_surface,
                reasons=adl_reasons or [],
            ),
            scene=SceneContext(floor_risk_score=floor_risk_score),
        )


if __name__ == "__main__":
    unittest.main()
