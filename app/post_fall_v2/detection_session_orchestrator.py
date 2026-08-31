from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.services.stream_service import StreamService


@dataclass(frozen=True)
class DetectionSessionStatus:
    state: str
    camera_id: str
    session_id: str | None
    started_at: str | None
    running_at: str | None
    stop_requested_at: str | None
    finalized_at: str | None
    elapsed_seconds: float | None
    failure_stage: str | None
    failure_reason: str | None
    components: dict[str, Any]
    archive: dict[str, Any] | None
    presentation_result: dict[str, Any] | None


class DetectionSessionOrchestrator:
    """One-button presentation session controller.

    This class only coordinates existing services. It does not change binary,
    Qwen, event, alarm, WebRTC, or MJPEG business logic.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        stream_service: StreamService,
        post_fall_service: PostFallV2RuntimeService,
        archive_service: PostFallTestArchiveService,
        video_ready_timeout_seconds: float = 10.0,
        stop_drain_wait_seconds: float = 15.0,
    ) -> None:
        self.settings = settings
        self.stream_service = stream_service
        self.post_fall_service = post_fall_service
        self.archive_service = archive_service
        self.video_ready_timeout_seconds = max(1.0, float(video_ready_timeout_seconds))
        self.stop_drain_wait_seconds = max(1.0, float(stop_drain_wait_seconds))
        self._lock = threading.RLock()
        self._state = "IDLE"
        self._camera_id = settings.default_camera_id
        self._failure_stage: str | None = None
        self._failure_reason: str | None = None

    def start(self, camera_id: str | None = None, source_url: str | None = None) -> dict[str, Any]:
        selected_camera_id = (camera_id or self._camera_id or self.settings.default_camera_id).strip() or "camera_01"
        selected_source_url = source_url or self._default_source_url()
        with self._lock:
            self._sync_state_from_archive_locked()
            if self._state in {"STARTING", "RUNNING", "STOPPING"}:
                return self.status(selected_camera_id)
            self._state = "STARTING"
            self._camera_id = selected_camera_id
            self._failure_stage = None
            self._failure_reason = None
            self.archive_service.start_manual_session(selected_camera_id)

        try:
            self.stream_service.start(selected_camera_id, selected_source_url)
            self._wait_for_video_ready(selected_camera_id)
            binary_status = self.post_fall_service.set_binary_enabled(selected_camera_id, True)
            if not binary_status.get("binary_enabled"):
                raise RuntimeError("二分类模型未进入运行状态")
            qwen_status = self.post_fall_service.set_qwen_enabled(selected_camera_id, True)
            if not qwen_status.get("qwen_enabled"):
                raise RuntimeError("千问复核未进入待机状态")
            self.archive_service.mark_running()
            with self._lock:
                self._state = "RUNNING"
            return self.status(selected_camera_id)
        except Exception as exc:
            self._rollback_failed_start(selected_camera_id, str(exc))
            return self.status(selected_camera_id)

    def stop(self, camera_id: str | None = None) -> dict[str, Any]:
        selected_camera_id = (camera_id or self._camera_id or self.settings.default_camera_id).strip() or "camera_01"
        with self._lock:
            self._sync_state_from_archive_locked()
            if self._state == "IDLE":
                return self.status(selected_camera_id)
            if self._state == "COMPLETED":
                return self.status(selected_camera_id)
            if self._state == "FAILED":
                return self.status(selected_camera_id)
            self._state = "STOPPING"
        self.archive_service.stop_test()
        self._wait_for_archive_drain()
        try:
            self.post_fall_service.set_qwen_enabled(selected_camera_id, False)
        except Exception:
            pass
        try:
            self.post_fall_service.set_binary_enabled(selected_camera_id, False)
        except Exception:
            pass
        try:
            self.stream_service.stop(selected_camera_id)
        except Exception:
            pass
        with self._lock:
            self._sync_state_from_archive_locked()
            if self._state == "STOPPING" and not self.archive_service.status().qwen_unresolved_count:
                self._state = "COMPLETED"
        return self.status(selected_camera_id)

    def status(self, camera_id: str | None = None) -> dict[str, Any]:
        selected_camera_id = (camera_id or self._camera_id or self.settings.default_camera_id).strip() or "camera_01"
        with self._lock:
            self._sync_state_from_archive_locked()
            self._camera_id = selected_camera_id
            archive_status = self.archive_service.status()
            control = self.post_fall_service.control_status(selected_camera_id)
            components = self._component_status(selected_camera_id, control)
            started_at = archive_status.started_at
            finalized_at = archive_status.finalized_at
            stop_requested_at = archive_status.stopped_at
            status = DetectionSessionStatus(
                state=self._state,
                camera_id=selected_camera_id,
                session_id=archive_status.test_session_id,
                started_at=started_at,
                running_at=archive_status.running_at,
                stop_requested_at=stop_requested_at,
                finalized_at=finalized_at,
                elapsed_seconds=_elapsed_seconds(started_at, finalized_at if self._state in {"COMPLETED", "FAILED"} else None),
                failure_stage=archive_status.failure_stage or self._failure_stage,
                failure_reason=archive_status.failure_reason or self._failure_reason,
                components=components,
                archive=archive_status.__dict__,
                presentation_result=archive_status.presentation_result,
            )
        return asdict(status)

    def _wait_for_video_ready(self, camera_id: str) -> None:
        deadline = time.monotonic() + self.video_ready_timeout_seconds
        while time.monotonic() < deadline:
            ready, reason = self._video_ready(camera_id)
            if ready:
                return
            time.sleep(0.2)
        _, reason = self._video_ready(camera_id)
        raise RuntimeError(f"视频源未就绪：{reason}")

    def _video_ready(self, camera_id: str) -> tuple[bool, str]:
        runtime = self.post_fall_service.source_manager.get_runtime(camera_id)
        worker = self.post_fall_service.source_manager.worker_status(camera_id)
        packet = runtime.frame_buffer.latest() if runtime is not None else None
        connected = bool(getattr(worker, "connected", False))
        frame_status = str(getattr(worker, "frame_status", "no_frame"))
        frame_seq = int(getattr(worker, "frame_seq", 0) or getattr(packet, "seq", 0) or 0)
        raw_jpeg_available = bool(getattr(worker, "raw_jpeg_available", False) or getattr(packet, "jpeg_bytes", None) is not None)
        fresh_enough = frame_status in {"fresh", "delayed"} or self.post_fall_service.stream_ready_for_processing(camera_id)
        if runtime is not None and packet is not None and connected and fresh_enough and frame_seq > 0:
            return True, "ready"
        return False, f"connected={connected}, frame_status={frame_status}, frame_seq={frame_seq}, raw_jpeg={raw_jpeg_available}"

    def _wait_for_archive_drain(self) -> None:
        deadline = time.monotonic() + self.stop_drain_wait_seconds
        while time.monotonic() < deadline:
            archive = self.archive_service.status()
            if archive.qwen_unresolved_count <= 0 and archive.state in {"completed", "failed"}:
                return
            time.sleep(0.25)

    def _rollback_failed_start(self, camera_id: str, reason: str) -> None:
        with self._lock:
            self._state = "FAILED"
            self._failure_stage = self._failure_stage or "startup"
            self._failure_reason = reason
        try:
            self.post_fall_service.set_qwen_enabled(camera_id, False)
        except Exception:
            pass
        try:
            self.post_fall_service.set_binary_enabled(camera_id, False)
        except Exception:
            pass
        self.archive_service.mark_failed(self._failure_stage or "startup", reason)

    def _sync_state_from_archive_locked(self) -> None:
        archive = self.archive_service.status()
        archive_state = str(archive.state or "idle").lower()
        if archive_state == "failed":
            self._state = "FAILED"
            return
        if self._state == "STARTING":
            return
        if archive_state == "draining":
            self._state = "STOPPING"
            return
        if archive_state == "completed" and self._state == "STOPPING":
            self._state = "COMPLETED"
            return
        if archive.running and self._state not in {"STOPPING", "FAILED"}:
            self._state = "RUNNING" if archive.running_at else "STARTING"
            return
        if not archive.test_session_id and self._state not in {"FAILED", "COMPLETED"}:
            self._state = "IDLE"

    def _component_status(self, camera_id: str, control: dict[str, Any]) -> dict[str, Any]:
        worker = self.post_fall_service.source_manager.worker_status(camera_id)
        return {
            "video": {
                "ready": bool(control.get("stream_connected")),
                "stream_state": getattr(worker, "stream_state", None),
                "frame_status": getattr(worker, "frame_status", None),
                "frame_seq": getattr(worker, "frame_seq", None),
                "raw_jpeg_available": getattr(worker, "raw_jpeg_available", None),
            },
            "binary": {
                "ready": bool(control.get("binary_enabled")),
                "requested": bool(control.get("binary_requested")),
            },
            "qwen": {
                "ready": bool(control.get("qwen_enabled")),
                "requested": bool(control.get("qwen_requested")),
                "active_count": (control.get("runtime") or {}).get("vlm_active_count"),
                "queue_depth": (control.get("runtime") or {}).get("vlm_queue_depth"),
            },
            "archive": {
                "ready": bool((control.get("test") or {}).get("test_session_id")),
                "state": (control.get("test") or {}).get("state"),
                "qwen_unresolved_count": (control.get("test") or {}).get("qwen_unresolved_count"),
            },
        }

    def _default_source_url(self) -> str | None:
        if self.settings.video_source_mode == "mjpeg" and self.settings.go2_mjpeg_url:
            return self.settings.go2_mjpeg_url
        return self.settings.default_rtsp_url


def _elapsed_seconds(started_at: str | None, ended_at: str | None = None) -> float | None:
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00")) if ended_at else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return round(max(0.0, (end - start).total_seconds()), 3)
