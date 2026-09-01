from __future__ import annotations

import json
import time
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from app.camera.frame_buffer import FrameBuffer
from app.core.config import Settings
from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.schemas import (
    BinaryAggregateDecision,
    BinaryDecisionEvidence,
    BinaryFrameResult,
    FallDetailResult,
    FallEvent,
    FallSafetyDecision,
    KeyframeItem,
    KeyframePackage,
)
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.services.stream_service import StreamService


class _Classifier:
    loaded = True
    model_sha256 = "testsha"
    provider = "test"

    def infer(self, sampled):  # pragma: no cover - the control tests do not consume frames
        raise AssertionError("manual control test should not run inference")


class _SourceManager:
    def __init__(self, *, connected: bool = True) -> None:
        self.buffer = FrameBuffer("camera_01")
        self.runtime = SimpleNamespace(
            config=SimpleNamespace(camera_id="camera_01", source_url="mock://colorbars"),
            frame_buffer=self.buffer,
        )
        self.connected = connected

    def get_runtime(self, camera_id):
        return self.runtime

    def get_buffer(self, camera_id):
        return self.buffer

    def worker_status(self, camera_id):
        return SimpleNamespace(connected=self.connected)


class _NoopChannels:
    def publish(self, result) -> None:
        pass


class _Service:
    def __init__(self) -> None:
        self.started = []

    def start_for_camera(self, camera_id):
        self.started.append(camera_id)

    def stop_for_camera(self, camera_id):
        pass


class _RealtimeStore:
    def clear_camera(self, camera_id):
        pass


def _settings() -> Settings:
    return replace(
        Settings(),
        pipeline_mode="post_fall_v2",
        post_fall_v2_enabled=True,
        post_fall_v2_vlm_enabled=True,
        post_fall_v2_qwen_enabled=True,
        post_fall_v2_keyframe_post_collection_enabled=False,
    )


def test_manual_control_defaults_binary_and_qwen_off() -> None:
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=_SourceManager(),
        realtime_store=SimpleNamespace(),
        result_channels=_NoopChannels(),
        classifier=_Classifier(),
        manual_control_enabled=True,
    )

    status = service.control_status("camera_01")

    assert status["binary_enabled"] is False
    assert status["qwen_enabled"] is False
    assert status["runtime"]["running"] is False
    assert status["performance"]["sample_fps"] == 10.0
    assert status["performance"]["ai_queue_depth"] == 0
    assert status["performance"]["qwen"]["armed"] is False
    assert status["performance"]["qwen"]["requests"] == 0


def test_control_status_treats_recent_frame_as_stream_ready() -> None:
    source_manager = _SourceManager(connected=False)
    source_manager.buffer.update(np.zeros((8, 8, 3), dtype="uint8"))
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=source_manager,
        realtime_store=SimpleNamespace(),
        result_channels=_NoopChannels(),
        classifier=_Classifier(),
        manual_control_enabled=True,
    )

    status = service.control_status("camera_01")

    assert status["stream_connected"] is True


def test_control_status_requires_runtime_or_recent_frame() -> None:
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=_SourceManager(connected=False),
        realtime_store=SimpleNamespace(),
        result_channels=_NoopChannels(),
        classifier=_Classifier(),
        manual_control_enabled=True,
    )

    status = service.control_status("camera_01")

    assert status["stream_connected"] is False


def test_manual_binary_and_qwen_require_order_and_can_toggle() -> None:
    service = PostFallV2RuntimeService(
        settings=_settings(),
        source_manager=_SourceManager(),
        realtime_store=SimpleNamespace(),
        result_channels=_NoopChannels(),
        classifier=_Classifier(),
        manual_control_enabled=True,
    )

    with pytest.raises(ValueError):
        service.set_qwen_enabled("camera_01", True)

    enabled = service.set_binary_enabled("camera_01", True)
    assert enabled["binary_enabled"] is True
    qwen = service.set_qwen_enabled("camera_01", True)
    assert qwen["qwen_enabled"] is True
    disabled = service.set_binary_enabled("camera_01", False)
    assert disabled["binary_enabled"] is False
    assert disabled["qwen_enabled"] is False
    service.stop_all()


def test_post_fall_v2_stream_start_does_not_start_binary_when_manual_off() -> None:
    settings = _settings()
    source_manager = SimpleNamespace(
        runtime=None,
        get_runtime=lambda camera_id: None,
        start_source=lambda config: (SimpleNamespace(config=config), True),
        stop_source=lambda camera_id: True,
    )
    post_fall = _Service()
    post_fall.binary_control_enabled = False

    service = StreamService(
        settings=settings,
        source_manager=source_manager,
        detection_service=_Service(),
        realtime_store=_RealtimeStore(),
        tracking_service=SimpleNamespace(reset=lambda camera_id: None),
        identity_binding_service=SimpleNamespace(reset_camera=lambda camera_id: None),
        temporal_service=SimpleNamespace(reset_camera=lambda camera_id: None),
        tracking_worker_service=_Service(),
        identity_binding_worker_service=_Service(),
        pose_worker_service=_Service(),
        result_publisher_service=_Service(),
        post_fall_v2_runtime_service=post_fall,
    )

    started, message = service.start("camera_01", "mock://colorbars")

    assert started is True
    assert message == "stream started"
    assert post_fall.started == []


def test_test_archive_keeps_binary_and_qwen_event_ids_matched(tmp_path) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"))
    archive.start_test(60)
    images = [QwenImageInput(offset_ms=0, role="trigger", image_bytes=b"jpeg")]

    event_a = _event("pfv2-camera_01-A", "confirmed_fall")
    event_b = _event("pfv2-camera_01-B", "intentional_low_posture")
    event_c = _event("pfv2-camera_01-C", "unclear")
    event_d = _event("pfv2-camera_01-D", "unclear", analysis_status="failed")
    package_a = _package(event_a)
    package_b = _package(event_b)
    package_c = _package(event_c)
    package_d = _package(event_d)

    assert archive.archive_binary_event(event_a, package_a, images)
    assert archive.archive_binary_event(event_b, package_b, images)
    assert archive.archive_binary_event(event_c, package_c, images)
    assert archive.archive_binary_event(event_d, package_d, images)
    assert archive.archive_qwen_result(event_a) == "confirm"
    assert archive.archive_qwen_result(event_b) == "deny"
    assert archive.archive_qwen_result(event_c) == "review"
    assert archive.archive_qwen_result(event_d) == "review"

    status = archive.status()
    assert status.binary_full_count == 4
    assert status.qwen_confirm_count == 1
    assert status.qwen_deny_count == 1
    assert status.qwen_review_count == 2
    assert status.qwen_unresolved_count == 0
    assert status.binary_full_count == status.qwen_confirm_count + status.qwen_deny_count + status.qwen_review_count
    assert (tmp_path / "event" / "binary-classification" / "full" / event_a.incident_id / "binary_event.json").exists()
    assert (tmp_path / "event" / "qwen" / "confirm" / event_a.incident_id / "qwen_review.json").exists()
    assert (tmp_path / "event" / "qwen" / "deny" / event_b.incident_id / "qwen_review.json").exists()
    assert (tmp_path / "event" / "qwen" / "review" / event_c.incident_id / "qwen_review.json").exists()
    assert (tmp_path / "event" / "qwen" / "review" / event_d.incident_id / "qwen_review.json").exists()
    qwen_review = json.loads(
        (
            tmp_path
            / "event"
            / "qwen"
            / "confirm"
            / event_a.incident_id
            / "qwen_review.json"
        ).read_text(encoding="utf-8")
    )
    assert {
        "occlusion",
        "scene_risks",
        "possible_help_gesture",
        "summary",
        "review_points",
        "confidence",
    }.issubset(set(qwen_review))
    assert qwen_review["analysis_status"] == "completed"
    assert qwen_review["fall_verdict"] == "confirmed_fall"


def test_manual_session_does_not_auto_complete_at_zero_seconds(tmp_path) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"))

    status = archive.start_manual_session("camera_01")
    time.sleep(0.05)
    refreshed = archive.status()

    assert status.manual_session is True
    assert refreshed.running is True
    assert refreshed.state == "running"
    assert refreshed.remaining_seconds == 0
    assert (tmp_path / "event" / "test_sessions" / status.test_session_id / "session.json").exists()


@pytest.mark.parametrize(
    ("verdict", "expected_label", "expected_real_fall"),
    [
        ("confirmed_fall", "真实跌倒", True),
        ("intentional_low_posture", "非真实跌倒", False),
        ("normal_activity", "非真实跌倒", False),
        ("non_fall", "非真实跌倒", False),
        ("unclear", "无法明确判断", None),
        ("uncertain", "无法明确判断", None),
        ("insufficient_visual_evidence", "视觉证据不足", None),
    ],
)
def test_presentation_result_maps_qwen_verdict_without_false_unknowns(
    tmp_path,
    verdict,
    expected_label,
    expected_real_fall,
) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"))
    status = archive.start_manual_session("camera_01")
    event = _event(f"pfv2-camera_01-{verdict}", verdict)

    assert archive.archive_binary_event(event, _package(event), [])
    archive.archive_qwen_result(event)

    session_dir = tmp_path / "event" / "test_sessions" / status.test_session_id
    presentation = json.loads((session_dir / "presentation_result.json").read_text(encoding="utf-8"))
    assert presentation["fall_label_zh"] == expected_label
    assert presentation["is_real_fall"] is expected_real_fall
    assert presentation["fall_verdict"] == verdict
    assert "time_description_zh" in presentation


def test_test_archive_persists_final_safety_decision_with_qwen_result(tmp_path) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"))
    archive.start_test(60)
    event = _event("pfv2-camera_01-final", "unclear")
    event = replace(
        event,
        safety_decision=FallSafetyDecision(
            outcome="alert",
            path="post_fall_persistent_abnormality",
            alert_level="high",
            reason="persistent_post_fall_abnormality_without_intentional_evidence",
            observation_elapsed_ms=15000,
        ),
    )
    images = [QwenImageInput(offset_ms=0, role="trigger", image_bytes=b"jpeg")]

    assert archive.archive_binary_event(event, _package(event), images)
    assert archive.archive_qwen_result(event) == "review"

    session_dir = tmp_path / "event" / "test_sessions" / archive.status().test_session_id
    events = json.loads((session_dir / "events.json").read_text(encoding="utf-8"))
    assert events[0]["event"]["safety_decision"]["outcome"] == "alert"
    assert events[0]["event"]["safety_decision"]["path"] == "post_fall_persistent_abnormality"


def test_test_archive_records_binary_non_fall_without_creating_full_event(tmp_path) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"))
    archive.start_test(60)
    binary = BinaryFrameResult(
        frame_id="camera_01_1",
        camera_id="camera_01",
        frame_seq=1,
        captured_at="2026-08-25T00:00:00.000+00:00",
        inferred_at="2026-08-25T00:00:00.100+00:00",
        fall_probability=0.1,
        non_fall_probability=0.9,
        raw_label="noFall",
        decision_label="NON_FALL",
        threshold=0.4,
        model_name="efficientnet_b0",
        model_version="testsha",
        valid=True,
        source_width=640,
        source_height=360,
    )
    raw = SimpleNamespace(
        model=SimpleNamespace(provider="CUDAExecutionProvider"),
        performance=SimpleNamespace(inference_ms=3.5, total_ms=5.0),
    )
    archive.archive_binary_frame(binary, _decision(binary), raw, SimpleNamespace(captured_monotonic=time.monotonic()))

    status = archive.status()
    assert status.binary_other_count == 1
    assert status.binary_non_fall_count == 1
    assert status.binary_fall_count == 0
    assert status.binary_full_count == 0
    assert len(list((tmp_path / "event" / "binary-classification" / "other").glob("*.json"))) == 1
    summary = json.loads(
        (
            tmp_path
            / "event"
            / "test_sessions"
            / status.test_session_id
            / "session_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["frames_processed"] == 1
    assert summary["binary_non_fall_count"] == 1
    csv_header = (
        tmp_path
        / "event"
        / "test_sessions"
        / status.test_session_id
        / "binary_predictions.csv"
    ).read_text(encoding="utf-8").splitlines()[0]
    assert "frame_age_ms" in csv_header
    assert "provider" in csv_header
    assert "inference_ms" in csv_header
    csv_row = (
        tmp_path
        / "event"
        / "test_sessions"
        / status.test_session_id
        / "binary_predictions.csv"
    ).read_text(encoding="utf-8").splitlines()[1]
    assert "CUDAExecutionProvider" in csv_row
    assert "3.5" in csv_row


def test_stop_test_drains_known_binary_event_until_qwen_result(tmp_path) -> None:
    archive = PostFallTestArchiveService(str(tmp_path / "event"), performance_sample_interval_seconds=60)
    status = archive.start_test(60)
    event = replace(_event("pfv2-camera_01-drain", "unclear"), vlm_status="pending", vlm_analysis=None)
    package = _package(event)

    assert archive.archive_binary_event(event, package, [])
    assert archive.status().qwen_unresolved_count == 1
    stopped = archive.stop_test()

    assert stopped.running is False
    assert stopped.state == "draining"
    assert archive.archive_qwen_result(_event(event.incident_id, "confirmed_fall")) == "confirm"

    final = archive.status()
    assert final.state == "completed"
    assert final.qwen_unresolved_count == 0
    session_dir = tmp_path / "event" / "test_sessions" / status.test_session_id
    assert (session_dir / "session_summary.json").exists()
    assert (session_dir / "events.json").exists()
    assert (session_dir / "binary_predictions.csv").exists()
    assert (session_dir / "performance.csv").exists()
    assert (session_dir / "test.log").exists()
    assert (tmp_path / "event" / "camera_01" / event.incident_id / "event.json").exists()


def test_stop_test_drain_timeout_keeps_event_and_completes_session(tmp_path) -> None:
    archive = PostFallTestArchiveService(
        str(tmp_path / "event"),
        performance_sample_interval_seconds=60,
        drain_timeout_seconds=1,
    )
    status = archive.start_test(60)
    event = replace(_event("pfv2-camera_01-timeout", "unclear"), vlm_status="pending", vlm_analysis=None)

    assert archive.archive_binary_event(event, _package(event), [])
    assert archive.stop_test().state == "draining"

    time.sleep(1.1)
    final = archive.status()

    assert final.state == "completed"
    assert final.qwen_unresolved_count == 0
    assert final.qwen_timeout_count == 1
    session_dir = tmp_path / "event" / "test_sessions" / status.test_session_id
    summary = json.loads((session_dir / "session_summary.json").read_text(encoding="utf-8"))
    events = json.loads((session_dir / "events.json").read_text(encoding="utf-8"))
    qwen = json.loads(
        (
            tmp_path
            / "event"
            / "qwen"
            / "review"
            / event.incident_id
            / "qwen_review.json"
        ).read_text(encoding="utf-8")
    )
    incident = json.loads((tmp_path / "event" / "camera_01" / event.incident_id / "event.json").read_text(encoding="utf-8"))
    assert summary["qwen_timeout"] == 1
    assert events[0]["stage"] == "qwen_timeout"
    assert set(qwen) == {
        "occlusion",
        "scene_risks",
        "possible_help_gesture",
        "summary",
        "review_points",
        "confidence",
    }
    assert incident["analysis_status"] == "timeout"


def _event(incident_id: str, verdict: str, *, analysis_status: str = "completed") -> FallEvent:
    detail = FallDetailResult(
        incident_id=incident_id,
        analysis_status=analysis_status,
        fall_verdict=verdict,
        posture="人员倒地" if verdict == "confirmed_fall" else "主动低姿态",
        summary="测试摘要",
    )
    return FallEvent(
        incident_id=incident_id,
        camera_id="camera_01",
        state="fall_confirmed",
        started_at="2026-08-25T00:00:00.000+00:00",
        confirmed_at="2026-08-25T00:00:01.000+00:00",
        binary_evidence={"max_fall_probability": 0.9, "threshold": 0.4},
        vlm_status="completed",
        vlm_analysis=detail,
    )


def _package(event: FallEvent) -> KeyframePackage:
    return KeyframePackage(
        incident_id=event.incident_id,
        camera_id=event.camera_id,
        confirmed_at=event.confirmed_at,
        source_width=640,
        source_height=360,
        frames=[KeyframeItem("trigger", 0, "frame-1", 1, event.confirmed_at)],
        fall_probability_summary=event.binary_evidence,
    )


def _decision(binary: BinaryFrameResult) -> BinaryAggregateDecision:
    return BinaryAggregateDecision(
        state="NORMAL",
        camera_id=binary.camera_id,
        frame_id=binary.frame_id,
        frame_seq=binary.frame_seq,
        decision_label=binary.decision_label,
        fall_probability=binary.fall_probability,
        incident_id=None,
        event_created=False,
        rearmed=False,
        evidence=BinaryDecisionEvidence(
            window_size=1,
            positive_count=0,
            consecutive_positive_count=0,
            mean_fall_probability=binary.fall_probability,
            max_fall_probability=binary.fall_probability,
            candidate_duration_ms=0,
            threshold=binary.threshold,
        ),
        reason="non_fall",
        updated_at=binary.inferred_at,
    )
