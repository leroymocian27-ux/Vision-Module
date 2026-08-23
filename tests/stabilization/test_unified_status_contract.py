from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.integration_api import latest_result
from app.fall.status_contract import camera_unavailable_reason, confidence_level, normalize_fall_state
from app.schemas.status import LatestResultStatus
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.status_service import StatusService


def _worker(
    *,
    frame_status: str = "fresh",
    stream_state: str = "streaming",
    running: bool = True,
    connected: bool = True,
    reconnect_reason: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        running=running,
        connected=connected,
        frame_status=frame_status,
        stream_state=stream_state,
        frame_age_ms=10.0,
        capture_fps=12.0,
        source_generation=1,
        reconnect_reason=reconnect_reason,
    )


def _runtime(worker_status: SimpleNamespace | None, result: VisionResult) -> SimpleNamespace:
    return SimpleNamespace(
        realtime_store=SimpleNamespace(latest_published=lambda camera_id: result if camera_id == "camera_01" else None),
        source_manager=SimpleNamespace(worker_status=lambda camera_id: worker_status),
        fall_event_reporter=SimpleNamespace(latest_alert=lambda camera_id: None),
        result_publisher_service=SimpleNamespace(status_fps=lambda camera_id: 10.0),
    )


def _result(person: DetectedObject) -> VisionResult:
    return VisionResult(
        camera_id="camera_01",
        timestamp="2026-07-20T00:00:00Z",
        frame_seq=1,
        frame_width=640,
        frame_height=360,
        objects=[person],
        detector={"evidence_freshness": {"detection": "fresh", "tracking": "fresh"}},
    )


def test_status_contract_core_values_are_stable():
    assert normalize_fall_state(None) == "normal"
    assert normalize_fall_state("fallen_candidate") == "fall_candidate"
    assert normalize_fall_state("fallen_confirmed") == "fall_confirmed"
    assert confidence_level(fall_state="normal", fall_probability=0.1, safe_to_interpret_as_no_fall=True) == "low"
    assert confidence_level(fall_state="unavailable", fall_probability=None, safe_to_interpret_as_no_fall=False) == "unavailable"
    assert camera_unavailable_reason(_worker(frame_status="stale", stream_state="stale")) == "frame_stale"
    assert camera_unavailable_reason(_worker()) is None
    assert (
        camera_unavailable_reason(
            _worker(frame_status="stale", stream_state="stopped", running=False, connected=False, reconnect_reason="eof")
        )
        == "end_of_file"
    )


def test_status_latest_result_no_frame_is_unavailable_and_unsafe():
    service = StatusService.__new__(StatusService)
    status = LatestResultStatus(camera_id="camera_01", fall_state="normal", safe_to_interpret_as_no_fall=True)

    unavailable = service._apply_camera_availability_guard(  # type: ignore[attr-defined]
        status,
        _worker(frame_status="no_frame", stream_state="connected"),
    )

    assert unavailable.fall_state == "unavailable"
    assert unavailable.reason == "no_frame"
    assert unavailable.safe_to_interpret_as_no_fall is False
    assert unavailable.alarm_confirmed is False
    assert unavailable.confidence_level == "unavailable"
    assert "no_frame" in unavailable.degraded_by


def test_status_latest_result_eof_is_end_of_file_and_unsafe():
    service = StatusService.__new__(StatusService)
    status = LatestResultStatus(camera_id="camera_01", fall_state="normal", safe_to_interpret_as_no_fall=True)

    unavailable = service._apply_camera_availability_guard(  # type: ignore[attr-defined]
        status,
        _worker(frame_status="stale", stream_state="stopped", running=False, connected=False, reconnect_reason="eof"),
    )

    assert unavailable.fall_state == "unavailable"
    assert unavailable.reason == "end_of_file"
    assert unavailable.safe_to_interpret_as_no_fall is False
    assert unavailable.alarm_confirmed is False
    assert unavailable.confidence_level == "unavailable"
    assert "end_of_file" in unavailable.degraded_by


def test_integration_latest_result_stale_frame_is_unavailable_and_unsafe():
    person = DetectedObject(
        label="person",
        confidence=0.9,
        bbox=[10.0, 20.0, 120.0, 220.0],
        track_id=1,
        is_target=True,
        fall_decision={"fall_state": "fallen_confirmed", "risk_level": "critical", "fall_probability": 0.9},
        alarm_preview={"confirmed": True, "risk_level": "critical", "fall_probability": 0.9},
    )

    payload = latest_result(
        "camera_01",
        runtime=_runtime(_worker(frame_status="stale", stream_state="stale"), _result(person)),
    )

    assert payload.fall_state == "unavailable"
    assert payload.status == "unavailable"
    assert payload.fall_detected is False
    assert payload.alarm_confirmed is False
    assert payload.reason == "frame_stale"
    assert payload.safe_to_interpret_as_no_fall is False
    assert payload.confidence_level == "unavailable"
    assert "frame_stale" in payload.degraded_by


def test_integration_latest_result_normal_frame_is_safe_normal_with_pose_degraded():
    person = DetectedObject(
        label="person",
        confidence=0.9,
        bbox=[10.0, 20.0, 120.0, 220.0],
        track_id=1,
        is_target=True,
        pose={"pose_provider": "disabled_placeholder", "keypoints": [], "debug": {"pose_disabled": True}},
    )

    payload = latest_result("camera_01", runtime=_runtime(_worker(), _result(person)))

    assert payload.fall_state == "normal"
    assert payload.status == "normal"
    assert payload.safe_to_interpret_as_no_fall is True
    assert payload.fall_detected is False
    assert payload.confidence_level == "low"
    assert "pose_disabled" in payload.degraded_by


def test_integration_latest_result_missing_result_remains_not_ready():
    with pytest.raises(Exception) as exc:
        latest_result("missing", runtime=_runtime(_worker(), _result(DetectedObject(confidence=0.1, bbox=[0, 0, 1, 1]))))

    assert "VISION_RESULT_NOT_READY" in str(exc.value)
