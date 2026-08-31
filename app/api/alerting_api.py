from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.schemas.alerting import (
    AlertControlStatus,
    AlertEndpointConfig,
    AlertEndpointUpdateRequest,
    AlertSimulationSendOnceRequest,
    AlertSimulationSendOnceResult,
    AlertSimulationStartRequest,
    AlertSimulationStatus,
)

router = APIRouter(prefix="/alerting", tags=["alerting"])


@router.get("/status", response_model=AlertControlStatus)
def alerting_status(runtime: Runtime = Depends(get_runtime)) -> AlertControlStatus:
    reporter = runtime.fall_event_reporter.status()
    simulation = runtime.alert_simulator_service.status()
    return AlertControlStatus(
        endpoint=AlertEndpointConfig(
            base_url=str(reporter.get("endpoint_base_url") or ""),
            path=str(reporter.get("endpoint_path") or "/api/integrations/fall-detection/alerts"),
            enabled=bool(reporter.get("enabled")),
            dry_run=bool(reporter.get("dry_run")),
            token_header=str(reporter.get("token_header") or ""),
        ),
        simulation=AlertSimulationStatus(**simulation),
    )


@router.post("/endpoint", response_model=AlertControlStatus)
def update_alert_endpoint(
    request: AlertEndpointUpdateRequest,
    runtime: Runtime = Depends(get_runtime),
) -> AlertControlStatus:
    reporter = runtime.fall_event_reporter.update_endpoint(
        base_url=request.base_url,
        path=request.path,
        enabled=request.enabled,
    )
    simulation = runtime.alert_simulator_service.status()
    return AlertControlStatus(
        endpoint=AlertEndpointConfig(
            base_url=str(reporter.get("endpoint_base_url") or ""),
            path=str(reporter.get("endpoint_path") or "/api/integrations/fall-detection/alerts"),
            enabled=bool(reporter.get("enabled")),
            dry_run=bool(reporter.get("dry_run")),
            token_header=str(reporter.get("token_header") or ""),
        ),
        simulation=AlertSimulationStatus(**simulation),
    )


@router.get("/main-system/health")
def test_main_system_connection(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.fall_event_reporter.check_health()


@router.post("/main-system/retry-pending")
def retry_pending_main_system_alerts(runtime: Runtime = Depends(get_runtime)) -> dict:
    return runtime.fall_event_reporter.retry_pending_alerts(include_failed=True)


@router.post("/simulation/start", response_model=AlertSimulationStatus)
def start_alert_simulation(
    request: AlertSimulationStartRequest,
    runtime: Runtime = Depends(get_runtime),
) -> AlertSimulationStatus:
    if request.base_url:
        base_url = request.base_url
    elif request.target_ip:
        base_url = f"http://{request.target_ip}:{runtime.settings.main_system_default_port}"
    else:
        reporter = runtime.fall_event_reporter.status()
        base_url = str(reporter.get("endpoint_base_url") or "").strip()
        if not base_url:
            raise HTTPException(status_code=400, detail="target_ip or base_url is required")
    path = request.path or runtime.fall_event_reporter.status().get("endpoint_path") or "/api/integrations/fall-detection/alerts"
    runtime.fall_event_reporter.update_endpoint(base_url=base_url, path=str(path), enabled=True)
    status = runtime.alert_simulator_service.start(
        interval_seconds=request.interval_seconds,
        camera_id=request.camera_id,
        track_id=request.track_id,
        fall_prob=request.fall_prob,
    )
    return AlertSimulationStatus(**status)


@router.post("/simulation/send-once", response_model=AlertSimulationSendOnceResult)
def send_alert_simulation_once(
    request: AlertSimulationSendOnceRequest,
    runtime: Runtime = Depends(get_runtime),
) -> AlertSimulationSendOnceResult:
    result = runtime.alert_simulator_service.send_once(
        target_ip=request.target_ip,
        base_url=request.base_url,
        event_id=request.event_id,
        camera_id=request.camera_id,
        track_id=request.track_id,
        fall_prob=request.fall_prob,
    )
    return AlertSimulationSendOnceResult(**result)


@router.post("/simulation/stop", response_model=AlertSimulationStatus)
def stop_alert_simulation(runtime: Runtime = Depends(get_runtime)) -> AlertSimulationStatus:
    status = runtime.alert_simulator_service.stop()
    return AlertSimulationStatus(**status)
