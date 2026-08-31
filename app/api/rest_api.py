from __future__ import annotations

import socket
import time

import cv2
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_runtime
from app.camera.frame_freshness import FreshnessThresholds, frame_freshness
from app.camera.source_models import is_mjpeg_source, is_mock_source, is_rtsp_source, mask_source_url
from app.core.runtime import Runtime
from app.streaming.display_frame_cache import get_display_frame_cache
from app.schemas.stream import (
    StreamControlResponse,
    StreamHostSwitchRequest,
    MockStreamFaultRequest,
    StreamProbeRequest,
    StreamProbeResponse,
    StreamRuntimeSourceResponse,
    StreamStartRequest,
    StreamStopRequest,
)

router = APIRouter(tags=["stream"])


@router.post("/stream/start", response_model=StreamControlResponse)
def start_stream(
    request: StreamStartRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamControlResponse:
    try:
        created, message = runtime.stream_service.start(
            request.camera_id,
            request.source_url or request.rtsp_url,
            main_source_url=request.main_rtsp_url,
            analysis_source_url=request.analysis_rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    stream_runtime = runtime.source_manager.get_runtime(request.camera_id)
    source_url = stream_runtime.config.source_url if stream_runtime else None
    status = "started"
    if message == "stream already running":
        status = "running"
    elif message == "stream restarted":
        status = "restarted"
    return StreamControlResponse(
        camera_id=request.camera_id,
        status=status,
        message=message,
        source_url=mask_source_url(source_url),
        main_rtsp_url=mask_source_url(source_url),
        analysis_rtsp_url=mask_source_url(source_url),
    )


@router.get("/stream/source", response_model=StreamRuntimeSourceResponse)
def stream_source(
    camera_id: str = "camera_01",
    runtime: Runtime = Depends(get_runtime),
) -> StreamRuntimeSourceResponse:
    stream_runtime = runtime.source_manager.get_runtime(camera_id)
    if stream_runtime is None:
        return StreamRuntimeSourceResponse(
            camera_id=camera_id,
            running=False,
            dual_stream_enabled=False,
            display_source_current="none",
            display_fallback_active=False,
            message="camera is not running",
        )

    worker_status = runtime.source_manager.worker_status(camera_id)
    return StreamRuntimeSourceResponse(
        camera_id=camera_id,
        running=worker_status.running if worker_status else False,
        dual_stream_enabled=False,
        display_source_current="single",
        display_fallback_active=False,
        main_rtsp_url_masked=mask_source_url(stream_runtime.config.source_url),
        analysis_rtsp_url_masked=mask_source_url(stream_runtime.config.source_url),
        source_url_masked=mask_source_url(stream_runtime.config.source_url),
        source_protocol=_source_protocol(stream_runtime.config.source_url),
        main_stream_state=worker_status.stream_state if worker_status else None,
        analysis_stream_state=worker_status.stream_state if worker_status else None,
        main_connected=worker_status.connected if worker_status else None,
        analysis_connected=worker_status.connected if worker_status else None,
        main_frame_age_ms=worker_status.frame_age_ms if worker_status else None,
        analysis_frame_age_ms=worker_status.frame_age_ms if worker_status else None,
        main_capture_fps=worker_status.capture_fps if worker_status else None,
        analysis_capture_fps=worker_status.capture_fps if worker_status else None,
        frame_status=worker_status.frame_status if worker_status else None,
        source_generation=worker_status.source_generation if worker_status else None,
    )


@router.get("/stream/latest-frame.jpg")
def latest_stream_frame(
    camera_id: str = "camera_01",
    display: bool = False,
    runtime: Runtime = Depends(get_runtime),
) -> Response:
    buffer = runtime.source_manager.get_buffer(camera_id)
    packet = buffer.latest() if buffer else None
    if packet is None:
        worker_status = runtime.source_manager.worker_status(camera_id)
        reason = "no_frame"
        if worker_status is not None and worker_status.stream_state in {"stopped", "reconnecting", "unreachable", "authentication_failed", "decode_error"}:
            reason = worker_status.stream_state
        raise HTTPException(status_code=404, detail={
            "code": "LATEST_FRAME_NOT_AVAILABLE",
            "camera_id": camera_id,
            "frame_status": "no_frame",
            "reason": reason,
            "safe_to_interpret_as_no_fall": False,
        })
    thresholds = FreshnessThresholds(
        delayed_ms=runtime.settings.frame_delayed_threshold_ms,
        stale_ms=runtime.settings.stream_stale_threshold_ms,
    )
    freshness = frame_freshness(packet.age_ms, thresholds)
    content = packet.jpeg_bytes
    resized_for_display = False
    if display:
        resized_for_display = int(runtime.settings.display_frame_height or 0) > 0 and packet.height > runtime.settings.display_frame_height
        try:
            display_entry = get_display_frame_cache().render(packet, runtime.settings)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        content = display_entry.content
        get_display_frame_cache().mark_served(camera_id, consumer="latest_frame")
    elif content is None:
        ok, encoded = cv2.imencode(".jpg", packet.frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise HTTPException(status_code=500, detail="LATEST_FRAME_ENCODE_FAILED")
        content = encoded.tobytes()
    headers = {
        "X-Camera-Id": camera_id,
        "X-Frame-Id": str(packet.seq),
        "X-Frame-Seq": str(packet.seq),
        "X-Frame-Age-Ms": str(packet.age_ms),
        "X-Frame-Status": freshness.frame_status,
        "X-Source-Generation": str(packet.source_generation),
        "X-Frame-Is-Stale": "true" if freshness.is_stale else "false",
        "X-Frame-Captured-At": packet.captured_at_iso,
        "X-Frame-Received-At": packet.received_at_iso,
        "X-Source-Protocol": _source_protocol(packet.source),
        "X-Raw-Jpeg-Reused": "true" if packet.jpeg_bytes is not None else "false",
    }
    if display:
        headers.update(
            {
                "X-Display-Resized": "true" if resized_for_display else "false",
                "X-Display-Cache-Hit": "true" if display_entry.cache_hit else "false",
                "X-Display-Encode-Ms": str(display_entry.encode_ms),
            }
        )
    return Response(content=content, media_type="image/jpeg", headers=headers)


@router.get("/stream/display.mjpg")
def display_stream(
    camera_id: str = "camera_01",
    fps: float | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    configured_fps = fps if fps is not None else getattr(runtime.settings, "display_mjpeg_fps", None)
    target_fps = max(1.0, min(float(configured_fps or runtime.settings.webrtc_video_fps or 12), 30.0))
    interval = 1.0 / target_fps
    boundary = "visiondisplay"

    def frames():
        last_seq = 0
        while True:
            started = time.monotonic()
            buffer = runtime.source_manager.get_buffer(camera_id)
            packet = buffer.latest() if buffer else None
            if packet is not None and packet.seq != last_seq:
                try:
                    display_entry = get_display_frame_cache().render(packet, runtime.settings)
                except ValueError:
                    continue
                content = display_entry.content
                last_seq = packet.seq
                get_display_frame_cache().mark_served(camera_id, consumer="display_mjpg")
                yield (
                    f"--{boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"X-Camera-Id: {camera_id}\r\n"
                    f"X-Frame-Seq: {packet.seq}\r\n"
                    f"X-Frame-Age-Ms: {packet.age_ms}\r\n"
                    f"X-Display-Cache-Hit: {'true' if display_entry.cache_hit else 'false'}\r\n"
                    f"X-Display-Encode-Ms: {display_entry.encode_ms}\r\n"
                    f"Content-Length: {len(content)}\r\n\r\n"
                ).encode("ascii") + content + b"\r\n"
            elapsed = time.monotonic() - started
            time.sleep(max(0.005, interval - elapsed))

    return StreamingResponse(
        frames(),
        media_type=f"multipart/x-mixed-replace; boundary={boundary}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-Display-Target-Fps": str(target_fps),
        },
    )


@router.post("/stream/mock-fault", response_model=StreamControlResponse)
def set_mock_stream_fault(
    request: MockStreamFaultRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamControlResponse:
    if runtime.settings.runtime_profile != "safe_demo":
        raise HTTPException(status_code=403, detail="MOCK_FAULT_ONLY_ALLOWED_IN_SAFE_DEMO")
    stream_runtime = runtime.source_manager.get_runtime(request.camera_id)
    if stream_runtime is None or not is_mock_source(stream_runtime.config.source_url):
        raise HTTPException(status_code=409, detail="MOCK_FAULT_REQUIRES_ACTIVE_MOCK_SOURCE")
    mode = runtime.source_manager.set_mock_fault(request.camera_id, request.mode)
    worker_status = runtime.source_manager.worker_status(request.camera_id)
    return StreamControlResponse(
        camera_id=request.camera_id,
        status=mode,
        message=f"mock fault mode set to {mode}",
        main_rtsp_url=mask_source_url(stream_runtime.config.source_url),
        analysis_rtsp_url=mask_source_url(stream_runtime.config.source_url),
    )


@router.post("/stream/switch-host", response_model=StreamControlResponse)
def switch_stream_host(
    request: StreamHostSwitchRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamControlResponse:
    main_rtsp_url = _build_rtsp_url(
        scheme=request.scheme,
        username=request.username,
        password=request.password,
        host=request.host,
        port=request.port,
        path=request.main_path,
    )
    analysis_rtsp_url = _build_rtsp_url(
        scheme=request.scheme,
        username=request.username,
        password=request.password,
        host=request.host,
        port=request.port,
        path=request.analysis_path,
    )
    try:
        _, message = runtime.stream_service.start(
            request.camera_id,
            analysis_rtsp_url,
            main_source_url=main_rtsp_url,
            analysis_source_url=analysis_rtsp_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return StreamControlResponse(
        camera_id=request.camera_id,
        status="restarted",
        message=message,
        main_rtsp_url=mask_source_url(main_rtsp_url),
        analysis_rtsp_url=mask_source_url(analysis_rtsp_url),
    )


@router.post("/stream/probe", response_model=StreamProbeResponse)
def probe_stream_host(request: StreamProbeRequest) -> StreamProbeResponse:
    started = time.monotonic()
    try:
        with socket.create_connection(
            (request.host, request.port),
            timeout=request.timeout_ms / 1000,
        ):
            elapsed_ms = round((time.monotonic() - started) * 1000, 2)
            return StreamProbeResponse(
                host=request.host,
                port=request.port,
                reachable=True,
                elapsed_ms=elapsed_ms,
            )
    except OSError as exc:
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        return StreamProbeResponse(
            host=request.host,
            port=request.port,
            reachable=False,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )


@router.post("/stream/stop", response_model=StreamControlResponse)
def stop_stream(
    request: StreamStopRequest,
    runtime: Runtime = Depends(get_runtime),
) -> StreamControlResponse:
    stopped = runtime.stream_service.stop(request.camera_id)
    return StreamControlResponse(
        camera_id=request.camera_id,
        status="stopped" if stopped else "not_found",
        message="stream stopped" if stopped else "stream was not running",
    )


def _build_rtsp_url(
    *,
    scheme: str,
    username: str,
    password: str,
    host: str,
    port: int,
    path: str,
) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{scheme}://{username}:{password}@{host}:{port}{normalized_path}"


def _source_protocol(source_url_or_kind: str | None) -> str:
    if source_url_or_kind == "mjpeg" or is_mjpeg_source(source_url_or_kind):
        return "mjpeg"
    if source_url_or_kind == "rtsp" or is_rtsp_source(source_url_or_kind):
        return "rtsp"
    if source_url_or_kind == "mock" or is_mock_source(source_url_or_kind):
        return "mock"
    if source_url_or_kind == "file":
        return "file"
    return "unknown"
