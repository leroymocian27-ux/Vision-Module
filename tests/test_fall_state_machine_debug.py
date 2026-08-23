from __future__ import annotations

from dataclasses import replace
import unittest

from app.core.config import Settings
from app.temporal.fall_state_machine import FallStateMachine
from app.temporal.schemas import SequencePrediction, TargetFeature


class FallStateMachineDebugTest(unittest.TestCase):
    def test_low_probability_reason_is_exposed(self) -> None:
        machine = FallStateMachine(Settings())
        decision = machine.update(
            "track:camera_01:7",
            self._feature(
                delta_y=6.0,
                aspect_ratio=0.42,
                speed=12.0,
                velocity_y=11.0,
                hip_height_ratio=0.34,
                head_height_ratio=0.16,
            ),
            SequencePrediction(fall_probability=0.22, window_size=16),
        )

        self.assertEqual(decision.fall_state, "normal")
        self.assertEqual(decision.rejected_reason, "low_fall_probability")
        self.assertFalse(decision.low_posture)
        self.assertTrue(decision.stillness)

    def test_candidate_wait_reason_is_exposed(self) -> None:
        settings = replace(Settings(), fall_confirm_frames=3, fall_still_ms=5000)
        machine = FallStateMachine(settings)
        feature = self._feature(delta_y=60.0, aspect_ratio=1.18, speed=8.0, velocity_y=120.0)
        prediction = SequencePrediction(fall_probability=0.88, window_size=16)

        first = machine.update("track:camera_01:9", feature, prediction)
        second = machine.update("track:camera_01:9", feature, prediction)

        self.assertEqual(first.fall_state, "falling")
        self.assertEqual(second.fall_state, "fallen_candidate")
        self.assertEqual(second.rejected_reason, "awaiting_confirm_frames_and_duration")
        self.assertGreaterEqual(second.confirm_frames, 1)
        self.assertGreaterEqual(second.candidate_duration_ms, 0)

    @staticmethod
    def _feature(
        *,
        delta_y: float,
        aspect_ratio: float,
        speed: float,
        velocity_y: float,
        hip_height_ratio: float = 0.78,
        head_height_ratio: float = 0.52,
    ) -> TargetFeature:
        return TargetFeature(
            track_id=7,
            timestamp="2026-06-17T00:00:00Z",
            monotonic_time=1.0,
            object_confidence=0.9,
            bbox_center_x=320.0,
            bbox_center_y=240.0,
            bbox_width=140.0,
            bbox_height=220.0,
            aspect_ratio=aspect_ratio,
            delta_x=0.0,
            delta_y=delta_y,
            velocity_x=0.0,
            velocity_y=velocity_y,
            speed=speed,
            pose_available=True,
            pose_confidence=0.92,
            torso_angle=7.5,
            hip_height_ratio=hip_height_ratio,
            head_height_ratio=head_height_ratio,
        )


if __name__ == "__main__":
    unittest.main()
