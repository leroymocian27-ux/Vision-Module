from __future__ import annotations

from app.post_fall_v2.binary_decision_aggregator import BinaryDecisionAggregator, BinaryDecisionAggregatorConfig
from app.post_fall_v2.schemas import BinaryFrameResult


def frame(seq: int, probability: float, *, camera_id: str = "camera_01") -> BinaryFrameResult:
    return BinaryFrameResult(
        frame_id=f"{camera_id}_1_{seq:08d}",
        camera_id=camera_id,
        frame_seq=seq,
        captured_at="2026-08-12T00:00:00.000+00:00",
        inferred_at="2026-08-12T00:00:00.000+00:00",
        fall_probability=probability,
        non_fall_probability=1.0 - probability,
        raw_label="Fall" if probability >= 0.6 else "noFall",
        decision_label="FALL" if probability >= 0.6 else "NON_FALL",
        threshold=0.6,
        model_name="test",
        model_version="test",
        valid=True,
        source_width=640,
        source_height=480,
    )


def aggregator() -> BinaryDecisionAggregator:
    return BinaryDecisionAggregator(
        BinaryDecisionAggregatorConfig(
            threshold=0.6,
            window_size=8,
            min_positive_frames=4,
            min_consecutive_frames=3,
            candidate_min_ms=0,
            high_confidence_threshold=0.9,
            high_confidence_min_consecutive_frames=2,
            recovery_threshold=0.45,
            recovery_min_consecutive_frames=5,
            recovery_min_ms=1000,
            cooldown_ms=1000,
        )
    )


def immediate_aggregator() -> BinaryDecisionAggregator:
    return BinaryDecisionAggregator(
        BinaryDecisionAggregatorConfig(
            threshold=0.6,
            window_size=8,
            min_positive_frames=1,
            min_consecutive_frames=1,
            candidate_min_ms=0,
            high_confidence_threshold=0.9,
            high_confidence_min_consecutive_frames=2,
            recovery_threshold=0.45,
            recovery_min_consecutive_frames=5,
            recovery_min_ms=1000,
            cooldown_ms=1000,
        )
    )


def test_single_threshold_hit_does_not_immediately_create_candidate_event() -> None:
    agg = immediate_aggregator()
    decision = agg.update(frame(1, 0.9), now=1.0)

    assert decision.state == "NORMAL"
    assert decision.event_created is False
    assert decision.incident_id is None
    assert decision.reason == "temporal_collecting"
    assert decision.evidence.positive_count == 1
    assert decision.evidence.consecutive_positive_count == 1
    assert decision.evidence.high_conf_consecutive == 1
    assert decision.evidence.candidate_duration_ms == 0


def test_single_fall_frame_does_not_confirm() -> None:
    agg = aggregator()
    decision = agg.update(frame(1, 0.9), now=1.0)

    assert decision.state == "NORMAL"
    assert decision.event_created is False
    assert decision.incident_id is None


def test_transient_false_positive_returns_normal() -> None:
    agg = aggregator()
    agg.update(frame(1, 0.9), now=1.0)
    decision = agg.update(frame(2, 0.1), now=1.3)

    assert decision.state == "NORMAL"
    assert decision.event_created is False


def test_sustained_fall_creates_one_event_and_no_duplicate_while_lying() -> None:
    agg = aggregator()
    decisions = [agg.update(frame(seq, probability), now=float(seq)) for seq, probability in enumerate([0.30, 0.41, 0.63, 0.68, 0.72, 0.80, 0.84, 0.86, 0.88], start=1)]

    created = [item for item in decisions if item.event_created]
    assert len(created) == 1
    assert created[0].state == "EVENT_ACTIVE"
    assert created[0].reason == "normal_temporal_confirmation"
    assert decisions[-1].event_created is False
    assert decisions[-1].incident_id == created[0].incident_id


def test_recovery_cooldown_rearms_and_second_fall_creates_second_incident() -> None:
    agg = aggregator()
    first = None
    for seq, probability in enumerate([0.30, 0.41, 0.63, 0.68, 0.72, 0.80, 0.84, 0.86], start=1):
        decision = agg.update(frame(seq, probability), now=float(seq))
        if decision.event_created:
            first = decision.incident_id
    assert first is not None

    for seq, probability in enumerate([0.44, 0.42, 0.40, 0.38, 0.35], start=9):
        recovered = agg.update(frame(seq, probability), now=float(seq))
    rearmed = agg.update(frame(14, 0.1), now=14.5)
    assert rearmed.rearmed is True
    assert rearmed.state == "NORMAL"

    second = None
    for seq, probability in enumerate([0.30, 0.41, 0.63, 0.68, 0.72, 0.80, 0.84, 0.86], start=15):
        decision = agg.update(frame(seq, probability), now=float(seq))
        if decision.event_created:
            second = decision.incident_id
    assert second is not None
    assert second != first


def test_persistent_strong_candidate_uses_recent_three_frame_window() -> None:
    strong = immediate_aggregator()
    for seq, probability in enumerate([0.91, 0.87, 0.93], start=1):
        decision = strong.update(frame(seq, probability), now=float(seq))

    assert decision.evidence.probability_window == [0.91, 0.87, 0.93]
    assert decision.evidence.persistent_strong_candidate is True
    assert strong.persistent_strong_candidate("camera_01") is True

    transient = immediate_aggregator()
    for seq, probability in enumerate([0.10, 0.85, 0.12], start=1):
        decision = transient.update(frame(seq, probability), now=float(seq))

    assert decision.evidence.probability_window == [0.1, 0.85, 0.12]
    assert decision.evidence.persistent_strong_candidate is False
    assert transient.persistent_strong_candidate("camera_01") is False


def run_sequence(probabilities: list[float]) -> list:
    agg = aggregator()
    return [agg.update(frame(seq, probability), now=float(seq)) for seq, probability in enumerate(probabilities, start=1)]


def test_case_1_single_frame_false_positive_does_not_trigger_candidate() -> None:
    decisions = run_sequence([0.20, 0.31, 0.68, 0.24, 0.29, 0.33, 0.21, 0.19])

    assert all(not decision.event_created for decision in decisions)
    assert decisions[-1].state == "NORMAL"


def test_case_2_threshold_jitter_does_not_trigger_candidate() -> None:
    decisions = run_sequence([0.58, 0.61, 0.57, 0.62, 0.59, 0.63, 0.55, 0.58])

    assert all(not decision.event_created for decision in decisions)
    assert decisions[-1].evidence.positive_count == 3
    assert decisions[-1].evidence.tail_consecutive_positive == 0


def test_case_3_sustained_fall_triggers_normal_candidate() -> None:
    decisions = run_sequence([0.30, 0.41, 0.63, 0.68, 0.72, 0.80, 0.84, 0.86])
    created = [decision for decision in decisions if decision.event_created]

    assert len(created) == 1
    assert created[0].evidence.normal_candidate_condition is True
    assert created[0].evidence.high_conf_candidate_condition is False
    assert created[0].evidence.trigger_reason == "normal_temporal_confirmation"
    assert created[0].reason == "normal_temporal_confirmation"


def test_case_4_high_confidence_fast_path_triggers_after_two_frames() -> None:
    decisions = run_sequence([0.30, 0.42, 0.95, 0.97])
    created = [decision for decision in decisions if decision.event_created]

    assert len(created) == 1
    assert created[0].frame_seq == 4
    assert created[0].evidence.high_conf_consecutive == 2
    assert created[0].evidence.trigger_reason == "high_confidence_fast_path"
    assert created[0].reason == "high_confidence_fast_path"


def test_case_5_single_high_confidence_frame_does_not_trigger_candidate() -> None:
    decisions = run_sequence([0.22, 0.96, 0.31])

    assert all(not decision.event_created for decision in decisions)
    assert decisions[1].evidence.high_conf_consecutive == 1


def test_case_6_recovery_requires_five_frames_below_recovery_threshold() -> None:
    agg = aggregator()
    for seq, probability in enumerate([0.30, 0.41, 0.63, 0.68, 0.72, 0.80, 0.84, 0.86], start=1):
        created = agg.update(frame(seq, probability), now=float(seq))
    assert created.event_created is True

    recovery_decisions = [
        agg.update(frame(seq, probability), now=float(seq))
        for seq, probability in enumerate([0.55, 0.51, 0.47, 0.44, 0.42, 0.40, 0.38, 0.35], start=9)
    ]

    assert recovery_decisions[0].evidence.candidate_active is True
    assert recovery_decisions[2].evidence.recovery_low_count == 0
    assert recovery_decisions[7].reason == "recovery_confirmed"
    assert recovery_decisions[7].state == "COOLDOWN"


def test_case_7_persistent_fall_does_not_create_duplicate_events() -> None:
    decisions = run_sequence([0.80, 0.85, 0.91, 0.94, 0.96, 0.93, 0.89, 0.92, 0.95, 0.96])
    created = [decision for decision in decisions if decision.event_created]

    assert len(created) == 1
    assert decisions[-1].incident_id == created[0].incident_id
    assert decisions[-1].evidence.candidate_active is True
