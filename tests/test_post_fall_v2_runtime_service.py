from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from app.camera.frame_buffer import FrameBuffer
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.schemas import (
    FULL_FRAME_TRAIN_MATCHED,
    BinaryFallResult,
    InputInfo,
    ModelInfo,
    PerformanceInfo,
    SampledFrame,
    ThresholdInfo,
)


class _NoopChannels:
    subscriber_count = 0

    def publish(self, result):
        self.last = result


class _SourceManager:
    def __init__(self, buffer: FrameBuffer) -> None:
        self.buffer = buffer

    def get_buffer(self, camera_id: str):
        return self.buffer


class _Classifier:
    loaded = True
    model_sha256 = "testsha"
    provider = "test"

    def __init__(self, probabilities: list[float]) -> None:
        self.probabilities = probabilities
        self.index = 0

    def infer(self, sampled: SampledFrame) -> BinaryFallResult:
        probability = self.probabilities[min(self.index, len(self.probabilities) - 1)]
        self.index += 1
        return BinaryFallResult(
            frame_id=sampled.frame_id,
            camera_id=sampled.camera_id,
            captured_at=sampled.captured_at,
            sampled_at=sampled.sampled_at,
            inferred_at="2026-08-12T00:00:00.000+00:00",
            prediction="Fall" if probability >= 0.4 else "noFall",
            class_index=1 if probability >= 0.4 else 0,
            fall_probability=probability,
            nofall_probability=1.0 - probability,
            shadow_candidate_hint=probability >= 0.4,
            threshold=ThresholdInfo(value=0.4),
            model=ModelInfo(name="fake_binary", format="onnx", sha256="testsha", provider="test"),
            input=InputInfo(policy=FULL_FRAME_TRAIN_MATCHED, source_width=64, source_height=48, model_width=224, model_height=224),
            performance=PerformanceInfo(queue_delay_ms=0.0, preprocess_ms=0.0, inference_ms=0.0, total_ms=0.0),
            valid=True,
        )


class _Analyzer:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.calls = 0
        self.fail = fail
        self.delay = delay

    def analyze_fall_event(self, event, keyframes):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("vlm boom")
        from app.post_fall_v2.schemas import FallDetailResult

        return FallDetailResult(
            incident_id=event.incident_id,
            analysis_status="completed",
            summary="mock detail",
            model_name="mock",
        )


def settings() -> Settings:
    return replace(
        Settings(),
        pipeline_mode="post_fall_v2",
        post_fall_v2_enabled=True,
        post_fall_v2_binary_threshold=0.4,
        post_fall_v2_sample_fps=50.0,
        post_fall_v2_window_size=3,
        post_fall_v2_min_positive_frames=3,
        post_fall_v2_min_consecutive_frames=3,
        post_fall_v2_candidate_min_ms=1,
        post_fall_v2_recovery_min_ms=10,
        post_fall_v2_cooldown_ms=10,
        post_fall_v2_vlm_enabled=True,
        post_fall_v2_vlm_timeout_seconds=1.0,
    )


def test_non_fall_stream_publishes_no_event_and_zero_vlm_calls() -> None:
    service, buffer, analyzer, store = build_service([0.1, 0.2, 0.1])
    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    service.stop_all()

    assert analyzer.calls == 0
    assert service.events() == []
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.detector["pipeline"] == "post_fall_v2"
    assert published.objects[0].fall_decision["binary_label"] == "NON_FALL"


def test_confirmed_fall_creates_one_event_and_one_vlm_call() -> None:
    service, buffer, analyzer, store = build_service([0.9, 0.9, 0.9, 0.9, 0.9])
    service.start_for_camera("camera_01")
    for _ in range(6):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: analyzer.calls == 1)
    service.stop_all()

    events = service.events()
    assert len(events) == 1
    assert analyzer.calls == 1
    assert events[0].vlm_status == "completed"
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["fall_state"] == "confirmed"


def test_vlm_completion_republishes_enriched_result_after_confirmed_event() -> None:
    service, buffer, analyzer, store = build_service([0.9, 0.9, 0.9, 0.9, 0.9])
    service.start_for_camera("camera_01")
    for _ in range(6):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(
        lambda: (store.latest_published("camera_01") is not None)
        and store.latest_published("camera_01").objects[0].fall_decision.get("vlm_status") == "completed"
    )
    service.stop_all()

    published = store.latest_published("camera_01")
    assert published is not None
    decision = published.objects[0].fall_decision
    assert decision["fall_state"] == "confirmed"
    assert decision["vlm_status"] == "completed"
    assert decision["vlm_summary"] == "mock detail"


def test_vlm_failure_does_not_remove_fall_event() -> None:
    service, buffer, analyzer, _store = build_service([0.9, 0.9, 0.9, 0.9], fail_vlm=True)
    service.start_for_camera("camera_01")
    for _ in range(5):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: analyzer.calls == 1)
    service.stop_all()

    events = service.events()
    assert len(events) == 1
    assert events[0].vlm_status == "failed"
    assert events[0].vlm_analysis is not None
    assert events[0].vlm_analysis.error_message == "vlm boom"


def test_vlm_timeout_does_not_remove_fall_event() -> None:
    service, buffer, analyzer, _store = build_service([0.9, 0.9, 0.9, 0.9], vlm_delay=0.5, vlm_timeout=0.05)
    service.start_for_camera("camera_01")
    for _ in range(5):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: len(service.events()) == 1 and service.events()[0].vlm_status == "timeout")
    service.stop_all()

    events = service.events()
    assert len(events) == 1
    assert analyzer.calls == 1
    assert events[0].vlm_analysis is not None
    assert events[0].vlm_analysis.analysis_status == "timeout"


def build_service(probabilities: list[float], *, fail_vlm: bool = False, vlm_delay: float = 0.0, vlm_timeout: float = 1.0):
    buffer = FrameBuffer("camera_01")
    store = RealtimeResultStore()
    analyzer = _Analyzer(fail=fail_vlm, delay=vlm_delay)
    from app.post_fall_v2.vlm_review_service import VLMReviewService

    service = PostFallV2RuntimeService(
        settings=replace(settings(), post_fall_v2_vlm_timeout_seconds=vlm_timeout),
        source_manager=_SourceManager(buffer),
        realtime_store=store,
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(outbox=SimpleNamespace(add_event=lambda record: record)),
        vlm_review_service=VLMReviewService(enabled=True, timeout_seconds=vlm_timeout, analyzer=analyzer),
        classifier=_Classifier(probabilities),
    )
    return service, buffer, analyzer, store


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()
