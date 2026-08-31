from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.core.config import Settings
from app.post_fall_v2.detection_session_orchestrator import DetectionSessionOrchestrator
from app.post_fall_v2.test_archive_service import ArchiveStatus


def _archive_status(*, state: str = "idle", running: bool = False) -> ArchiveStatus:
    return ArchiveStatus(
        running=running,
        test_session_id="session-1" if state != "idle" else None,
        total_seconds=0,
        remaining_seconds=0,
        event_root="events",
        binary_full_count=0,
        binary_other_count=0,
        qwen_confirm_count=0,
        qwen_deny_count=0,
        qwen_review_count=0,
        qwen_unresolved_count=0,
        tracked_binary_event_ids=[],
        state=state,
        camera_id="go2_front_camera",
    )


class _StreamService:
    def __init__(self) -> None:
        self.started: list[tuple[str, str | None]] = []
        self.stopped: list[str] = []

    def start(self, camera_id: str, source_url: str | None) -> tuple[bool, str]:
        self.started.append((camera_id, source_url))
        return True, "stream started"

    def stop(self, camera_id: str) -> bool:
        self.stopped.append(camera_id)
        return True


class _ArchiveService:
    def __init__(self) -> None:
        self.state = "idle"
        self.failed: tuple[str, str] | None = None

    def start_manual_session(self, camera_id: str) -> ArchiveStatus:
        self.state = "starting"
        return self.status()

    def mark_running(self) -> ArchiveStatus:
        self.state = "running"
        return self.status()

    def mark_failed(self, stage: str, reason: str) -> ArchiveStatus:
        self.state = "failed"
        self.failed = (stage, reason)
        return self.status()

    def stop_test(self) -> ArchiveStatus:
        self.state = "completed"
        return self.status()

    def status(self) -> ArchiveStatus:
        return _archive_status(state=self.state, running=self.state == "running")


class _PostFallService:
    def __init__(self) -> None:
        self.binary_toggles: list[tuple[str, bool]] = []
        self.qwen_toggles: list[tuple[str, bool]] = []
        self.source_manager = SimpleNamespace(worker_status=lambda camera_id: None)

    def set_binary_enabled(self, camera_id: str, enabled: bool) -> dict:
        self.binary_toggles.append((camera_id, enabled))
        return {"binary_enabled": enabled}

    def set_qwen_enabled(self, camera_id: str, enabled: bool) -> dict:
        self.qwen_toggles.append((camera_id, enabled))
        return {"qwen_enabled": enabled}

    def control_status(self, camera_id: str) -> dict:
        return {
            "camera_id": camera_id,
            "stream_connected": False,
            "binary_enabled": False,
            "binary_requested": False,
            "qwen_enabled": False,
            "qwen_requested": False,
            "runtime": {},
            "test": {"test_session_id": "session-1", "state": "failed", "qwen_unresolved_count": 0},
        }


def test_failed_session_start_preserves_video_stream_for_recovery(monkeypatch) -> None:
    stream_service = _StreamService()
    post_fall_service = _PostFallService()
    archive_service = _ArchiveService()
    orchestrator = DetectionSessionOrchestrator(
        settings=replace(
            Settings(),
            default_camera_id="go2_front_camera",
            video_source_mode="mjpeg",
            go2_mjpeg_url="http://192.168.8.254:8093/stream.mjpg",
        ),
        stream_service=stream_service,
        post_fall_service=post_fall_service,
        archive_service=archive_service,
    )

    monkeypatch.setattr(
        orchestrator,
        "_wait_for_video_ready",
        lambda camera_id: (_ for _ in ()).throw(RuntimeError("video source not ready")),
    )

    status = orchestrator.start(camera_id="go2_front_camera")

    assert status["state"] == "FAILED"
    assert stream_service.started == [("go2_front_camera", "http://192.168.8.254:8093/stream.mjpg")]
    assert stream_service.stopped == []
    assert post_fall_service.qwen_toggles == [("go2_front_camera", False)]
    assert post_fall_service.binary_toggles == [("go2_front_camera", False)]
    assert archive_service.failed == ("startup", "video source not ready")


def test_manual_session_stop_still_stops_video_stream() -> None:
    stream_service = _StreamService()
    post_fall_service = _PostFallService()
    archive_service = _ArchiveService()
    archive_service.state = "running"
    orchestrator = DetectionSessionOrchestrator(
        settings=replace(Settings(), default_camera_id="go2_front_camera"),
        stream_service=stream_service,
        post_fall_service=post_fall_service,
        archive_service=archive_service,
    )

    orchestrator.stop(camera_id="go2_front_camera")

    assert stream_service.stopped == ["go2_front_camera"]
