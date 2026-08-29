from __future__ import annotations

from app.post_fall_v2.schemas import FallEvent, FallSafetyDecision


_ACTIVE_BINARY_STATES = {"EVENT_ACTIVE", "FALL_CONFIRMED"}
_GROUND_POSTURES = {"lying", "ground_low", "fallen", "on_ground"}
_NORMAL_POSTURES = {"upright", "seated"}


def evaluate_fall_safety(
    event: FallEvent,
    *,
    binary_state: str,
    observation_elapsed_ms: int,
    post_fall_alert_min_ms: int,
    followup_complete: bool = True,
) -> FallSafetyDecision:
    """Combine binary persistence and semantic evidence into a safety decision."""
    elapsed_ms = max(0, int(observation_elapsed_ms))
    detail = event.vlm_analysis
    verdict = detail.fall_verdict if detail is not None else None

    if detail is not None and detail.analysis_status == "completed":
        high_risk_fall = _is_high_risk_fall(getattr(detail, "high_risk_fall", 0))
        explicit_non_fall = (
            (
                verdict == "non_fall"
                and not high_risk_fall
                and detail.fall_transition_visible is not True
            )
            or
            (
                verdict == "normal_activity"
                and detail.posture_state in _NORMAL_POSTURES
                and detail.activity.strip().lower() not in {"", "unknown", "unclear"}
            )
            or (
                verdict == "intentional_low_posture"
                and detail.intentional_action_evidence is True
            )
        )
        transition_evidence = detail.fall_transition_visible is True
        qwen_confirmed_high_risk = verdict == "confirmed_fall" and high_risk_fall
        if transition_evidence and (explicit_non_fall or detail.intentional_action_evidence is True):
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="semantic_review_conflicting_transition_and_intentional_evidence",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
                review_required=True,
            )
        if explicit_non_fall:
            return FallSafetyDecision(
                outcome="dismiss",
                path="explicit_non_fall",
                alert_level="none",
                reason="semantic_review_explicit_non_fall",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
            )

        if qwen_confirmed_high_risk:
            path = "transition_fall" if transition_evidence else "post_fall_abnormality"
            return FallSafetyDecision(
                outcome="alert",
                path=path,
                alert_level="high",
                reason="qwen_high_risk_confirmed_fall",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
            )
        if verdict == "confirmed_fall" and not high_risk_fall:
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="confirmed_fall_without_high_risk_gate",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
                review_required=True,
            )

    binary_persisting = binary_state in _ACTIVE_BINARY_STATES
    if binary_persisting and elapsed_ms >= max(1, int(post_fall_alert_min_ms)):
        if not followup_complete:
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="awaiting_post_fall_followup_review",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
                review_required=True,
            )
        persistent_visual_evidence = bool(
            detail is not None
            and detail.analysis_status == "completed"
            and verdict == "unclear"
            and detail.posture_state in _GROUND_POSTURES
            and detail.persistent_ground_state == "observed"
            and detail.recovery_observed is not True
            and detail.intentional_action_evidence is not True
        )
        if persistent_visual_evidence:
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="persistent_visual_ground_abnormality_requires_high_risk_gate",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=verdict,
                review_required=True,
            )

    return FallSafetyDecision(
        outcome="observe",
        path="uncertain_evidence",
        alert_level="none",
        reason=_observe_reason(event, binary_persisting),
        observation_elapsed_ms=elapsed_ms,
        qwen_verdict=verdict,
        review_required=True,
    )


def _observe_reason(event: FallEvent, binary_persisting: bool) -> str:
    detail = event.vlm_analysis
    if detail is None:
        return "semantic_review_pending" if event.vlm_status != "disabled" else "semantic_review_disabled"
    if detail.analysis_status != "completed":
        return f"semantic_review_{detail.analysis_status}"
    if not binary_persisting:
        return "binary_abnormality_not_persisting"
    return "semantic_evidence_uncertain_continue_observation"


def _is_high_risk_fall(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip() == "1"
    return False
