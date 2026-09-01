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
    effective_verdict = verdict
    abnormal_ground_conflict = False

    if detail is not None and detail.analysis_status == "completed":
        compact_decision = _compact_semantic_safety(event, detail, elapsed_ms)
        if compact_decision is not None:
            return compact_decision
        high_risk_fall = _is_high_risk_fall(getattr(detail, "high_risk_fall", 0))
        abnormal_ground_conflict = bool(
            (
                detail.posture_state in _GROUND_POSTURES
                and detail.persistent_ground_state == "observed"
                and detail.recovery_observed is False
                and detail.intentional_action_evidence is not True
            )
            or (
                detail.posture_state in {"lying", "ground_low"}
                and detail.scene_type
                not in {"walking", "standing", "seated_rest", "intentional_low_posture", "intentional_lying", "squatting", "bending"}
            )
        )
        if verdict == "non_fall" and abnormal_ground_conflict:
            effective_verdict = "unclear"

        verified_normal_activity = (
            effective_verdict in {"non_fall", "normal_activity"}
            and detail.scene_type in {"walking", "standing", "seated_rest"}
            and detail.posture_state in _NORMAL_POSTURES
            and detail.fall_transition_visible is not True
            and not abnormal_ground_conflict
        )
        verified_intentional_activity = (
            effective_verdict in {"non_fall", "intentional_low_posture"}
            and detail.scene_type in {"intentional_low_posture", "intentional_lying"}
            and detail.intentional_action_evidence is True
            and detail.fall_transition_visible is not True
            and not abnormal_ground_conflict
        )
        explicit_non_fall = (
            not high_risk_fall
            and (verified_normal_activity or verified_intentional_activity)
        )
        transition_evidence = detail.fall_transition_visible is True
        qwen_confirmed_high_risk = effective_verdict == "confirmed_fall" and high_risk_fall
        if transition_evidence and (explicit_non_fall or detail.intentional_action_evidence is True):
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="semantic_review_conflicting_transition_and_intentional_evidence",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=effective_verdict,
                review_required=True,
            )
        if explicit_non_fall:
            return FallSafetyDecision(
                outcome="dismiss",
                path="explicit_non_fall",
                alert_level="none",
                reason="semantic_review_explicit_non_fall",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=effective_verdict,
            )

        if qwen_confirmed_high_risk:
            path = "transition_fall" if transition_evidence else "post_fall_abnormality"
            return FallSafetyDecision(
                outcome="alert",
                path=path,
                alert_level="high",
                reason="qwen_high_risk_confirmed_fall",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=effective_verdict,
            )
        if effective_verdict == "confirmed_fall" and not high_risk_fall:
            return FallSafetyDecision(
                outcome="observe",
                path="uncertain_evidence",
                alert_level="none",
                reason="confirmed_fall_without_high_risk_gate",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=effective_verdict,
                review_required=True,
            )

    persistent_ground_evidence = bool(
        detail is not None
        and detail.analysis_status == "completed"
        and detail.posture_state in _GROUND_POSTURES
        and detail.persistent_ground_state == "observed"
        and detail.recovery_observed is False
    )
    binary_persisting = binary_state in _ACTIVE_BINARY_STATES or persistent_ground_evidence
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
            and effective_verdict == "unclear"
            and detail.posture_state in _GROUND_POSTURES
            and detail.persistent_ground_state == "observed"
            and detail.recovery_observed is False
            and detail.intentional_action_evidence is False
            and not (
                detail.scene_type
                in {
                    "walking",
                    "standing",
                    "seated_rest",
                    "intentional_low_posture",
                    "intentional_lying",
                    "squatting",
                    "bending",
                }
                and detail.intentional_action_evidence is True
            )
        )
        if persistent_visual_evidence:
            return FallSafetyDecision(
                outcome="alert",
                path="post_fall_persistent_abnormality",
                alert_level="high",
                reason="persistent_post_fall_abnormality_without_intentional_evidence",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=effective_verdict,
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


def _compact_semantic_safety(event: FallEvent, detail, elapsed_ms: int) -> FallSafetyDecision | None:
    activity = str(getattr(detail, "activity", "") or "").strip()
    confidence = _confidence(getattr(detail, "confidence", None))
    visible_distress = str(getattr(detail, "visible_distress", "unclear") or "unclear").strip().lower()
    vlm_flag = getattr(detail, "vlm_is_true_fall", None)
    posture_state = str(getattr(detail, "posture_state", "unclear") or "unclear").strip().lower()
    persistent_strong = bool((event.binary_evidence or {}).get("persistent_strong_candidate"))
    if activity in {"confirmed_fall", "possible_fall_or_distress"}:
        return FallSafetyDecision(
            outcome="alert",
            path="transition_fall",
            alert_level="high",
            reason="compact_semantic_true_fall",
            observation_elapsed_ms=elapsed_ms,
            qwen_verdict=activity,
        )
    if activity in {"lying_using_phone", "lying_reading"}:
        if confidence is not None and confidence >= 0.80 and visible_distress == "no" and vlm_flag is False:
            return FallSafetyDecision(
                outcome="dismiss",
                path="explicit_non_fall",
                alert_level="none",
                reason="compact_semantic_explicit_non_fall",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=activity,
            )
        return None
    if activity == "normal_activity":
        if (
            confidence is not None
            and confidence >= 0.90
            and visible_distress == "no"
            and posture_state != "unclear"
            and vlm_flag is False
            and not persistent_strong
        ):
            return FallSafetyDecision(
                outcome="dismiss",
                path="explicit_non_fall",
                alert_level="none",
                reason="compact_semantic_explicit_normal_activity",
                observation_elapsed_ms=elapsed_ms,
                qwen_verdict=activity,
            )
        return None
    return None


def _confidence(value: object) -> float | None:
    try:
        if value is None:
            return None
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None
