from __future__ import annotations

from app.temporal.schemas import SequencePrediction, TargetFeature


class MockSequenceModel:
    def predict(self, window: list[TargetFeature]) -> SequencePrediction:
        if not window:
            return SequencePrediction(fall_probability=0.0)

        latest = window[-1]
        recent = window[-6:]
        probability = 0.05

        max_delta_y = max((item.delta_y for item in recent), default=0.0)
        total_downward_delta = max(0.0, latest.bbox_center_y - recent[0].bbox_center_y)
        latest_low_posture = self._is_low_posture(latest)
        still_after_low = latest_low_posture and latest.speed < 20
        torso_change = self._max_torso_change(recent)
        downward_trend = self._downward_trend(recent)
        rapid_descent = max_delta_y > 40 or total_downward_delta > 85

        if max_delta_y > 55:
            probability += 0.5
        elif max_delta_y > 45:
            probability += 0.44
        elif max_delta_y > 40:
            probability += 0.38
        elif max_delta_y > 35 and downward_trend:
            probability += 0.12
        elif max_delta_y > 28 and downward_trend:
            probability += 0.08
        # Offline evaluation can inflate velocity when frames are processed faster
        # than real time, so velocity is only a weak assist when bbox displacement
        # already shows a meaningful downward trend.
        if downward_trend and max_delta_y > 35:
            probability += 0.06
        if downward_trend and max_delta_y > 40:
            probability += 0.12
        elif downward_trend and total_downward_delta > 70:
            probability += 0.1
        if torso_change > 35:
            probability += 0.18
        if latest_low_posture and rapid_descent:
            probability += 0.18
        elif latest_low_posture:
            probability += 0.06
        if still_after_low and len(window) >= 4 and rapid_descent:
            probability += 0.12
        if self._looks_like_low_confidence_fallen_candidate(latest, window):
            probability += 0.38

        if self._looks_like_normal_motion(recent):
            probability -= 0.2
        if self._looks_like_controlled_sitting(recent):
            probability -= 0.28
        if self._looks_like_bending(latest):
            probability -= 0.18
        if (
            latest_low_posture
            and not rapid_descent
            and latest.speed < 25
            and not self._looks_like_low_confidence_fallen_candidate(latest, window)
        ):
            probability -= 0.12

        probability = max(0.0, min(1.0, probability))
        return SequencePrediction(fall_probability=round(probability, 4))

    @staticmethod
    def _is_low_posture(feature: TargetFeature) -> bool:
        if feature.aspect_ratio >= 0.9:
            return True
        if feature.head_height_ratio is not None and feature.head_height_ratio > 0.45:
            return True
        if feature.hip_height_ratio is not None and feature.hip_height_ratio > 0.68:
            return True
        return False

    @staticmethod
    def _max_torso_change(window: list[TargetFeature]) -> float:
        values = [item.torso_angle for item in window if item.torso_angle is not None]
        if len(values) < 2:
            return 0.0
        return max(values) - min(values)

    @staticmethod
    def _downward_trend(window: list[TargetFeature]) -> bool:
        if len(window) < 3:
            return False
        meaningful_down_steps = sum(1 for item in window[1:] if item.delta_y > 10)
        strong_down_steps = sum(1 for item in window[1:] if item.delta_y > 28)
        total_down = window[-1].bbox_center_y - window[0].bbox_center_y
        return meaningful_down_steps >= 2 and (strong_down_steps >= 1 or total_down > 70)

    @staticmethod
    def _looks_like_normal_motion(window: list[TargetFeature]) -> bool:
        if not window:
            return False
        avg_speed = sum(item.speed for item in window) / len(window)
        avg_abs_y = sum(abs(item.velocity_y) for item in window) / len(window)
        return avg_speed > 35 and avg_abs_y < 90

    @staticmethod
    def _looks_like_controlled_sitting(window: list[TargetFeature]) -> bool:
        if len(window) < 4:
            return False
        vertical = [item.velocity_y for item in window]
        max_down = max(vertical)
        total_down = window[-1].bbox_center_y - window[0].bbox_center_y
        latest = window[-1]
        return (
            20 < max_down < 180
            and total_down < 120
            and latest.speed < 45
            and latest.aspect_ratio < 0.9
        )

    @staticmethod
    def _looks_like_bending(feature: TargetFeature) -> bool:
        angle = abs(feature.torso_angle) if feature.torso_angle is not None else 0.0
        return 30 <= angle <= 65 and feature.aspect_ratio < 0.85

    @staticmethod
    def _looks_like_low_confidence_fallen_candidate(feature: TargetFeature, window: list[TargetFeature]) -> bool:
        if len(window) < 8:
            return False
        if feature.object_confidence > 0.35:
            return False
        if feature.aspect_ratio < 1.15 and not (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        ):
            return False
        recent = window[-6:]
        avg_speed = sum(item.speed for item in recent) / len(recent)
        return avg_speed < 28
