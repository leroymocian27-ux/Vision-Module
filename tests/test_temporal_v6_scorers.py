from __future__ import annotations

import unittest

from app.core.config import Settings
from app.temporal.adl_suppressor import ADLSuppressor
from app.temporal.fall_evidence_scorer import FallEvidenceScorer
from app.temporal.scene_context import SceneContextResolver
from app.temporal.schemas import SequencePrediction, TargetFeature
from app.temporal.temporal_motion_features import TemporalMotionFeatureBuilder


class TemporalV6ScorerTest(unittest.TestCase):
    def test_fast_fall_sequence_scores_high_fall_evidence(self) -> None:
        window = [
            self._feature(index=i, center_y=260 + i * 18, aspect_ratio=0.45 + i * 0.055, delta_y=18.0, speed=42.0)
            for i in range(14)
        ]
        window.append(self._feature(index=14, center_y=540, aspect_ratio=1.22, delta_y=76.0, speed=5.0))
        motion = TemporalMotionFeatureBuilder().build(window)
        fall = FallEvidenceScorer(Settings()).score(
            feature=window[-1],
            prediction=SequencePrediction(fall_probability=0.9, window_size=32),
            motion=motion,
            frame_height=720,
        )

        self.assertGreaterEqual(fall.fall_evidence_score, 0.75)
        self.assertIn("high_lstm_probability", fall.reasons)
        self.assertIn("fast_vertical_drop", fall.reasons)

    def test_bending_like_sequence_scores_adl_suppression(self) -> None:
        window = [
            self._feature(index=i, center_y=320 + i * 3, aspect_ratio=0.45, delta_y=3.0, speed=10.0, torso_angle=15 + i * 3)
            for i in range(12)
        ]
        latest = self._feature(index=12, center_y=356, aspect_ratio=0.62, delta_y=3.0, speed=8.0, torso_angle=55.0)
        latest.head_height_ratio = 0.62
        latest.hip_height_ratio = 0.48
        window.append(latest)
        motion = TemporalMotionFeatureBuilder().build(window)
        fall = FallEvidenceScorer(Settings()).score(
            feature=latest,
            prediction=SequencePrediction(fall_probability=0.7, window_size=32),
            motion=motion,
            frame_height=720,
        )
        adl = ADLSuppressor(Settings()).score(feature=latest, motion=motion, fall=fall)

        self.assertGreaterEqual(adl.bending_score, 0.55)
        self.assertGreater(adl.adl_suppression_score, 0.35)
        self.assertIn("bending_like_motion", adl.reasons)

    def test_support_surface_scene_context_boosts_adl_support_evidence(self) -> None:
        latest = self._feature(index=8, center_y=430, aspect_ratio=0.92, delta_y=1.0, speed=2.0)
        motion = TemporalMotionFeatureBuilder().build([latest])
        fall = FallEvidenceScorer(Settings()).score(
            feature=latest,
            prediction=SequencePrediction(fall_probability=0.65, window_size=32),
            motion=motion,
            frame_height=720,
        )
        context = SceneContextResolver.from_payload(
            {"scene_context": {"scene_type": "support_surface_zone", "support_surface": "bed"}}
        )

        adl = ADLSuppressor(Settings()).score(feature=latest, motion=motion, fall=fall, scene_context=context)

        self.assertGreaterEqual(adl.support_surface_score, 0.85)
        self.assertIn("support_surface_likely", adl.reasons)
        self.assertIn("support_surface_context", adl.reasons)

    def test_floor_risk_scene_context_does_not_boost_support_surface(self) -> None:
        latest = self._feature(index=8, center_y=430, aspect_ratio=0.92, delta_y=1.0, speed=2.0)
        motion = TemporalMotionFeatureBuilder().build([latest])
        fall = FallEvidenceScorer(Settings()).score(
            feature=latest,
            prediction=SequencePrediction(fall_probability=0.65, window_size=32),
            motion=motion,
            frame_height=720,
        )
        context = SceneContextResolver.from_payload({"scene_context": {"scene_type": "floor_risk_zone"}})

        adl = ADLSuppressor(Settings()).score(feature=latest, motion=motion, fall=fall, scene_context=context)

        self.assertLess(adl.support_surface_score, 0.60)
        self.assertIn("floor_risk_zone_context", adl.reasons)

    @staticmethod
    def _feature(
        *,
        index: int,
        center_y: float,
        aspect_ratio: float,
        delta_y: float,
        speed: float,
        torso_angle: float = 8.0,
    ) -> TargetFeature:
        return TargetFeature(
            track_id=1,
            timestamp="2026-07-03T00:00:00Z",
            monotonic_time=float(index) * 0.2,
            object_confidence=0.95,
            bbox_center_x=320.0,
            bbox_center_y=center_y,
            bbox_width=180.0,
            bbox_height=max(80.0, 180.0 / max(aspect_ratio, 0.1)),
            aspect_ratio=aspect_ratio,
            delta_x=0.0,
            delta_y=delta_y,
            velocity_x=0.0,
            velocity_y=delta_y * 5,
            speed=speed,
            pose_available=True,
            pose_confidence=0.9,
            torso_angle=torso_angle,
            hip_height_ratio=0.72,
            head_height_ratio=0.52,
        )


if __name__ == "__main__":
    unittest.main()
