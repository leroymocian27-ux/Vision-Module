from __future__ import annotations

from app.core.config import Settings
from app.temporal.scene_context import SceneContext
from app.temporal.schemas import ADLSuppressionScores, FallEvidenceScores, TargetFeature, TemporalMotionSummary


class ADLSuppressor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def score(
        self,
        *,
        feature: TargetFeature,
        motion: TemporalMotionSummary,
        fall: FallEvidenceScores,
        scene_context: SceneContext | None = None,
    ) -> ADLSuppressionScores:
        recovery_score = motion.recovery_upward_score_16f
        controlled_descent_score = self._controlled_descent_score(motion, fall)
        sitting_score = self._sitting_score(feature, motion, controlled_descent_score)
        bending_score = self._bending_score(feature, motion, recovery_score)
        normal_lying_score = self._normal_lying_score(feature, motion, fall, controlled_descent_score)
        squatting_score = self._squatting_score(feature, motion, recovery_score)
        support_surface_score = self._support_surface_score(feature, motion, scene_context)
        track_instability_score = self._clip01(1.0 - motion.track_quality_score)
        weighted_score = self._clip01(
            0.18 * sitting_score
            + 0.18 * bending_score
            + 0.16 * normal_lying_score
            + 0.12 * squatting_score
            + 0.14 * controlled_descent_score
            + 0.10 * support_surface_score
            + 0.08 * recovery_score
            + 0.04 * track_instability_score
        )
        strongest_adl = max(sitting_score, bending_score, normal_lying_score, squatting_score)
        adl_suppression_score = self._clip01(max(weighted_score, strongest_adl * 0.72))
        return ADLSuppressionScores(
            adl_suppression_score=round(adl_suppression_score, 4),
            sitting_score=round(sitting_score, 4),
            bending_score=round(bending_score, 4),
            normal_lying_score=round(normal_lying_score, 4),
            squatting_score=round(squatting_score, 4),
            controlled_descent_score=round(controlled_descent_score, 4),
            support_surface_score=round(support_surface_score, 4),
            recovery_score=round(recovery_score, 4),
            track_instability_score=round(track_instability_score, 4),
            reasons=self._reasons(
                sitting_score=sitting_score,
                bending_score=bending_score,
                normal_lying_score=normal_lying_score,
                squatting_score=squatting_score,
                controlled_descent_score=controlled_descent_score,
                support_surface_score=support_surface_score,
                recovery_score=recovery_score,
                track_instability_score=track_instability_score,
                scene_context=scene_context,
            ),
        )

    @staticmethod
    def _controlled_descent_score(motion: TemporalMotionSummary, fall: FallEvidenceScores) -> float:
        smooth_descent = motion.center_y_trend_score * (1.0 - fall.impact_proxy_score)
        bottom_stable = motion.bbox_bottom_stability_16f
        not_rapid = 1.0 - fall.vertical_drop_score
        return ADLSuppressor._clip01(smooth_descent * 0.45 + bottom_stable * 0.35 + not_rapid * 0.20)

    @staticmethod
    def _sitting_score(feature: TargetFeature, motion: TemporalMotionSummary, controlled_descent_score: float) -> float:
        uprightish = 1.0 - ADLSuppressor._clip01((feature.aspect_ratio - 0.75) / 0.55)
        bottom_stable = motion.bbox_bottom_stability_16f
        low_but_not_horizontal = ADLSuppressor._clip01((feature.bbox_center_y - 250.0) / 260.0) * uprightish
        return ADLSuppressor._clip01(controlled_descent_score * 0.40 + bottom_stable * 0.35 + low_but_not_horizontal * 0.25)

    @staticmethod
    def _bending_score(feature: TargetFeature, motion: TemporalMotionSummary, recovery_score: float) -> float:
        angle = abs(feature.torso_angle) if feature.torso_angle is not None else 0.0
        torso_bent = ADLSuppressor._clip01((angle - 25.0) / 45.0)
        head_low = 0.0 if feature.head_height_ratio is None else ADLSuppressor._clip01((feature.head_height_ratio - 0.35) / 0.35)
        hip_not_low = 1.0 if feature.hip_height_ratio is None else 1.0 - ADLSuppressor._clip01((feature.hip_height_ratio - 0.55) / 0.25)
        not_horizontal = 1.0 - ADLSuppressor._clip01((feature.aspect_ratio - 0.70) / 0.55)
        return ADLSuppressor._clip01(torso_bent * 0.30 + head_low * hip_not_low * 0.30 + motion.bbox_bottom_stability_16f * 0.20 + max(recovery_score, not_horizontal) * 0.20)

    @staticmethod
    def _normal_lying_score(
        feature: TargetFeature,
        motion: TemporalMotionSummary,
        fall: FallEvidenceScores,
        controlled_descent_score: float,
    ) -> float:
        horizontal = ADLSuppressor._clip01((feature.aspect_ratio - 0.85) / 0.65)
        long_transition = controlled_descent_score
        no_impact = 1.0 - fall.impact_proxy_score
        return ADLSuppressor._clip01(horizontal * 0.35 + long_transition * 0.40 + no_impact * 0.25)

    @staticmethod
    def _squatting_score(feature: TargetFeature, motion: TemporalMotionSummary, recovery_score: float) -> float:
        short_box = ADLSuppressor._clip01((260.0 - feature.bbox_height) / 180.0)
        bottom_stable = motion.bbox_bottom_stability_16f
        not_horizontal = 1.0 - ADLSuppressor._clip01((feature.aspect_ratio - 0.75) / 0.55)
        return ADLSuppressor._clip01(short_box * 0.30 + bottom_stable * 0.35 + not_horizontal * 0.20 + recovery_score * 0.15)

    @staticmethod
    def _support_surface_score(
        feature: TargetFeature,
        motion: TemporalMotionSummary,
        scene_context: SceneContext | None,
    ) -> float:
        del motion
        # Without scene polygons, only infer weak support evidence from stable seated-like posture.
        seated_like = 1.0 - ADLSuppressor._clip01((feature.aspect_ratio - 0.75) / 0.55)
        heuristic_score = ADLSuppressor._clip01(seated_like * 0.35)
        context_score = scene_context.support_surface_score if scene_context is not None else 0.0
        return ADLSuppressor._clip01(max(heuristic_score, context_score))

    @staticmethod
    def _reasons(
        *,
        sitting_score: float,
        bending_score: float,
        normal_lying_score: float,
        squatting_score: float,
        controlled_descent_score: float,
        support_surface_score: float,
        recovery_score: float,
        track_instability_score: float,
        scene_context: SceneContext | None,
    ) -> list[str]:
        reasons: list[str] = []
        if sitting_score >= 0.60:
            reasons.append("sitting_like_motion")
        if bending_score >= 0.60:
            reasons.append("bending_like_motion")
        if normal_lying_score >= 0.60:
            reasons.append("normal_lying_like_motion")
        if squatting_score >= 0.60:
            reasons.append("squat_kneel_like_motion")
        if controlled_descent_score >= 0.60:
            reasons.append("controlled_descent")
        if support_surface_score >= 0.60:
            reasons.append("support_surface_likely")
        if recovery_score >= 0.60:
            reasons.append("quick_recovery")
        if track_instability_score >= 0.50:
            reasons.append("track_instability")
        if scene_context is not None:
            reasons.extend(scene_context.reasons)
        return reasons

    @staticmethod
    def _clip01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
