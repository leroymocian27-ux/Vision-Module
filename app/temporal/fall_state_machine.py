from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import Settings
from app.temporal.schemas import FallDecision, FallState, RiskLevel, SequencePrediction, TargetFeature, TemporalV6Scores


@dataclass
class _FallRuntime:
    state: FallState = FallState.NORMAL
    abnormal_frames: int = 0
    confirm_frames: int = 0
    candidate_started_at: float | None = None
    cooldown_until: float | None = None
    last_probability: float = 0.0
    falling_seen: bool = False
    recent_rapid_descent: bool = False
    rapid_descent_seen_at: float | None = None
    low_confidence_candidate_frames: int = 0
    slow_candidate_started_at: float | None = None
    fall_latched: bool = False
    fall_session_id: int = 0


class FallStateMachine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._states: dict[str, _FallRuntime] = {}

    def update(
        self,
        key: str,
        feature: TargetFeature,
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None = None,
    ) -> FallDecision:
        runtime = self._states.setdefault(key, _FallRuntime())
        now = time.monotonic()
        runtime.last_probability = prediction.fall_probability
        if self._has_rapid_descent(feature):
            runtime.recent_rapid_descent = True
            runtime.rapid_descent_seen_at = now
        elif (
            runtime.rapid_descent_seen_at is not None
            and (now - runtime.rapid_descent_seen_at) * 1000 > self.settings.fall_still_ms * 2
        ):
            runtime.recent_rapid_descent = False

        if runtime.state == FallState.COOLDOWN:
            if runtime.cooldown_until is not None and now < runtime.cooldown_until:
                return self._with_v6_debug(self._decision(runtime, now), runtime, v6_scores, "cooldown_active")
            self._reset_runtime(runtime)
            return self._with_v6_debug(self._decision(runtime, now), runtime, v6_scores, "cooldown_complete")
        if runtime.state == FallState.FALLEN_CONFIRMED:
            runtime.state = FallState.COOLDOWN
            runtime.cooldown_until = now + self.settings.cooldown_seconds
            return self._with_v6_debug(self._decision(runtime, now), runtime, v6_scores, "cooldown_active")

        if self.settings.fall_v6_decision_enabled and v6_scores is not None:
            return self._update_v6(runtime=runtime, feature=feature, prediction=prediction, scores=v6_scores, now=now)

        strong_falling_evidence = self._is_strong_falling_evidence(feature, prediction)
        abnormal = self._is_abnormal(feature, prediction)
        low_confidence_fallen_candidate = self._is_low_confidence_fallen_candidate(feature, prediction, runtime)
        if abnormal:
            runtime.abnormal_frames += 1
        else:
            runtime.abnormal_frames = max(0, runtime.abnormal_frames - 1)
        if low_confidence_fallen_candidate:
            runtime.low_confidence_candidate_frames += 1
        else:
            runtime.low_confidence_candidate_frames = max(0, runtime.low_confidence_candidate_frames - 1)

        if runtime.state == FallState.NORMAL:
            if strong_falling_evidence:
                runtime.state = FallState.FALLING
                runtime.falling_seen = True
            elif self._low_confidence_candidate_ready(runtime):
                runtime.state = FallState.FALLEN_CANDIDATE
                runtime.falling_seen = True
                runtime.candidate_started_at = now
                runtime.confirm_frames = 1
            elif runtime.abnormal_frames >= self.settings.unstable_frame_threshold:
                runtime.state = FallState.UNSTABLE
        elif runtime.state == FallState.UNSTABLE:
            if strong_falling_evidence:
                runtime.state = FallState.FALLING
                runtime.falling_seen = True
            elif self._low_confidence_candidate_ready(runtime):
                runtime.state = FallState.FALLEN_CANDIDATE
                runtime.falling_seen = True
                runtime.candidate_started_at = now
                runtime.confirm_frames = 1
            elif runtime.abnormal_frames == 0:
                runtime.state = FallState.NORMAL
        elif runtime.state == FallState.FALLING:
            runtime.falling_seen = True
            if self._is_fallen_candidate(feature, prediction, runtime):
                runtime.state = FallState.FALLEN_CANDIDATE
                runtime.candidate_started_at = now
                runtime.confirm_frames = 1
            elif prediction.fall_probability < self.settings.falling_prob_threshold * 0.55:
                runtime.state = FallState.UNSTABLE
        elif runtime.state == FallState.FALLEN_CANDIDATE:
            if self._is_fallen_candidate(feature, prediction, runtime):
                runtime.confirm_frames += 1
            elif self._low_confidence_candidate_ready(runtime):
                runtime.confirm_frames += 1
            else:
                runtime.confirm_frames = max(0, runtime.confirm_frames - 1)
            still_ms = (
                (now - runtime.candidate_started_at) * 1000
                if runtime.candidate_started_at is not None
                else 0.0
            )
            if (
                runtime.confirm_frames >= self.settings.fall_confirm_frames
                and still_ms >= self.settings.fall_still_ms
            ):
                runtime.state = FallState.FALLEN_CONFIRMED
        elif runtime.state == FallState.FALLEN_CONFIRMED:
            runtime.state = FallState.COOLDOWN
            runtime.cooldown_until = now + self.settings.cooldown_seconds

        decision = self._decision(runtime, now)
        return decision.model_copy(
            update=self._debug_fields(
                runtime=runtime,
                feature=feature,
                prediction=prediction,
                now=now,
                v6_scores=v6_scores,
            )
        )

    def clear(self, key: str) -> None:
        self._states.pop(key, None)

    def status(self, key: str) -> FallDecision:
        runtime = self._states.get(key, _FallRuntime())
        return self._decision(runtime, time.monotonic())

    @staticmethod
    def _reset_runtime(runtime: _FallRuntime) -> None:
        runtime.state = FallState.NORMAL
        runtime.abnormal_frames = 0
        runtime.confirm_frames = 0
        runtime.candidate_started_at = None
        runtime.cooldown_until = None
        runtime.falling_seen = False
        runtime.recent_rapid_descent = False
        runtime.rapid_descent_seen_at = None
        runtime.low_confidence_candidate_frames = 0
        runtime.slow_candidate_started_at = None
        runtime.fall_latched = False

    def _decision(self, runtime: _FallRuntime, now: float) -> FallDecision:
        countdown_ms = 0
        if runtime.state == FallState.COOLDOWN and runtime.cooldown_until is not None:
            countdown_ms = max(0, int((runtime.cooldown_until - now) * 1000))
        elif runtime.state == FallState.FALLEN_CANDIDATE and runtime.candidate_started_at is not None:
            elapsed_ms = int((now - runtime.candidate_started_at) * 1000)
            countdown_ms = max(0, int(self.settings.fall_still_ms - elapsed_ms))

        return FallDecision(
            fall_state=runtime.state.value,
            risk_level=self._risk_for(runtime.state).value,
            countdown_ms=countdown_ms,
        )

    def _debug_fields(
        self,
        *,
        runtime: _FallRuntime,
        feature: TargetFeature,
        prediction: SequencePrediction,
        now: float,
        v6_scores: TemporalV6Scores | None = None,
    ) -> dict[str, object]:
        candidate_duration_ms = 0
        if runtime.candidate_started_at is not None:
            candidate_duration_ms = max(0, int((now - runtime.candidate_started_at) * 1000))

        low_by_bbox = feature.aspect_ratio >= 0.95
        low_by_pose = (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        )
        low_posture = low_by_bbox or low_by_pose
        stillness = feature.speed < 28
        rejected_reason = self._rejected_reason(
            runtime=runtime,
            feature=feature,
            prediction=prediction,
            low_posture=low_posture,
            stillness=stillness,
            candidate_duration_ms=candidate_duration_ms,
        )

        payload: dict[str, object] = {
            "fall_probability": prediction.fall_probability,
            "low_posture": low_posture,
            "stillness": stillness,
            "body_angle": feature.torso_angle,
            "bbox_aspect_ratio": feature.aspect_ratio,
            "velocity_y": feature.velocity_y,
            "candidate_duration_ms": candidate_duration_ms,
            "confirm_duration_ms": candidate_duration_ms,
            "confirm_frames": runtime.confirm_frames,
            "rejected_reason": rejected_reason,
            "debug_reason": rejected_reason,
        }
        if v6_scores is not None:
            payload.update(
                {
                    "motion_path": "legacy_shadow",
                    "fall_evidence_score": v6_scores.fall.fall_evidence_score,
                    "adl_suppression_score": v6_scores.adl.adl_suppression_score,
                    "suppressed_by_adl": False,
                    "uncertain_review": False,
                    "fall_latched": runtime.fall_latched,
                    "decision_reason": [*v6_scores.fall.reasons, *v6_scores.adl.reasons],
                }
            )
        return payload

    def _update_v6(
        self,
        *,
        runtime: _FallRuntime,
        feature: TargetFeature,
        prediction: SequencePrediction,
        scores: TemporalV6Scores,
        now: float,
    ) -> FallDecision:
        if self._v6_recovery(scores):
            runtime.state = FallState.NORMAL
            runtime.confirm_frames = 0
            runtime.candidate_started_at = None
            runtime.slow_candidate_started_at = None
            runtime.falling_seen = False
            runtime.fall_latched = False
            return self._v6_decision(runtime, feature, prediction, scores, now, "recovery_observed", "recovery_observed")

        if scores.motion.track_quality_score < self.settings.uncertain_track_quality_min:
            runtime.confirm_frames = 0
            return self._v6_decision(runtime, feature, prediction, scores, now, "uncertain_review", "track_quality_too_low", uncertain=True)

        if self._v6_adl_suppressed(scores):
            runtime.confirm_frames = 0
            runtime.candidate_started_at = None
            runtime.slow_candidate_started_at = None
            runtime.state = FallState.UNSTABLE if scores.fall.fall_evidence_score >= 0.55 else FallState.NORMAL
            return self._v6_decision(runtime, feature, prediction, scores, now, "adl_suppressed", "adl_suppression", suppressed=True)

        if self._v6_fast_candidate(scores):
            if self._v6_fast_hold(scores) or self._v6_fast_grounded_hold(scores):
                runtime.state = FallState.FALLEN_CANDIDATE
                runtime.falling_seen = True
                runtime.candidate_started_at = runtime.candidate_started_at or now
                runtime.confirm_frames += 1
                if self._v6_fast_confirm(runtime, scores, now):
                    return self._confirm_v6(runtime, feature, prediction, scores, now, "fast_fall_path")
            elif runtime.state not in {FallState.FALLING, FallState.FALLEN_CANDIDATE}:
                runtime.state = FallState.FALLING
                runtime.falling_seen = True
                runtime.candidate_started_at = None
                runtime.confirm_frames = 0
            return self._v6_decision(runtime, feature, prediction, scores, now, "fast_fall_path", "awaiting_fast_confirm")

        if self.settings.slow_fall_enabled and self._v6_slow_candidate(scores):
            runtime.state = FallState.FALLEN_CANDIDATE
            runtime.falling_seen = True
            runtime.slow_candidate_started_at = runtime.slow_candidate_started_at or now
            runtime.candidate_started_at = runtime.candidate_started_at or now
            runtime.confirm_frames += 1
            if self._v6_slow_confirm(runtime, scores, now):
                return self._confirm_v6(runtime, feature, prediction, scores, now, "slow_fall_path")
            return self._v6_decision(runtime, feature, prediction, scores, now, "slow_fall_path", "awaiting_slow_low_posture_hold")

        if scores.fall.fall_evidence_score >= 0.45 or prediction.fall_probability >= 0.45:
            runtime.state = FallState.UNSTABLE
            runtime.confirm_frames = max(0, runtime.confirm_frames - 1)
            return self._v6_decision(runtime, feature, prediction, scores, now, "motion_observe", "monitoring_motion")

        runtime.state = FallState.NORMAL
        runtime.confirm_frames = 0
        runtime.candidate_started_at = None
        runtime.slow_candidate_started_at = None
        return self._v6_decision(runtime, feature, prediction, scores, now, "normal", "low_fall_evidence")

    def _confirm_v6(
        self,
        runtime: _FallRuntime,
        feature: TargetFeature,
        prediction: SequencePrediction,
        scores: TemporalV6Scores,
        now: float,
        motion_path: str,
    ) -> FallDecision:
        if runtime.fall_latched:
            return self._v6_decision(runtime, feature, prediction, scores, now, motion_path, "fall_latched")
        runtime.state = FallState.FALLEN_CONFIRMED
        runtime.fall_latched = True
        runtime.fall_session_id += 1
        return self._v6_decision(runtime, feature, prediction, scores, now, motion_path, None)

    def _v6_decision(
        self,
        runtime: _FallRuntime,
        feature: TargetFeature,
        prediction: SequencePrediction,
        scores: TemporalV6Scores,
        now: float,
        motion_path: str,
        rejected_reason: str | None,
        *,
        suppressed: bool = False,
        uncertain: bool = False,
    ) -> FallDecision:
        decision = self._decision(runtime, now)
        debug = self._debug_fields(runtime=runtime, feature=feature, prediction=prediction, now=now, v6_scores=scores)
        debug.update(
            {
                "motion_path": motion_path,
                "rejected_reason": rejected_reason,
                "debug_reason": rejected_reason,
                "suppressed_by_adl": suppressed,
                "uncertain_review": uncertain,
                "fall_latched": runtime.fall_latched,
                "decision_reason": self._v6_reasons(scores, rejected_reason),
            }
        )
        return decision.model_copy(update=debug)

    def _with_v6_debug(
        self,
        decision: FallDecision,
        runtime: _FallRuntime,
        scores: TemporalV6Scores | None,
        reason: str,
    ) -> FallDecision:
        if scores is None:
            return decision
        return decision.model_copy(
            update={
                "motion_path": reason,
                "fall_evidence_score": scores.fall.fall_evidence_score,
                "adl_suppression_score": scores.adl.adl_suppression_score,
                "fall_latched": runtime.fall_latched,
                "decision_reason": self._v6_reasons(scores, reason),
                "rejected_reason": reason,
                "debug_reason": reason,
            }
        )

    def _v6_recovery(self, scores: TemporalV6Scores) -> bool:
        return scores.adl.recovery_score >= self.settings.recovery_cancel_threshold

    def _v6_adl_suppressed(self, scores: TemporalV6Scores) -> bool:
        return (
            scores.adl.adl_suppression_score >= self.settings.adl_suppression_block_threshold
            and scores.fall.impact_proxy_score < 0.55
            and scores.fall.fall_evidence_score < 0.80
        )

    def _v6_fast_candidate(self, scores: TemporalV6Scores) -> bool:
        standard_candidate = (
            scores.fall.fall_evidence_score >= 0.65
            and scores.fall.vertical_drop_score >= 0.50
            and scores.adl.adl_suppression_score < 0.60
            and scores.motion.track_quality_score >= self.settings.track_quality_min_confirm
        )
        return (
            standard_candidate
            or self._v6_risk_zone_medium_grounded_hold(scores)
            or self._v6_risk_zone_vertical_impact_drop(scores)
        )

    @staticmethod
    def _v6_fast_hold(scores: TemporalV6Scores) -> bool:
        return scores.fall.low_posture_score >= 0.60 and scores.fall.post_fall_stillness_score >= 0.45

    @staticmethod
    def _v6_fast_grounded_hold(scores: TemporalV6Scores) -> bool:
        standard_grounded = (
            scores.fall.low_posture_score >= 0.85
            and scores.motion.low_posture_duration_ms >= 600
            and scores.fall.floor_contact_score >= 0.45
            and scores.fall.impact_proxy_score >= 0.55
            and scores.adl.recovery_score < 0.30
        )
        risk_zone_relaxed_contact = (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.80
            and scores.fall.vertical_drop_score >= 0.85
            and scores.fall.low_posture_score >= 0.90
            and scores.motion.low_posture_duration_ms >= 600
            and scores.fall.floor_contact_score >= 0.32
            and scores.fall.impact_proxy_score >= 0.70
            and scores.adl.recovery_score < 0.30
        )
        risk_zone_short_impact = (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.80
            and scores.fall.vertical_drop_score >= 0.95
            and scores.fall.low_posture_score >= 0.90
            and scores.motion.low_posture_duration_ms >= 300
            and scores.fall.floor_contact_score >= 0.38
            and scores.fall.impact_proxy_score >= 0.80
            and scores.adl.recovery_score < 0.30
        )
        return (
            standard_grounded
            or risk_zone_relaxed_contact
            or risk_zone_short_impact
            or FallStateMachine._v6_risk_zone_short_window_hold(scores)
            or FallStateMachine._v6_risk_zone_single_frame_impact(scores)
            or FallStateMachine._v6_risk_zone_short_observation_grounded(scores)
            or FallStateMachine._v6_risk_zone_partial_grounded_drop(scores)
            or FallStateMachine._v6_risk_zone_medium_grounded_hold(scores)
            or FallStateMachine._v6_risk_zone_vertical_impact_drop(scores)
        )

    @staticmethod
    def _v6_risk_zone_short_window_hold(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.78
            and scores.fall.vertical_drop_score >= 0.95
            and scores.fall.low_posture_score >= 0.95
            and scores.motion.low_posture_duration_ms >= 600
            and scores.fall.floor_contact_score >= 0.38
            and scores.fall.impact_proxy_score >= 0.70
            and scores.adl.adl_suppression_score < 0.35
            and scores.adl.support_surface_score < 0.20
            and scores.adl.recovery_score < 0.30
        )

    @staticmethod
    def _v6_risk_zone_single_frame_impact(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.80
            and scores.fall.vertical_drop_score >= 0.98
            and scores.fall.low_posture_score >= 0.98
            and scores.fall.floor_contact_score >= 0.48
            and scores.fall.impact_proxy_score >= 0.65
            and scores.adl.adl_suppression_score < 0.45
            and scores.adl.support_surface_score < 0.05
            and scores.adl.recovery_score < 0.30
            and scores.motion.track_quality_score >= 0.85
        )

    @staticmethod
    def _v6_risk_zone_short_observation_grounded(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.70
            and scores.fall.vertical_drop_score >= 0.68
            and scores.fall.low_posture_score >= 0.98
            and scores.fall.floor_contact_score >= 0.45
            and scores.fall.impact_proxy_score >= 0.54
            and scores.adl.adl_suppression_score < 0.50
            and scores.adl.support_surface_score < 0.05
            and scores.adl.recovery_score < 0.30
            and scores.motion.track_quality_score >= 0.75
        )

    @staticmethod
    def _v6_risk_zone_partial_grounded_drop(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.67
            and scores.fall.vertical_drop_score >= 0.94
            and scores.fall.low_posture_score >= 0.58
            and scores.fall.floor_contact_score >= 0.37
            and scores.fall.impact_proxy_score >= 0.62
            and scores.adl.adl_suppression_score < 0.25
            and scores.adl.support_surface_score < 0.16
            and scores.adl.recovery_score < 0.10
            and scores.motion.track_quality_score >= 0.84
        )

    @staticmethod
    def _v6_risk_zone_medium_grounded_hold(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.56
            and scores.fall.vertical_drop_score >= 0.58
            and scores.fall.low_posture_score >= 0.49
            and scores.fall.floor_contact_score >= 0.41
            and scores.fall.impact_proxy_score >= 0.43
            and scores.motion.low_posture_duration_ms >= 600
            and scores.adl.adl_suppression_score < 0.28
            and scores.adl.support_surface_score < 0.20
            and scores.adl.recovery_score < 0.10
            and scores.motion.track_quality_score >= 0.79
        )

    @staticmethod
    def _v6_risk_zone_vertical_impact_drop(scores: TemporalV6Scores) -> bool:
        return (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.49
            and scores.fall.vertical_drop_score >= 0.99
            and scores.fall.low_posture_score <= 0.08
            and scores.fall.floor_contact_score >= 0.34
            and scores.fall.impact_proxy_score >= 0.58
            and scores.adl.adl_suppression_score < 0.27
            and scores.adl.support_surface_score <= 0.35
            and scores.adl.recovery_score < 0.10
            and scores.motion.track_quality_score >= 0.86
        )

    def _v6_fast_confirm(self, runtime: _FallRuntime, scores: TemporalV6Scores, now: float) -> bool:
        hold_ms = max(self._candidate_ms(runtime, now), scores.motion.low_posture_duration_ms)
        strong_single_observation = (
            scores.fall.fall_evidence_score >= 0.80
            and scores.fall.vertical_drop_score >= 0.75
            and scores.fall.low_posture_score >= 0.85
            and scores.fall.post_fall_stillness_score >= 0.65
            and scores.fall.floor_contact_score >= 0.45
            and scores.adl.adl_suppression_score < self.settings.adl_suppression_confirm_max
            and scores.adl.recovery_score < 0.30
        )
        strong_grounded_observation = (
            scores.fall.fall_evidence_score >= 0.80
            and scores.fall.vertical_drop_score >= 0.75
            and self._v6_fast_grounded_hold(scores)
            and scores.adl.adl_suppression_score < self.settings.adl_suppression_confirm_max
        )
        risk_zone_short_window_observation = self._v6_risk_zone_short_window_hold(scores)
        risk_zone_single_frame_observation = self._v6_risk_zone_single_frame_impact(scores)
        risk_zone_short_observation_grounded = self._v6_risk_zone_short_observation_grounded(scores)
        risk_zone_partial_grounded_drop = self._v6_risk_zone_partial_grounded_drop(scores)
        risk_zone_medium_grounded_hold = self._v6_risk_zone_medium_grounded_hold(scores)
        risk_zone_vertical_impact_drop = self._v6_risk_zone_vertical_impact_drop(scores)
        required_hold_ms = self.settings.fall_still_ms
        if (
            risk_zone_single_frame_observation
            or risk_zone_short_observation_grounded
            or risk_zone_partial_grounded_drop
            or risk_zone_medium_grounded_hold
            or risk_zone_vertical_impact_drop
        ):
            required_hold_ms = 0
        elif strong_single_observation or strong_grounded_observation or risk_zone_short_window_observation:
            required_hold_ms = min(required_hold_ms, max(600, int(self.settings.fall_still_ms * 0.4)))
        return (
            (
                scores.fall.fall_evidence_score >= self.settings.fall_evidence_confirm_threshold
                or risk_zone_short_observation_grounded
                or risk_zone_partial_grounded_drop
                or risk_zone_medium_grounded_hold
                or risk_zone_vertical_impact_drop
            )
            and (
                scores.adl.adl_suppression_score < self.settings.adl_suppression_confirm_max
                or risk_zone_short_observation_grounded
            )
            and hold_ms >= required_hold_ms
            and (
                runtime.confirm_frames >= self.settings.fall_confirm_frames
                or strong_single_observation
                or strong_grounded_observation
                or risk_zone_short_window_observation
                or risk_zone_single_frame_observation
                or risk_zone_short_observation_grounded
                or risk_zone_partial_grounded_drop
                or risk_zone_medium_grounded_hold
                or risk_zone_vertical_impact_drop
            )
            and scores.adl.recovery_score < 0.40
            and scores.motion.track_quality_score >= self.settings.track_quality_min_confirm
        )

    def _v6_slow_candidate(self, scores: TemporalV6Scores) -> bool:
        return (
            scores.motion.continuous_descent_score >= 0.45
            and scores.fall.low_posture_score >= 0.55
            and scores.adl.recovery_score < 0.35
            and scores.adl.adl_suppression_score < 0.65
            and scores.motion.track_quality_score >= self.settings.track_quality_min_confirm
        )

    def _v6_slow_confirm(self, runtime: _FallRuntime, scores: TemporalV6Scores, now: float) -> bool:
        hold_ms = max(self._candidate_ms(runtime, now), scores.motion.low_posture_duration_ms)
        standard_slow_confirm = (
            hold_ms >= self.settings.slow_fall_hold_ms
            and scores.adl.recovery_score < 0.30
            and scores.adl.support_surface_score < self.settings.slow_fall_support_surface_max
            and scores.fall.floor_contact_score >= self.settings.slow_fall_floor_contact_min
            and scores.motion.track_quality_score >= self.settings.track_quality_min_confirm
            and scores.adl.adl_suppression_score < self.settings.adl_suppression_slow_max
        )
        short_clip_slow_confirm = (
            scores.scene.floor_risk_score >= 0.80
            and scores.fall.fall_evidence_score >= 0.55
            and scores.fall.vertical_drop_score >= 0.70
            and scores.fall.low_posture_score >= 0.95
            and hold_ms >= 900
            and scores.fall.floor_contact_score >= 0.30
            and scores.fall.impact_proxy_score >= 0.70
            and scores.fall.post_fall_stillness_score >= 0.75
            and scores.adl.adl_suppression_score < 0.40
            and scores.adl.support_surface_score < 0.20
            and scores.adl.recovery_score < 0.30
            and scores.motion.track_quality_score >= self.settings.track_quality_min_confirm
        )
        return standard_slow_confirm or short_clip_slow_confirm

    @staticmethod
    def _candidate_ms(runtime: _FallRuntime, now: float) -> int:
        started = runtime.candidate_started_at or runtime.slow_candidate_started_at
        if started is None:
            return 0
        return max(0, int((now - started) * 1000))

    @staticmethod
    def _v6_reasons(scores: TemporalV6Scores, rejected_reason: str | None) -> list[str]:
        reasons = [*scores.fall.reasons, *scores.adl.reasons]
        if rejected_reason:
            reasons.append(rejected_reason)
        return list(dict.fromkeys(reasons))

    def _rejected_reason(
        self,
        *,
        runtime: _FallRuntime,
        feature: TargetFeature,
        prediction: SequencePrediction,
        low_posture: bool,
        stillness: bool,
        candidate_duration_ms: int,
    ) -> str | None:
        if runtime.state == FallState.FALLEN_CONFIRMED:
            return None
        if runtime.state == FallState.COOLDOWN:
            return "cooldown_active"
        if runtime.state == FallState.FALLEN_CANDIDATE:
            if prediction.fall_probability < self.settings.falling_prob_threshold:
                return "low_fall_probability"
            if not runtime.recent_rapid_descent and not self._has_rapid_descent(feature):
                return "no_recent_rapid_descent"
            if not low_posture:
                return "not_low_posture"
            if not stillness:
                return "moving_too_fast"
            need_frames = runtime.confirm_frames < self.settings.fall_confirm_frames
            need_duration = candidate_duration_ms < self.settings.fall_still_ms
            if need_frames and need_duration:
                return "awaiting_confirm_frames_and_duration"
            if need_frames:
                return "awaiting_confirm_frames"
            if need_duration:
                return "awaiting_confirm_duration"
            return None
        if runtime.state == FallState.FALLING:
            if prediction.fall_probability < self.settings.falling_prob_threshold:
                return "low_fall_probability"
            if not runtime.recent_rapid_descent and not self._has_rapid_descent(feature):
                return "no_recent_rapid_descent"
            if not low_posture:
                return "not_low_posture"
            if not stillness:
                return "moving_too_fast"
            return "awaiting_fallen_candidate"
        if runtime.state == FallState.UNSTABLE:
            if runtime.abnormal_frames < self.settings.unstable_frame_threshold:
                return "awaiting_abnormal_frames"
            if prediction.fall_probability < self.settings.falling_prob_threshold:
                return "low_fall_probability"
            if not low_posture and feature.delta_y < 35:
                return "insufficient_low_posture_or_descent"
            return "monitoring_instability"

        if self._low_confidence_candidate_ready(runtime):
            return "awaiting_fallen_candidate"
        if runtime.abnormal_frames > 0 and runtime.abnormal_frames < self.settings.unstable_frame_threshold:
            return "awaiting_abnormal_frames"
        if prediction.fall_probability < self.settings.falling_prob_threshold:
            return "low_fall_probability"
        if not low_posture and feature.delta_y < 35:
            return "insufficient_low_posture_or_descent"
        if not runtime.recent_rapid_descent and not self._has_rapid_descent(feature):
            return "no_recent_rapid_descent"
        return "monitoring_normal"

    @staticmethod
    def _risk_for(state: FallState) -> RiskLevel:
        mapping = {
            FallState.NORMAL: RiskLevel.LOW,
            FallState.UNSTABLE: RiskLevel.MEDIUM,
            FallState.FALLING: RiskLevel.HIGH,
            FallState.FALLEN_CANDIDATE: RiskLevel.HIGH,
            FallState.FALLEN_CONFIRMED: RiskLevel.CRITICAL,
            FallState.COOLDOWN: RiskLevel.COOLDOWN,
        }
        return mapping[state]

    def _is_abnormal(self, feature: TargetFeature, prediction: SequencePrediction) -> bool:
        posture_evidence = self._has_posture_evidence(feature)
        return (
            self._is_strong_falling_evidence(feature, prediction)
            or (prediction.fall_probability >= 0.5 and feature.delta_y > 55)
            or (prediction.fall_probability >= 0.5 and posture_evidence)
        )

    @staticmethod
    def _has_posture_evidence(feature: TargetFeature) -> bool:
        return feature.aspect_ratio >= 0.95 or (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        )

    def _is_strong_falling_evidence(
        self,
        feature: TargetFeature,
        prediction: SequencePrediction,
    ) -> bool:
        if prediction.fall_probability < self.settings.falling_prob_threshold:
            return False
        return (
            feature.delta_y >= 52
            or (feature.pose_available and feature.delta_y >= 35)
            or self._has_posture_evidence(feature)
        )

    @staticmethod
    def _has_rapid_descent(feature: TargetFeature) -> bool:
        return feature.delta_y > 40

    def _is_fallen_candidate(
        self,
        feature: TargetFeature,
        prediction: SequencePrediction,
        runtime: _FallRuntime,
    ) -> bool:
        if not runtime.falling_seen:
            return False
        if not runtime.recent_rapid_descent and not self._has_rapid_descent(feature):
            return False
        if prediction.fall_probability < self.settings.falling_prob_threshold:
            return False

        low_by_bbox = feature.aspect_ratio >= 0.95
        low_by_pose = (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        )
        still = feature.speed < 28
        return still and (low_by_bbox or low_by_pose)

    def _is_low_confidence_fallen_candidate(
        self,
        feature: TargetFeature,
        prediction: SequencePrediction,
        runtime: _FallRuntime,
    ) -> bool:
        if not self.settings.low_confidence_fallen_candidate_enabled:
            return False
        if prediction.window_size is not None and prediction.window_size < self.settings.low_confidence_fallen_candidate_min_window:
            return False
        if feature.object_confidence > self.settings.low_confidence_fallen_candidate_max_confidence:
            return False
        if prediction.fall_probability < self.settings.low_confidence_fallen_candidate_min_probability:
            return False
        low_by_bbox = feature.aspect_ratio >= 1.15
        low_by_pose = (
            feature.head_height_ratio is not None
            and feature.head_height_ratio > 0.45
            and feature.hip_height_ratio is not None
            and feature.hip_height_ratio > 0.65
        )
        if not (low_by_bbox or low_by_pose):
            return False
        return feature.speed < 22 or runtime.low_confidence_candidate_frames > 0

    def _low_confidence_candidate_ready(self, runtime: _FallRuntime) -> bool:
        return runtime.low_confidence_candidate_frames >= self.settings.unstable_frame_threshold
