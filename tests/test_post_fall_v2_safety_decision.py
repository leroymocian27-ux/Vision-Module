from __future__ import annotations

from dataclasses import replace

import pytest

from app.post_fall_v2.safety_decision import evaluate_fall_safety
from app.post_fall_v2.schemas import FallDetailResult, FallEvent


def test_visible_transition_produces_high_confidence_alert() -> None:
    event = _event(_detail("confirmed_fall", high_risk_fall=1, fall_transition_visible=True))

    decision = _evaluate(event, elapsed_ms=2500)

    assert decision.outcome == "alert"
    assert decision.path == "transition_fall"
    assert decision.alert_level == "high"


def test_high_risk_confirmed_fall_is_the_only_emergency_alert_gate() -> None:
    event = _event(
        _detail(
            "confirmed_fall",
            high_risk_fall=1,
            scene_type="fall",
            recommended_action="emergency_alert",
            fall_transition_visible=True,
        )
    )

    decision = _evaluate(event, elapsed_ms=2500)

    assert decision.outcome == "alert"
    assert decision.alert_level == "high"


@pytest.mark.parametrize("verdict", ["normal_activity", "intentional_low_posture"])
def test_explicit_non_fall_is_the_only_semantic_veto(verdict: str) -> None:
    event = _event(
        _detail(
            verdict,
            activity="正常行走" if verdict == "normal_activity" else "主动躺卧阅读",
            posture_state="upright" if verdict == "normal_activity" else "lying",
            intentional_action_evidence=verdict == "intentional_low_posture",
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "dismiss"
    assert decision.path == "explicit_non_fall"


def test_unclear_result_continues_observation_before_threshold() -> None:
    event = _event(_detail("unclear", persistent_ground_state="observed"))

    decision = _evaluate(event, elapsed_ms=9000)

    assert decision.outcome == "observe"
    assert decision.review_required is True


def test_conflicting_transition_and_intentional_evidence_requires_review() -> None:
    event = _event(
        _detail(
            "confirmed_fall",
            fall_transition_visible=True,
            intentional_action_evidence=True,
        )
    )

    decision = _evaluate(event, elapsed_ms=15000)

    assert decision.outcome == "observe"
    assert decision.reason == "semantic_review_conflicting_transition_and_intentional_evidence"
    assert decision.review_required is True


def test_pending_semantic_review_prevents_premature_post_fall_alert() -> None:
    event = _event(_detail("unclear", analysis_status="running"))

    decision = evaluate_fall_safety(
        event,
        binary_state="EVENT_ACTIVE",
        observation_elapsed_ms=15000,
        post_fall_alert_min_ms=10000,
        followup_complete=False,
    )

    assert decision.outcome == "observe"
    assert decision.reason == "awaiting_post_fall_followup_review"


def test_persistent_abnormality_with_completed_visual_evidence_stays_observe_without_high_risk_gate() -> None:
    detail = _detail(
        "unclear",
        posture_state="ground_low",
        persistent_ground_state="observed",
        recovery_observed=False,
    )
    event = _event(detail)

    decision = _evaluate(event, elapsed_ms=10000)

    assert decision.outcome == "observe"
    assert decision.path == "uncertain_evidence"
    assert decision.alert_level == "none"
    assert decision.review_required is True


@pytest.mark.parametrize("status", ["failed", "timeout"])
def test_failed_semantic_review_without_valid_visual_evidence_stays_observe(status: str) -> None:
    event = _event(
        _detail(
            "unclear",
            analysis_status=status,
            posture_state="ground_low",
            persistent_ground_state="observed",
            recovery_observed=False,
        )
    )

    decision = _evaluate(event, elapsed_ms=15000)

    assert decision.outcome == "observe"
    assert decision.path == "uncertain_evidence"


def test_insufficient_visual_evidence_stays_observe_after_threshold() -> None:
    event = _event(
        _detail(
            "insufficient_visual_evidence",
            posture_state="unknown",
            persistent_ground_state="insufficient_visual_evidence",
        )
    )

    decision = _evaluate(event, elapsed_ms=15000)

    assert decision.outcome == "observe"


def test_confirmed_verdict_without_visible_transition_is_not_transition_alert() -> None:
    event = _event(_detail("confirmed_fall", fall_transition_visible=False))

    decision = _evaluate(event, elapsed_ms=2000)

    assert decision.outcome == "observe"
    assert decision.path == "uncertain_evidence"


def test_high_risk_confirmed_post_fall_state_alerts_without_visible_transition() -> None:
    event = _event(
        _detail(
            "confirmed_fall",
            high_risk_fall=1,
            scene_type="fall",
            recommended_action="emergency_alert",
            fall_transition_visible=False,
            posture_state="ground_low",
            persistent_ground_state="observed",
            intentional_action_evidence=False,
            recovery_observed=False,
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "alert"
    assert decision.path == "post_fall_abnormality"
    assert decision.reason == "qwen_high_risk_confirmed_fall"


def test_low_posture_reading_does_not_alert() -> None:
    event = _event(
        _detail(
            "non_fall",
            high_risk_fall=0,
            scene_type="intentional_low_posture",
            recommended_action="no_alert",
            activity="主动低姿态看书",
            posture_state="lying",
            intentional_action_evidence=True,
            fall_transition_visible=False,
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "dismiss"
    assert decision.path == "explicit_non_fall"


def test_seated_rest_does_not_alert() -> None:
    event = _event(
        _detail(
            "non_fall",
            high_risk_fall=0,
            scene_type="seated_rest",
            recommended_action="no_alert",
            activity="坐在椅子上休息",
            posture_state="seated",
            intentional_action_evidence=True,
            fall_transition_visible=False,
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "dismiss"
    assert decision.path == "explicit_non_fall"


def test_manual_review_recommendation_does_not_alert_without_high_risk_gate() -> None:
    event = _event(
        _detail(
            "non_fall",
            high_risk_fall=0,
            scene_type="seated_rest",
            recommended_action="manual_review",
            activity="坐在椅子上休息",
            posture_state="seated",
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "dismiss"
    assert decision.path == "explicit_non_fall"


def test_confirmed_fall_with_high_risk_zero_does_not_alert() -> None:
    event = _event(_detail("confirmed_fall", high_risk_fall=0, fall_transition_visible=True))

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "observe"
    assert decision.reason == "confirmed_fall_without_high_risk_gate"


def test_high_risk_one_with_non_fall_verdict_does_not_alert() -> None:
    event = _event(
        _detail(
            "non_fall",
            high_risk_fall=1,
            scene_type="seated_rest",
            recommended_action="emergency_alert",
            activity="坐在椅子上休息",
            posture_state="seated",
        )
    )

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "observe"
    assert decision.path == "uncertain_evidence"


def test_missing_high_risk_field_defaults_to_no_alert() -> None:
    event = _event(_detail("confirmed_fall", fall_transition_visible=True))

    decision = _evaluate(event, elapsed_ms=30000)

    assert decision.outcome == "observe"
    assert decision.reason == "confirmed_fall_without_high_risk_gate"


def test_binary_recovery_prevents_post_fall_escalation() -> None:
    event = _event(_detail("unclear", persistent_ground_state="observed"))

    decision = evaluate_fall_safety(
        event,
        binary_state="RECOVERY_PENDING",
        observation_elapsed_ms=15000,
        post_fall_alert_min_ms=10000,
    )

    assert decision.outcome == "observe"
    assert decision.path == "uncertain_evidence"


def test_observed_recovery_prevents_post_fall_escalation() -> None:
    event = _event(
        _detail(
            "unclear",
            persistent_ground_state="observed",
            recovery_observed=True,
        )
    )

    decision = _evaluate(event, elapsed_ms=15000)

    assert decision.outcome == "observe"


def _evaluate(event: FallEvent, *, elapsed_ms: int):
    return evaluate_fall_safety(
        event,
        binary_state="EVENT_ACTIVE",
        observation_elapsed_ms=elapsed_ms,
        post_fall_alert_min_ms=10000,
    )


def _event(detail: FallDetailResult) -> FallEvent:
    return FallEvent(
        incident_id="incident-1",
        camera_id="camera-01",
        state="fall_candidate",
        started_at="2026-08-28T00:00:00+00:00",
        confirmed_at="2026-08-28T00:00:01+00:00",
        binary_evidence={"candidate_duration_ms": 1000},
        vlm_status=detail.analysis_status,
        vlm_analysis=detail,
    )


def _detail(verdict: str, **updates) -> FallDetailResult:
    base = FallDetailResult(
        incident_id="incident-1",
        analysis_status="completed",
        fall_verdict=verdict,
        summary="测试语义结果",
    )
    return replace(base, **updates)
