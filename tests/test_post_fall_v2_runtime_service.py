from __future__ import annotations

import queue
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from app.camera.frame_buffer import FrameBuffer
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.follow_target import FollowTargetState
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
        self.samples: list[SampledFrame] = []

    def infer(self, sampled: SampledFrame) -> BinaryFallResult:
        self.samples.append(sampled)
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
    def __init__(self, *, fail: bool = False, delay: float = 0.0, fall_verdict: str = "unclear") -> None:
        self.calls = 0
        self.fail = fail
        self.delay = delay
        self.fall_verdict = fall_verdict

    def analyze_fall_event(self, event, keyframes):
        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("vlm boom")
        from app.post_fall_v2.schemas import FallDetailResult

        evidence = {
            "activity": "低位状态不明",
            "posture_state": "ground_low",
            "fall_transition_visible": False,
            "intentional_action_evidence": None,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
        }
        if self.fall_verdict == "confirmed_fall":
            evidence.update(
                high_risk_fall=1,
                scene_type="fall",
                recommended_action="emergency_alert",
                activity="非自主失衡倒地",
                fall_transition_visible=True,
                intentional_action_evidence=False,
            )
        return FallDetailResult(
            incident_id=event.incident_id,
            analysis_status="completed",
            fall_verdict=self.fall_verdict,
            summary="mock detail",
            model_name="mock",
            **evidence,
        )


class _Reporter:
    def __init__(self) -> None:
        self.results = []

    def inspect_result(self, result) -> None:
        self.results.append(result)


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
    status = service.status("camera_01")
    service.stop_all()

    assert analyzer.calls == 0
    assert service.events() == []
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.detector["pipeline"] == "post_fall_v2"
    assert published.objects[0].fall_decision["binary_label"] == "NON_FALL"


def test_runtime_queue_keeps_only_latest_frame_when_worker_lags() -> None:
    service, _buffer, _analyzer, _store = build_service([0.1])
    sampled = []
    for seq in (1, 2, 3):
        frame = np.full((48, 64, 3), seq, dtype=np.uint8)
        sampled.append(
            SampledFrame(
                camera_id="camera_01",
                frame_id=f"camera_01_1_{seq:08d}",
                frame_seq=seq,
                captured_at="2026-08-12T00:00:00.000+00:00",
                sampled_at="2026-08-12T00:00:00.000+00:00",
                captured_monotonic=time.monotonic(),
                sampled_monotonic=time.monotonic(),
                source_width=64,
                source_height=48,
                source_generation=1,
                frame=frame,
            )
        )

    state = service._states.setdefault(  # noqa: SLF001 - asserts latest-frame-only queue behavior
        "camera_01",
        SimpleNamespace(frames_sampled=0, frames_dropped=0),
    )
    frame_queue = queue.Queue(maxsize=1)

    service._put_latest("camera_01", frame_queue, sampled[0])  # noqa: SLF001
    service._put_latest("camera_01", frame_queue, sampled[1])  # noqa: SLF001
    service._put_latest("camera_01", frame_queue, sampled[2])  # noqa: SLF001

    assert frame_queue.qsize() == 1
    assert frame_queue.get_nowait().frame_seq == 3
    assert state.frames_sampled == 3
    assert state.frames_dropped == 2


def test_confirmed_fall_creates_one_event_and_one_vlm_call() -> None:
    service, buffer, analyzer, store = build_service([0.9, 0.9, 0.9, 0.9, 0.9])
    service.start_for_camera("camera_01")
    for _ in range(6):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: analyzer.calls == 1 and service.events() and service.events()[0].vlm_status == "completed")
    service.stop_all()

    events = service.events()
    assert len(events) == 1
    assert analyzer.calls == 1
    assert events[0].vlm_status == "completed"
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["fall_state"] == "observe_post_fall"
    assert published.objects[0].fall_decision["safety_outcome"] == "observe"
    assert published.objects[0].alarm_preview["confirmed"] is False


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
    assert decision["fall_state"] == "observe_post_fall"
    assert decision["safety_outcome"] == "observe"
    assert decision["vlm_status"] == "completed"
    assert decision["vlm_summary"] == "mock detail"
    assert published.objects[0].alarm_preview["confirmed"] is False


def test_qwen_confirmed_fall_reports_to_main_system_reporter() -> None:
    reporter = _Reporter()
    outbox_records = []
    service, buffer, analyzer, _store = build_service(
        [0.9, 0.9, 0.9, 0.9, 0.9],
        fall_verdict="confirmed_fall",
        reporter=reporter,
        outbox_records=outbox_records,
    )
    service.start_for_camera("camera_01")
    for _ in range(6):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: len(reporter.results) == 1)
    service.stop_all()

    result = reporter.results[0]
    assert result.objects[0].alarm_preview["confirmed"] is True
    assert result.objects[0].alarm_preview["source"] == "post_fall_v2_transition"
    assert result.objects[0].fall_decision["decision_authority"] == "event_state_machine"
    assert result.objects[0].fall_decision["safety_path"] == "transition_fall"
    assert result.objects[0].fall_decision["fall_verdict"] == "confirmed_fall"
    assert result.objects[0].fall_decision["high_risk_fall"] == 1
    assert result.objects[0].fall_decision["vlm_summary"] == "mock detail"
    assert outbox_records[0].metadata["qwen_review"]["high_risk_fall"] == 1


def test_unclear_qwen_persistent_post_fall_stays_observe_without_high_risk_gate() -> None:
    reporter = _Reporter()
    outbox_records = []
    service, buffer, _analyzer, store = build_service(
        [0.9] * 20,
        fall_verdict="unclear",
        reporter=reporter,
        post_fall_alert_min_ms=80,
        outbox_records=outbox_records,
    )
    service.start_for_camera("camera_01")
    for _ in range(12):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: len(service.events()) == 1 and service.events()[0].safety_decision is not None)
    service.stop_all()

    assert reporter.results == []
    assert outbox_records == []
    latest = store.latest_published("camera_01")
    assert latest is not None
    assert latest.objects[0].fall_decision["safety_outcome"] == "observe"
    assert latest.objects[0].fall_decision["safety_path"] == "uncertain_evidence"


def test_running_qwen_prevents_premature_persistent_post_fall_alert() -> None:
    reporter = _Reporter()
    service, buffer, _analyzer, _store = build_service(
        [0.9] * 20,
        vlm_delay=0.4,
        fall_verdict="unclear",
        reporter=reporter,
        post_fall_alert_min_ms=80,
    )
    service.start_for_camera("camera_01")
    for _ in range(10):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: len(service.events()) == 1)

    assert reporter.results == []
    service.stop_all()

    assert reporter.results == []


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


def test_full_frame_mode_ignores_invalid_follow_target_and_reaches_qwen() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=1,
            target_valid=False,
            follow_active=False,
            bearing_deg=0.0,
            distance_m=2.0,
            received_monotonic=time.monotonic(),
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, analyzer, store = build_service(
        [0.99, 0.99, 0.99],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    wait_for(lambda: analyzer.calls == 1 and service.events())
    status = service.status("camera_01")
    service.stop_all()

    assert classifier.index > 0
    assert analyzer.calls == 1
    assert len(service.events()) == 1
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["binary_label"] == "FALL"
    assert published.objects[0].fall_decision["binary_input_source"] == "full_frame"
    assert published.objects[0].fall_decision["post_fall_v2_input_mode"] == "full_frame"
    assert published.objects[0].fall_decision["target_tracking_state"] == "unavailable"
    assert published.objects[0].fall_decision["reason"] != "follow_target_unavailable"
    assert status["post_fall_v2_input_mode"] == "full_frame"
    assert status["binary_input_source"] == "full_frame"
    assert status["follow_target_required_for_binary"] is False
    assert status["target_unavailable_skips"] == 0


def test_full_frame_mode_ignores_stale_follow_target_and_runs_binary() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=2,
            target_valid=True,
            follow_active=True,
            bearing_deg=0.0,
            distance_m=2.0,
            received_monotonic=time.monotonic() - 1.0,
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, analyzer, store = build_service(
        [0.1, 0.1, 0.1],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    status = service.status("camera_01")
    service.stop_all()

    assert classifier.index > 0
    assert analyzer.calls == 0
    assert service.events() == []
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["binary_label"] == "NON_FALL"
    assert published.objects[0].fall_decision["binary_input_source"] == "full_frame"
    assert published.objects[0].fall_decision["target_tracking_state"] == "unavailable"
    assert published.objects[0].fall_decision["target_binding"]["reason"] == "target_stale"
    assert published.objects[0].fall_decision["reason"] != "follow_target_unavailable"


def test_follow_target_roi_mode_keeps_experimental_skip_behavior() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=3,
            target_valid=False,
            follow_active=False,
            bearing_deg=0.0,
            distance_m=2.0,
            received_monotonic=time.monotonic(),
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, analyzer, store = build_service(
        [0.99, 0.99, 0.99],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
        input_mode="follow_target_roi",
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(4):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    status = service.status("camera_01")
    service.stop_all()

    assert classifier.index == 0
    assert analyzer.calls == 0
    assert service.events() == []
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["binary_label"] == "UNKNOWN"
    assert published.objects[0].fall_decision["binary_input_source"] == "unavailable"
    assert published.objects[0].fall_decision["reason"] == "follow_target_unavailable"
    assert status["target_unavailable_skips"] > 0


def test_auto_mode_falls_back_to_full_frame_when_follow_target_unavailable() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=4,
            target_valid=False,
            follow_active=False,
            bearing_deg=0.0,
            distance_m=2.0,
            received_monotonic=time.monotonic(),
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, _analyzer, store = build_service(
        [0.1, 0.1, 0.1],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
        input_mode="auto",
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(3):
        buffer.update(np.zeros((48, 64, 3), dtype=np.uint8))
        time.sleep(0.03)
    service.stop_all()

    assert classifier.index > 0
    assert classifier.samples[0].target_binding["binary_input_source"] == "full_frame_fallback"
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["binary_label"] == "NON_FALL"
    assert published.objects[0].fall_decision["binary_input_source"] == "full_frame_fallback"


def test_follow_target_fresh_roi_is_binary_input() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=7,
            target_valid=True,
            follow_active=True,
            bearing_deg=0.0,
            distance_m=1.8,
            received_monotonic=time.monotonic(),
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, _analyzer, store = build_service(
        [0.1],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
        input_mode="follow_target_roi",
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(3):
        buffer.update(np.zeros((100, 200, 3), dtype=np.uint8))
        time.sleep(0.03)
    service.stop_all()

    assert classifier.samples
    assert classifier.samples[0].frame.shape[:2] == (100, 100)
    assert classifier.samples[0].target_binding["roi"] == [50, 0, 150, 100]
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.frame_width == 200
    assert published.objects[0].bbox == [50.0, 0.0, 150.0, 100.0]


def test_follow_target_fresh_roi_runs_binary_when_follow_inactive() -> None:
    receiver = SimpleNamespace(
        latest=lambda: FollowTargetState(
            sequence=8,
            target_valid=True,
            follow_active=False,
            bearing_deg=-15.0,
            distance_m=1.5,
            received_monotonic=time.monotonic(),
        ),
        status=lambda: {
            "running": True,
            "packet_count": 1,
            "invalid_count": 0,
            "out_of_order_count": 0,
        },
    )
    service, buffer, _analyzer, store = build_service(
        [0.1],
        follow_target_enabled=True,
        follow_target_receiver=receiver,
        input_mode="auto",
    )
    classifier = service._classifier  # noqa: SLF001
    service.start_for_camera("camera_01")
    for _ in range(3):
        buffer.update(np.zeros((100, 200, 3), dtype=np.uint8))
        time.sleep(0.03)
    service.stop_all()

    assert classifier.index > 0
    assert classifier.samples
    binding = classifier.samples[0].target_binding
    assert binding["target_tracking_state"] == "fresh"
    assert binding["target_valid"] is True
    assert binding["follow_active"] is False
    assert binding["bearing_deg"] == -15.0
    assert binding["distance_m"] == 1.5
    assert binding["roi"] is not None
    published = store.latest_published("camera_01")
    assert published is not None
    assert published.objects[0].fall_decision["target_tracking_state"] == "fresh"


def build_service(
    probabilities: list[float],
    *,
    fail_vlm: bool = False,
    vlm_delay: float = 0.0,
    vlm_timeout: float = 1.0,
    fall_verdict: str = "unclear",
    reporter=None,
    post_fall_alert_min_ms: int = 10000,
    outbox_records: list | None = None,
    follow_target_enabled: bool = False,
    follow_target_receiver=None,
    input_mode: str = "full_frame",
):
    buffer = FrameBuffer("camera_01")
    store = RealtimeResultStore()
    analyzer = _Analyzer(fail=fail_vlm, delay=vlm_delay, fall_verdict=fall_verdict)
    from app.post_fall_v2.vlm_review_service import VLMReviewService

    service = PostFallV2RuntimeService(
        settings=replace(
            settings(),
            post_fall_v2_vlm_timeout_seconds=vlm_timeout,
            post_fall_v2_post_fall_alert_min_ms=post_fall_alert_min_ms,
            follow_target_enabled=follow_target_enabled,
            follow_target_fresh_ms=300,
            follow_target_grace_ms=700,
            follow_target_camera_hfov_deg=90.0,
            follow_target_camera_yaw_offset_deg=0.0,
            follow_target_roi_width_ratio=0.5,
            follow_target_grace_roi_width_ratio=0.7,
            post_fall_v2_input_mode=input_mode,
        ),
        source_manager=_SourceManager(buffer),
        realtime_store=store,
        result_channels=_NoopChannels(),
        event_pipeline=SimpleNamespace(
            outbox=SimpleNamespace(
                add_event=lambda record: (outbox_records.append(record) if outbox_records is not None else record)
            )
        ),
        vlm_review_service=VLMReviewService(enabled=True, timeout_seconds=vlm_timeout, analyzer=analyzer),
        fall_event_reporter=reporter,
        classifier=_Classifier(probabilities),
        follow_target_receiver=follow_target_receiver,
    )
    return service, buffer, analyzer, store


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()
