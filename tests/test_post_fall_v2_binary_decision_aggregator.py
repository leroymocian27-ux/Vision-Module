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
        raw_label="Fall" if probability >= 0.4 else "noFall",
        decision_label="FALL" if probability >= 0.4 else "NON_FALL",
        threshold=0.4,
        model_name="test",
        model_version="test",
        valid=True,
        source_width=640,
        source_height=480,
    )


def aggregator() -> BinaryDecisionAggregator:
    return BinaryDecisionAggregator(
        BinaryDecisionAggregatorConfig(
            threshold=0.4,
            window_size=5,
            min_positive_frames=3,
            min_consecutive_frames=3,
            candidate_min_ms=800,
            recovery_min_ms=1000,
            cooldown_ms=1000,
        )
    )


def immediate_aggregator() -> BinaryDecisionAggregator:
    return BinaryDecisionAggregator(
        BinaryDecisionAggregatorConfig(
            threshold=0.4,
            window_size=10,
            min_positive_frames=1,
            min_consecutive_frames=1,
            candidate_min_ms=0,
            recovery_min_ms=1000,
            cooldown_ms=1000,
        )
    )


def test_single_threshold_hit_immediately_creates_candidate_event() -> None:
    agg = immediate_aggregator()
    decision = agg.update(frame(1, 0.9), now=1.0)

    assert decision.state == "EVENT_ACTIVE"
    assert decision.event_created is True
    assert decision.incident_id is not None
    assert decision.reason == "fall_confirmed"
    assert decision.evidence.positive_count == 1
    assert decision.evidence.consecutive_positive_count == 1
    assert decision.evidence.candidate_duration_ms == 0


def test_single_fall_frame_does_not_confirm() -> None:
    agg = aggregator()
    decision = agg.update(frame(1, 0.9), now=1.0)

    assert decision.state == "FALL_CANDIDATE"
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
    decisions = [
        agg.update(frame(1, 0.9), now=1.0),
        agg.update(frame(2, 0.8), now=1.4),
        agg.update(frame(3, 0.85), now=1.9),
        agg.update(frame(4, 0.92), now=2.4),
        agg.update(frame(5, 0.91), now=8.0),
    ]

    created = [item for item in decisions if item.event_created]
    assert len(created) == 1
    assert created[0].state == "EVENT_ACTIVE"
    assert decisions[-1].event_created is False
    assert decisions[-1].incident_id == created[0].incident_id


def test_recovery_cooldown_rearms_and_second_fall_creates_second_incident() -> None:
    agg = aggregator()
    first = None
    for seq, now in [(1, 1.0), (2, 1.4), (3, 1.9)]:
        decision = agg.update(frame(seq, 0.9), now=now)
        if decision.event_created:
            first = decision.incident_id
    assert first is not None

    agg.update(frame(4, 0.1), now=3.0)
    agg.update(frame(5, 0.1), now=4.2)
    rearmed = agg.update(frame(6, 0.1), now=5.3)
    assert rearmed.rearmed is True
    assert rearmed.state == "NORMAL"

    second = None
    for seq, now in [(7, 6.0), (8, 6.4), (9, 6.9)]:
        decision = agg.update(frame(seq, 0.9), now=now)
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
