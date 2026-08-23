from __future__ import annotations

from app.core.config import Settings
from app.temporal.schemas import FallEvidenceScores, SequencePrediction, TargetFeature, TemporalMotionSummary


class FallEvidenceScorer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def score(
        self,
        *,
        feature: TargetFeature,
        prediction: SequencePrediction,
        motion: TemporalMotionSummary,
        frame_height: int,
    ) -> FallEvidenceScores:
        vertical_drop_score = self._clip01(
            max(
                motion.max_downward_delta_16f / 70.0,
                motion.cumulative_drop_16f / 140.0,
                motion.cumulative_drop_32f / 180.0,
            )
        )
        aspect_ratio_change_score = self._clip01(
            max(
                motion.aspect_ratio_change_16f / 0.75,
                (feature.aspect_ratio - 0.75) / 0.75,
            )
        )
        low_posture_score = self._low_posture_score(feature)
        stillness_score = self._clip01(1.0 - feature.speed / 45.0)
        post_fall_stillness_score = self._clip01(
            stillness_score * 0.65 + min(motion.low_posture_duration_ms / max(1, self.settings.fall_still_ms), 1.0) * 0.35
        )
        floor_contact_score = self._floor_contact_score(feature, frame_height)
        impact_proxy_score = self._clip01(
            vertical_drop_score * 0.45
            + aspect_ratio_change_score * 0.20
            + post_fall_stillness_score * 0.25
            + self._clip01((motion.max_downward_velocity_16f - 120.0) / 600.0) * 0.10
        )
        fall_evidence_score = self._clip01(
            0.30 * prediction.fall_probability
            + 0.18 * vertical_drop_score
            + 0.14 * aspect_ratio_change_score
            + 0.12 * low_posture_score
            + 0.10 * impact_proxy_score
            + 0.10 * post_fall_stillness_score
            + 0.06 * floor_contact_score
        )
        reasons = self._reasons(
            prediction=prediction,
            vertical_drop_score=vertical_drop_score,
            aspect_ratio_change_score=aspect_ratio_change_score,
            low_posture_score=low_posture_score,
            impact_proxy_score=impact_proxy_score,
            post_fall_stillness_score=post_fall_stillness_score,
            floor_contact_score=floor_contact_score,
        )
        return FallEvidenceScores(
            fall_evidence_score=round(fall_evidence_score, 4),
            vertical_drop_score=round(vertical_drop_score, 4),
            aspect_ratio_change_score=round(aspect_ratio_change_score, 4),
            low_posture_score=round(low_posture_score, 4),
            impact_proxy_score=round(impact_proxy_score, 4),
            post_fall_stillness_score=round(post_fall_stillness_score, 4),
            floor_contact_score=round(floor_contact_score, 4),
            reasons=reasons,
        )

    @staticmethod
    def _low_posture_score(feature: TargetFeature) -> float:
        bbox_score = FallEvidenceScorer._clip01((feature.aspect_ratio - 0.65) / 0.7)
        head_score = 0.0 if feature.head_height_ratio is None else FallEvidenceScorer._clip01((feature.head_height_ratio - 0.35) / 0.35)
        hip_score = 0.0 if feature.hip_height_ratio is None else FallEvidenceScorer._clip01((feature.hip_height_ratio - 0.50) / 0.30)
        return max(bbox_score, (head_score + hip_score) / 2)

    @staticmethod
    def _floor_contact_score(feature: TargetFeature, frame_height: int) -> float:
        height = max(float(frame_height), 1.0)
        bottom_norm = (feature.bbox_center_y + feature.bbox_height / 2) / height
        center_norm = feature.bbox_center_y / height
        bottom_score = FallEvidenceScorer._clip01((bottom_norm - 0.58) / 0.30)
        center_score = FallEvidenceScorer._clip01((center_norm - 0.45) / 0.30)
        return max(bottom_score, center_score)

    @staticmethod
    def _reasons(
        *,
        prediction: SequencePrediction,
        vertical_drop_score: float,
        aspect_ratio_change_score: float,
        low_posture_score: float,
        impact_proxy_score: float,
        post_fall_stillness_score: float,
        floor_contact_score: float,
    ) -> list[str]:
        reasons: list[str] = []
        if prediction.fall_probability >= 0.65:
            reasons.append("high_lstm_probability")
        if vertical_drop_score >= 0.65:
            reasons.append("fast_vertical_drop")
        if aspect_ratio_change_score >= 0.55:
            reasons.append("body_became_horizontal")
        if low_posture_score >= 0.60:
            reasons.append("low_posture")
        if impact_proxy_score >= 0.55:
            reasons.append("impact_proxy")
        if post_fall_stillness_score >= 0.60:
            reasons.append("post_fall_stillness")
        if floor_contact_score >= 0.60:
            reasons.append("floor_contact_likely")
        return reasons

    @staticmethod
    def _clip01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
