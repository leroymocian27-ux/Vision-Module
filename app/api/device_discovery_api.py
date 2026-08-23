from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.services.device_connection_service import apply_resolved_settings_to_runtime

router = APIRouter(prefix="/device-discovery", tags=["device-discovery"])
_rescan_lock = threading.Lock()


@router.get("/status")
def device_discovery_status(runtime: Runtime = Depends(get_runtime)) -> dict:
    service = runtime.device_connection_service
    if service is None:
        return {"discovery": {"status": "unavailable", "last_error": "device_connection_service_not_configured"}}
    return service.status()


@router.post("/rescan")
def rescan_devices(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="all")


@router.post("/connect-all")
def connect_all_devices(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="all")


@router.post("/connect-main-system")
def connect_main_system(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="main_system")


@router.post("/connect-camera")
def connect_camera(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="camera")


def _run_discovery(runtime: Runtime, *, mode: str) -> dict:
    service = runtime.device_connection_service
    if service is None:
        raise HTTPException(status_code=503, detail="device connection service is not configured")
    if not _rescan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="device discovery scan already running")
    try:
        if mode == "main_system":
            result = service.connect_main_system()
        elif mode == "camera":
            result = service.connect_camera()
        else:
            result = service.manual_rescan()
        apply_resolved_settings_to_runtime(runtime, result.settings)
        camera_url = result.settings.default_rtsp_url
        if camera_url and mode != "main_system":
            try:
                runtime.stream_service.start(result.settings.default_camera_id, camera_url)
            except ValueError:
                pass
        return {
            **result.status,
            "applied": {
                "mode": mode,
                "main_system_base_url": result.settings.main_system_base_url,
                "camera_stream_started": bool(camera_url and mode != "main_system"),
                "default_camera_id": result.settings.default_camera_id,
            },
            "scan_results": [
                {
                    "ip": item.ip,
                    "device_type": item.device_type,
                    "confidence": item.confidence,
                    "status": item.status,
                    "open_ports": item.open_ports,
                    "evidence": item.evidence,
                    "error": item.error,
                }
                for item in result.scan_results
                if item.confidence > 0 or item.open_ports or item.error
            ],
        }
    finally:
        _rescan_lock.release()
