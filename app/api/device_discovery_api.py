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
    status = service.status()
    return {**status, "alert_pairing": _current_alert_pairing(runtime)}


@router.post("/rescan")
def rescan_devices(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="main_system")


@router.post("/connect-all")
def connect_all_devices(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="main_system")


@router.post("/connect-main-system")
def connect_main_system(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="main_system")


@router.post("/pair-main-system")
def pair_main_system(runtime: Runtime = Depends(get_runtime)) -> dict:
    return _run_discovery(runtime, mode="main_system")


@router.post("/connect-camera")
def connect_camera(runtime: Runtime = Depends(get_runtime)) -> dict:
    raise HTTPException(status_code=410, detail="camera discovery has been removed; use the video source URL field for video input")


def _run_discovery(runtime: Runtime, *, mode: str) -> dict:
    service = runtime.device_connection_service
    if service is None:
        raise HTTPException(status_code=503, detail="device connection service is not configured")
    if not _rescan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="device discovery scan already running")
    try:
        result = service.connect_main_system()
        apply_resolved_settings_to_runtime(runtime, result.settings)
        alert_pairing = _pair_main_system_alert_endpoint(runtime, result)
        return {
            **result.status,
            "alert_pairing": alert_pairing,
            "applied": {
                "mode": "main_system",
                "main_system_base_url": result.settings.main_system_base_url,
                "default_camera_id": result.settings.default_camera_id,
                "paired": alert_pairing["connected"] and alert_pairing["enabled"] and not alert_pairing["dry_run"],
                "alert_endpoint": alert_pairing["endpoint"],
                "alert_path": alert_pairing["path"],
                "alert_enabled": alert_pairing["enabled"],
                "alert_dry_run": alert_pairing["dry_run"],
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


def _pair_main_system_alert_endpoint(runtime: Runtime, result) -> dict:
    reporter = getattr(runtime, "fall_event_reporter", None)
    main_system = result.status.get("main_system") if isinstance(result.status, dict) else {}
    connected = isinstance(main_system, dict) and main_system.get("status") == "connected"
    base_url = str(result.settings.main_system_base_url or "").strip()
    path = str(getattr(result.settings, "main_system_alert_path", None) or result.settings.main_system_fall_event_path or "/api/integrations/fall-detection/alerts")
    if reporter is not None and connected and base_url:
        update_endpoint = getattr(reporter, "update_endpoint", None)
        if callable(update_endpoint):
            try:
                status = update_endpoint(base_url=base_url, path=path, enabled=True, dry_run=False)
            except TypeError:
                status = update_endpoint(base_url=base_url, path=path, enabled=True)
        else:
            status = reporter.status()
    elif reporter is not None and hasattr(reporter, "status"):
        status = reporter.status()
    else:
        status = {}
    endpoint = str(status.get("endpoint") or f"{base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}")
    return {
        "connected": connected,
        "enabled": bool(status.get("enabled")) if connected and status else False,
        "dry_run": bool(status.get("dry_run")) if connected and status else True,
        "endpoint": endpoint,
        "base_url": str(status.get("endpoint_base_url") or base_url),
        "path": str(status.get("endpoint_path") or path),
    }


def _current_alert_pairing(runtime: Runtime) -> dict:
    reporter = getattr(runtime, "fall_event_reporter", None)
    if reporter is None or not hasattr(reporter, "status"):
        return {"connected": False, "enabled": False, "dry_run": True, "endpoint": "", "base_url": "", "path": ""}
    status = reporter.status()
    return {
        "connected": bool(status.get("enabled")) and not bool(status.get("dry_run")),
        "enabled": bool(status.get("enabled")),
        "dry_run": bool(status.get("dry_run")),
        "endpoint": str(status.get("endpoint") or ""),
        "base_url": str(status.get("endpoint_base_url") or ""),
        "path": str(status.get("endpoint_path") or ""),
    }
