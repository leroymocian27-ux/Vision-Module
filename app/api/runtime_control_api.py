from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.post_fall_v2.model_log_bus import SUPPORTED_MODEL_LOG_KINDS, model_log_bus

router = APIRouter(prefix="/runtime-control", tags=["runtime-control"])


class ModelToggleRequest(BaseModel):
    camera_id: str = Field(default="camera_01")
    enabled: bool


class TestStartRequest(BaseModel):
    hours: int = Field(default=0, ge=0, le=24)
    minutes: int = Field(default=0, ge=0, le=59)
    seconds: int = Field(default=0, ge=0, le=59)

    @property
    def total_seconds(self) -> int:
        return self.hours * 3600 + self.minutes * 60 + self.seconds


@router.get("/status")
def control_status(
    camera_id: str = "camera_01",
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    service = _post_fall_service(runtime)
    return service.control_status(camera_id)


@router.get("/logs/{kind}")
def model_logs(
    kind: str,
    camera_id: str = "camera_01",
    tail: int = 100,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    _validate_model_kind(kind)
    service = _post_fall_service(runtime)
    return {
        "kind": kind,
        "camera_id": camera_id,
        "status": _model_status(kind, service.control_status(camera_id)),
        "events": model_log_bus.snapshot(kind, limit=max(0, min(tail, 500))),
    }


@router.get("/logs/{kind}/stream")
async def model_log_stream(
    kind: str,
    request: Request,
    camera_id: str = "camera_01",
    tail: int = 20,
    status_interval_seconds: float = 1.0,
    runtime: Runtime = Depends(get_runtime),
) -> StreamingResponse:
    _validate_model_kind(kind)
    service = _post_fall_service(runtime)
    interval = max(0.5, min(float(status_interval_seconds), 10.0))

    async def stream():
        snapshot = model_log_bus.snapshot(kind, limit=max(0, min(tail, 200)))
        last_seq = max((int(event.get("seq", 0)) for event in snapshot), default=0)
        yield _sse("status", _model_status(kind, service.control_status(camera_id)))
        for event in snapshot:
            yield _sse("log", event)
        while not await request.is_disconnected():
            for event in model_log_bus.since(kind, last_seq):
                last_seq = max(last_seq, int(event.get("seq", last_seq)))
                yield _sse("log", event)
            yield _sse("status", _model_status(kind, service.control_status(camera_id)))
            await asyncio.sleep(interval)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/binary")
def set_binary_model(
    request: ModelToggleRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    service = _post_fall_service(runtime)
    if request.enabled:
        if not service.stream_ready_for_processing(request.camera_id):
            raise HTTPException(status_code=409, detail="请先连接视频流。")
    try:
        return service.set_binary_enabled(request.camera_id, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/qwen")
def set_qwen_model(
    request: ModelToggleRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    try:
        return _post_fall_service(runtime).set_qwen_enabled(request.camera_id, request.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/test/start")
def start_test(
    request: TestStartRequest,
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    if request.total_seconds <= 0:
        raise HTTPException(status_code=422, detail="测试时间必须大于 0 秒。")
    archive = runtime.post_fall_test_archive_service
    if archive is None:
        raise HTTPException(status_code=503, detail="测试归档服务不可用。")
    return archive.start_test(request.total_seconds).__dict__


@router.post("/test/stop")
def stop_test(runtime: Runtime = Depends(get_runtime)) -> dict:
    archive = runtime.post_fall_test_archive_service
    if archive is None:
        raise HTTPException(status_code=503, detail="测试归档服务不可用。")
    return archive.stop_test().__dict__


def _post_fall_service(runtime: Runtime):
    service = runtime.post_fall_v2_runtime_service
    if service is None:
        raise HTTPException(status_code=503, detail="Post-Fall V2 runtime unavailable")
    return service


def _validate_model_kind(kind: str) -> None:
    if kind not in SUPPORTED_MODEL_LOG_KINDS:
        raise HTTPException(status_code=404, detail="unknown model log kind")


def _sse(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _model_status(kind: str, control: dict) -> dict:
    runtime = control.get("runtime") or {}
    if kind == "binary":
        enabled = bool(control.get("binary_enabled"))
        requested = bool(control.get("binary_requested"))
        return {
            "kind": "binary",
            "state": "running" if enabled else ("requested" if requested else "stopped"),
            "enabled": enabled,
            "requested": requested,
            "camera_id": control.get("camera_id"),
            "stream_connected": bool(control.get("stream_connected")),
            "provider": runtime.get("binary_provider"),
            "model_sha256": runtime.get("binary_model_sha256"),
            "active_providers": runtime.get("binary_active_providers"),
            "provider_degraded": bool(runtime.get("binary_provider_degraded")),
            "sample_fps": runtime.get("binary_sample_fps") or runtime.get("sample_fps"),
            "frames_processed": runtime.get("frames_processed"),
            "frames_dropped": runtime.get("frames_dropped"),
            "queue_depth": runtime.get("queue_depth"),
            "fall_probability": runtime.get("binary_last_probability"),
            "last_label": runtime.get("binary_last_label"),
            "latency_ms": runtime.get("binary_inference_latency_ms"),
            "avg_latency_ms": runtime.get("binary_inference_latency_avg_ms"),
            "frame_age_ms": runtime.get("frame_age_ms"),
            "last_error": runtime.get("last_error"),
        }
    enabled = bool(control.get("qwen_enabled"))
    requested = bool(control.get("qwen_requested"))
    return {
        "kind": "qwen",
        "state": "enabled" if enabled else ("requested" if requested else "stopped"),
        "enabled": enabled,
        "requested": requested,
        "camera_id": control.get("camera_id"),
        "binary_enabled": bool(control.get("binary_enabled")),
        "provider": runtime.get("vlm_provider"),
        "model": runtime.get("vlm_model"),
        "active_count": runtime.get("vlm_active_count"),
        "queue_depth": runtime.get("vlm_queue_depth"),
        "queue_capacity": runtime.get("vlm_queue_capacity"),
        "submitted_count": runtime.get("vlm_submitted_count"),
        "finished_count": runtime.get("vlm_finished_count"),
        "rejected_count": runtime.get("vlm_rejected_count"),
        "last_incident_id": runtime.get("active_incident_id"),
        "last_error": runtime.get("last_error"),
    }
