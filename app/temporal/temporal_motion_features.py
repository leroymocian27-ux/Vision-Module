from __future__ import annotations

from app.temporal.schemas import TargetFeature, TemporalMotionSummary


class TemporalMotionFeatureBuilder:
    def build(self, window: list[TargetFeature]) -> TemporalMotionSummary:
        if not window:
            return TemporalMotionSummary()

        recent16 = window[-16:]
        latest = window[-1]
        return TemporalMotionSummary(
            cumulative_drop_8f=self._cumulative_drop(window[-8:]),
            cumulative_drop_16f=self._cumulative_drop(recent16),
            cumulative_drop_32f=self._cumulative_drop(window[-32:]),
            max_downward_delta_16f=max((item.delta_y for item in recent16), default=0.0),
            max_downward_velocity_16f=max((item.velocity_y for item in recent16), default=0.0),
            center_y_trend_score=self._center_y_trend(recent16),
            continuous_descent_score=self._continuous_descent(recent16),
            aspect_ratio_change_16f=self._aspect_ratio_change(recent16),
            bbox_bottom_stability_16f=self._bbox_bottom_stability(recent16),
            low_posture_duration_ms=self._duration_ms(window, self._is_low_posture),
            horizontal_posture_duration_ms=self._duration_ms(
                window,
                lambda item: item.aspect_ratio >= 0.95,
            ),
            recovery_upward_score_16f=self._recovery_upward(recent16),
            post_drop_speed_min_16f=min((item.speed for item in recent16), default=latest.speed),
            track_quality_score=self._track_quality(recent16),
        )

    @staticmethod
    def _cumulative_drop(window: list[TargetFeature]) -> float:
        if len(window) < 2:
            return 0.0
        return max(0.0, window[-1].bbox_center_y - window[0].bbox_center_y)

    @staticmethod
    def _center_y_trend(window: list[TargetFeature]) -> float:
        if len(window) < 3:
            return 0.0
        down_steps = sum(1 for item in window[1:] if item.delta_y > 4)
        return TemporalMotionFeatureBuilder._clip01(down_steps / max(1, len(window) - 1))

    @staticmethod
    def _continuous_descent(window: list[TargetFeature]) -> float:
        if len(window) < 4:
            return 0.0
        meaningful = sum(1 for item in window[1:] if item.delta_y > 8)
        total_drop = TemporalMotionFeatureBuilder._cumulative_drop(window)
        return TemporalMotionFeatureBuilder._clip01((meaningful / max(1, len(window) - 1)) * 0.6 + min(total_drop / 140.0, 1.0) * 0.4)

    @staticmethod
    def _aspect_ratio_change(window: list[TargetFeature]) -> float:
        if len(window) < 2:
            return 0.0
        return max(0.0, window[-1].aspect_ratio - window[0].aspect_ratio)

    @staticmethod
    def _bbox_bottom_stability(window: list[TargetFeature]) -> float:
        if len(window) < 3:
            return 0.0
        bottoms = [item.bbox_center_y + item.bbox_height / 2 for item in window]
        height = max(window[-1].bbox_height, 1.0)
        spread = max(bottoms) - min(bottoms)
        return 1.0 - TemporalMotionFeatureBuilder._clip01(spread / max(35.0, height * 0.18))

    @staticmethod
    def _duration_ms(window: list[TargetFeature], predicate) -> int:
        if not window:
            return 0
        latest_time = window[-1].monotonic_time
        start_time = latest_time
        for item in reversed(window):
            if not predicate(item):
                break
            start_time = item.monotonic_time
        return max(0, int((latest_time - start_time) * 1000))

    @staticmethod
    def _recovery_upward(window: list[TargetFeature]) -> float:
        if len(window) < 3:
            return 0.0
        upward_steps = sum(1 for item in window[1:] if item.delta_y < -8)
        center_recovery = max(0.0, window[0].bbox_center_y - window[-1].bbox_center_y)
        aspect_recovery = max(0.0, window[0].aspect_ratio - window[-1].aspect_ratio)
        return TemporalMotionFeatureBuilder._clip01(
            (upward_steps / max(1, len(window) - 1)) * 0.45
            + min(center_recovery / 100.0, 1.0) * 0.35
            + min(aspect_recovery / 0.6, 1.0) * 0.20
        )

    @staticmethod
    def _track_quality(window: list[TargetFeature]) -> float:
        if len(window) < 2:
            return 1.0
        jump_count = 0
        for item in window[1:]:
            if abs(item.delta_x) > max(120.0, item.bbox_width * 0.75) or abs(item.delta_y) > max(160.0, item.bbox_height * 0.75):
                jump_count += 1
        avg_conf = sum(item.object_confidence for item in window) / len(window)
        jump_penalty = min(jump_count / 3.0, 1.0)
        return TemporalMotionFeatureBuilder._clip01(avg_conf * 0.75 + (1.0 - jump_penalty) * 0.25)

    @staticmethod
    def _is_low_posture(feature: TargetFeature) -> bool:
        return feature.aspect_ratio >= 0.95 or (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        )

    @staticmethod
    def _clip01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
