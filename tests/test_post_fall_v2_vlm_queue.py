from __future__ import annotations

import threading
import time

from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframePackage
from app.post_fall_v2.vlm_review_service import VLMReviewService


class _BlockingAnalyzer:
    def __init__(self) -> None:
        self.calls = 0
        self.release = threading.Event()

    def analyze_fall_event(self, event, keyframes):
        self.calls += 1
        self.release.wait(2)
        return FallDetailResult(incident_id=event.incident_id, analysis_status="completed", summary="done")


def test_single_incident_is_idempotent_and_queue_is_bounded() -> None:
    analyzer = _BlockingAnalyzer()
    service = VLMReviewService(enabled=True, timeout_seconds=3, analyzer=analyzer, queue_capacity=2)
    first_result: list[FallDetailResult] = []
    second_result: list[FallDetailResult] = []

    first = threading.Thread(target=lambda: first_result.append(service.analyze_fall_event(_event("one"), _package("one"))))
    second = threading.Thread(target=lambda: second_result.append(service.analyze_fall_event(_event("two"), _package("two"))))
    first.start()
    _wait_for(lambda: service.queue_depth == 1)
    duplicate = service.analyze_fall_event(_event("one"), _package("one"))
    second.start()
    _wait_for(lambda: service.queue_depth == 2)
    full = service.analyze_fall_event(_event("three"), _package("three"))

    assert duplicate.analysis_status == "failed"
    assert duplicate.error_message == "duplicate_incident_submission"
    assert full.analysis_status == "failed"
    assert full.error_message == "vlm_queue_full"
    assert analyzer.calls == 1
    analyzer.release.set()
    first.join(2)
    second.join(2)
    _wait_for(lambda: service.queue_depth == 0)
    assert [item.analysis_status for item in first_result + second_result] == ["completed", "completed"]
    assert analyzer.calls == 2
    service.shutdown()


def test_timeout_keeps_incident_in_flight_until_underlying_worker_exits() -> None:
    analyzer = _BlockingAnalyzer()
    service = VLMReviewService(enabled=True, timeout_seconds=0.05, analyzer=analyzer, queue_capacity=1)
    result: list[FallDetailResult] = []
    worker = threading.Thread(target=lambda: result.append(service.analyze_fall_event(_event("timeout"), _package("timeout"))))
    worker.start()
    _wait_for(lambda: service.queue_depth == 1)
    _wait_for(lambda: bool(result), timeout=1.0)

    duplicate = service.analyze_fall_event(_event("timeout"), _package("timeout"))

    assert result[0].analysis_status == "timeout"
    assert duplicate.analysis_status == "timeout"
    assert analyzer.calls == 1
    analyzer.release.set()
    worker.join(2)
    _wait_for(lambda: service.queue_depth == 0)
    service.shutdown()


def _event(incident_id: str) -> FallEvent:
    return FallEvent(
        incident_id=incident_id,
        camera_id="camera_01",
        state="fall_confirmed",
        started_at="2026-08-13T00:00:00+00:00",
        confirmed_at="2026-08-13T00:00:00+00:00",
        binary_evidence={},
    )


def _package(incident_id: str) -> KeyframePackage:
    return KeyframePackage(
        incident_id=incident_id,
        camera_id="camera_01",
        confirmed_at="2026-08-13T00:00:00+00:00",
        source_width=1,
        source_height=1,
        frames=[],
        fall_probability_summary={},
    )


def _wait_for(predicate, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()
