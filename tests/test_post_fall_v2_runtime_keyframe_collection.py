from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from app.camera.frame_buffer import FrameBuffer
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
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


class _Outbox:
    def __init__(self) -> None:
        self.records = []

    def add_event(self, record):
        self.records.append(record)
        return record


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
            inferred_at="2026-08-13T00:00:00.000+00:00",
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
    def __init__(self, delay: float = 0.0, fall_verdict: str = "confirmed_fall") -> None:
        self.calls = 0
        self.delay = delay
        self.fall_verdict = fall_verdict

    def analyze_fall_event(self, event, keyframes):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        from app.post_fall_v2.schemas import FallDetailResult

        return FallDetailResult(
            incident_id=event.incident_id,
            analysis_status="completed",
            fall_verdict=self.fall_verdict,
            high_risk_fall=1 if self.fall_verdict == "confirmed_fall" else 0,
            scene_type="fall" if self.fall_verdict == "confirmed_fall" else "unknown",
            recommended_action="emergency_alert" if self.fall_verdict == "confirmed_fall" else "manual_review",
            activity="非自主失衡倒地",
            posture_state="ground_low",
            fall_transition_visible=self.fall_verdict == "confirmed_fall",
            intentional_action_evidence=False,
            recovery_observed=False,
            persistent_ground_state="observed",
            summary="mock detail",
            model_name="mock",
        )


def test_confirmed_event_is_created_immediately_and_qwen_waits_for_future_keyframes(tmp_path) -> None:
    buffer = FrameBuffer("camera_01")
    store = RealtimeResultStore()
    analyzer = _Analyzer()
    outbox = _Outbox()
    archive = PostFallTestArchiveService(str(tmp_path / "event"), performance_sample_interval_seconds=60)
    archive.start_test(60)
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=_SourceManager(buffer),
        realtime_store=store,
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(outbox=outbox),
        vlm_review_service=_vlm(analyzer),
        test_archive_service=archive,
        classifier=_Classifier([0.9] * 30),
    )

    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)

    wait_for(lambda: len(service.events()) == 1 and service.events()[0].vlm_status == "collecting_keyframes")
    incident_id = service.events()[0].incident_id
    assert (tmp_path / "event" / "binary-classification" / "full" / incident_id / "binary_event.json").exists()
    assert (tmp_path / "event" / "camera_01" / incident_id / "event.json").exists()
    assert analyzer.calls == 0

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and analyzer.calls == 0:
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: len(service.events()) == 1 and service.events()[0].vlm_status == "completed")
    service.stop_all()

    events = service.events()
    assert len(events) == 1
    assert analyzer.calls == 1
    assert events[0].keyframes is not None
    assert events[0].keyframes.status == "ready"
    assert events[0].keyframes.resolved_offsets_ms == [0, 1000]
    assert outbox.records
    assert outbox.records[-1].metadata["keyframes"]["status"] == "ready"
    decision = store.latest_published("camera_01").objects[0].fall_decision
    assert decision["fall_state"] == "fallen_confirmed"
    assert decision["keyframe_status"] == "ready"
    assert decision["vlm_status"] == "completed"


def test_keyframe_collection_degrades_but_still_runs_one_vlm_call() -> None:
    buffer = FrameBuffer("camera_01")
    analyzer = _Analyzer()
    outbox = _Outbox()
    service = PostFallV2RuntimeService(
        settings=replace(_settings(), post_fall_v2_keyframe_collection_timeout_seconds=0.1),
        source_manager=_SourceManager(buffer),
        realtime_store=RealtimeResultStore(),
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(outbox=outbox),
        vlm_review_service=_vlm(analyzer),
        classifier=_Classifier([0.9] * 6),
    )

    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)

    wait_for(lambda: len(service.events()) == 1 and service.events()[0].vlm_status == "completed")
    service.stop_all()

    event = service.events()[0]
    assert analyzer.calls == 1
    assert event.keyframes is not None
    assert event.keyframes.status == "degraded"
    assert outbox.records[-1].metadata["keyframes"]["status"] == "degraded"


def test_immediate_vlm_path_exports_current_ring_buffer_keyframes() -> None:
    buffer = FrameBuffer("camera_01")
    observed_media = []
    outbox = _Outbox()

    class _ProviderObservingAnalyzer(_Analyzer):
        def analyze_fall_event(self, event, keyframes):
            images, missing = service.qwen_images_for_incident(event.incident_id)
            observed_media.append((images, missing))
            return super().analyze_fall_event(event, keyframes)

    analyzer = _ProviderObservingAnalyzer()
    service = PostFallV2RuntimeService(
        settings=replace(
            _settings(),
            post_fall_v2_keyframe_post_collection_enabled=False,
            event_keyframe_offsets_ms=(0,),
        ),
        source_manager=_SourceManager(buffer),
        realtime_store=RealtimeResultStore(),
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(outbox=outbox),
        vlm_review_service=_vlm(analyzer),
        classifier=_Classifier([0.9] * 20),
    )

    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)

    wait_for(lambda: len(service.events()) == 1 and service.events()[0].vlm_status == "completed")
    service.stop_all()

    assert len(observed_media) == 1
    images, missing = observed_media[0]
    assert len(images) == 1
    assert images[0].image_bytes[:2] == b"\xff\xd8"
    assert missing == []


def test_stop_for_camera_cancels_keyframe_collection() -> None:
    buffer = FrameBuffer("camera_01")
    analyzer = _Analyzer(delay=0.2)
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=_SourceManager(buffer),
        realtime_store=RealtimeResultStore(),
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(outbox=SimpleNamespace(add_event=lambda record: record)),
        vlm_review_service=_vlm(analyzer),
        classifier=_Classifier([0.9] * 20),
    )

    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)

    wait_for(lambda: len(service.events()) == 1)
    service.stop_for_camera("camera_01")

    status = service.status("camera_01")
    assert status["keyframe_collection_active_count"] == 0
    assert service.latest_event(service.events()[0].incident_id) is not None


def _settings() -> Settings:
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
        post_fall_v2_qwen_enabled=True,
        post_fall_v2_qwen_provider="qwen_keyframe",
        post_fall_v2_keyframe_post_collection_enabled=True,
        post_fall_v2_keyframe_tolerance_ms=80,
        post_fall_v2_keyframe_collection_timeout_seconds=1.0,
        event_keyframe_offsets_ms=(0, 1000),
        follow_target_enabled=False,
    )


def _vlm(analyzer):
    from app.post_fall_v2.vlm_review_service import VLMReviewService

    return VLMReviewService(enabled=True, timeout_seconds=1.0, analyzer=analyzer)


def wait_for(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()
