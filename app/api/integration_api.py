from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import requests
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.fall.status_contract import camera_unavailable_reason, confidence_level, degraded_by_from_payload
from app.schemas.common import utc_now_iso
from app.schemas.integration import (
    ConnectionStatusCamera,
    ConnectionStatusEndpoint,
    FallAlertPollingResponse,
    IntegrationConnectionStatusResponse,
    IntegrationLatestResultResponse,
)

router = APIRouter(prefix="/integration", tags=["integration"])


@router.get("/connection-status", response_model=IntegrationConnectionStatusResponse)
def connection_status(runtime: Runtime = Depends(get_runtime)) -> IntegrationConnectionStatusResponse:
    settings = runtime.settings
    vision_base_url = settings.vision_service_public_base_url.rstrip("/")
    main_base_url = _origin_from_base_url(settings.main_system_base_url).rstrip("/")
    reporter = getattr(runtime, "fall_event_reporter", None)
    if reporter is not None and hasattr(reporter, "check_health"):
        health = reporter.check_health()
        main_status = "online" if health.get("ok") else "unavailable"
    else:
        main_status = _main_system_status(
            main_base_url,
            health_path=getattr(settings, "main_system_health_path", "/api/integrations/fall-detection/health"),
            timeout_seconds=max(0.2, float(getattr(settings, "main_system_read_timeout_sec", settings.main_system_alert_timeout_ms / 1000))),
        )
    return IntegrationConnectionStatusResponse(
        vision_service=ConnectionStatusEndpoint(
            base_url=vision_base_url,
            status=_vision_service_status(runtime),
        ),
        main_system=ConnectionStatusEndpoint(
            base_url=main_base_url,
            status=main_status,
        ),
        camera=ConnectionStatusCamera(camera_id=settings.default_camera_id),
        timestamp=utc_now_iso(),
    )


@router.get("/results/{camera_id}/latest", response_model=IntegrationLatestResultResponse)
def latest_result(camera_id: str, runtime: Runtime = Depends(get_runtime)) -> IntegrationLatestResultResponse:
    result = runtime.realtime_store.latest_published(camera_id)
    if result is None:
        raise HTTPException(status_code=404, detail="VISION_RESULT_NOT_READY")
    payload = result.model_dump(mode="json")
    worker_status = runtime.source_manager.worker_status(camera_id)
    best_person = _best_person_object(result.objects)
    fall_decision = dict(best_person.fall_decision or {}) if best_person is not None else {}
    alarm_preview = dict(best_person.alarm_preview or {}) if best_person is not None else {}
    temporal = dict(best_person.temporal or {}) if best_person is not None else {}
    shadow = dict(temporal.get("shadow") or {}) if isinstance(temporal.get("shadow"), dict) else {}
    event_metadata = _object_event_metadata(best_person)
    latest_alert = runtime.fall_event_reporter.latest_alert(camera_id)
    fall_state = _coalesce_text(
        fall_decision.get("fall_state"),
        event_metadata.get("status"),
        event_metadata.get("state"),
        (latest_alert or {}).get("status"),
        (latest_alert or {}).get("state"),
    )
    risk_level = _coalesce_text(
        alarm_preview.get("risk_level"),
        fall_decision.get("risk_level"),
        event_metadata.get("risk_level"),
        event_metadata.get("risk"),
        (latest_alert or {}).get("risk_level"),
        (latest_alert or {}).get("risk"),
    )
    fall_prob = _best_fall_probability(best_person, temporal, shadow)
    incident_id = _coalesce_text(event_metadata.get("incident_id"), (latest_alert or {}).get("incident_id"))
    snapshot_url = _coalesce_text(
        event_metadata.get("snapshot_url"),
        (latest_alert or {}).get("snapshot_url"),
    )
    snapshot_path = _coalesce_text(
        event_metadata.get("snapshot_path"),
        (latest_alert or {}).get("snapshot_path"),
        snapshot_url,
    )
    service_state = (
        "running"
        if worker_status and worker_status.running and worker_status.connected
        else (worker_status.stream_state if worker_status else "unknown")
    )
    alarm_confirmed = bool(alarm_preview.get("confirmed")) or fall_state in {"fallen_confirmed", "confirmed_fall"}
    unavailable_reason = camera_unavailable_reason(worker_status)
    safe_to_interpret = unavailable_reason is None
    public_fall_state = "unavailable" if unavailable_reason else (fall_state or "normal")
    public_risk_level = None if unavailable_reason else risk_level
    public_fall_prob = None if unavailable_reason else fall_prob
    public_alarm_confirmed = False if unavailable_reason else alarm_confirmed
    pose = dict(best_person.pose or {}) if best_person is not None and isinstance(best_person.pose, dict) else {}
    pose_debug = dict(pose.get("debug") or {}) if isinstance(pose.get("debug"), dict) else {}
    pose_available = bool(pose) and not bool(pose_debug.get("pose_disabled")) and bool(pose.get("keypoints"))
    degraded_by = degraded_by_from_payload(
        pose_available=pose_available,
        pose_debug=pose_debug,
        detector_debug=result.detector,
        extra=[unavailable_reason] if unavailable_reason else None,
    )
    return IntegrationLatestResultResponse(
        **payload,
        stream_name="primary",
        source="vision_service",
        event_type="fall_confirmed" if public_alarm_confirmed else None,
        state=public_fall_state,
        status=public_fall_state,
        service_state=service_state,
        camera_lost=bool(
            worker_status and worker_status.stream_state in {"disconnected", "reconnecting"} and not worker_status.connected
        ),
        capture_stale=bool(
            worker_status and worker_status.stream_state in {"connecting", "stale", "reconnecting"}
        ),
        frame_age_ms=worker_status.frame_age_ms if worker_status else None,
        source_fps=worker_status.capture_fps if worker_status else None,
        analysis_fps=runtime.result_publisher_service.status_fps(camera_id),
        fall_detected=public_alarm_confirmed,
        fall_state=public_fall_state,
        risk=public_risk_level,
        risk_level=public_risk_level,
        fall_prob=public_fall_prob,
        fall_score=public_fall_prob,
        confidence_level=confidence_level(
            fall_state=public_fall_state,
            fall_probability=public_fall_prob,
            safe_to_interpret_as_no_fall=safe_to_interpret,
        ),
        degraded_by=degraded_by,
        reason=unavailable_reason,
        safe_to_interpret_as_no_fall=safe_to_interpret,
        frame_status=getattr(worker_status, "frame_status", None) if worker_status else "no_frame",
        camera_stream_state=getattr(worker_status, "stream_state", None) if worker_status else "disabled",
        source_generation=getattr(worker_status, "source_generation", None) if worker_status else None,
        track_id=best_person.track_id if best_person is not None else None,
        incident_id=incident_id,
        bbox=[float(value) for value in best_person.bbox] if best_person is not None else None,
        target=_target_payload(best_person),
        snapshot_url=snapshot_url,
        snapshot_path=snapshot_path,
        alarm_confirmed=public_alarm_confirmed,
        scores=_score_payload(fall_prob, shadow),
        injury=dict(event_metadata.get("injury") or (latest_alert or {}).get("injury") or {}),
        metadata=_metadata_payload(best_person, latest_alert, event_metadata),
    )


@router.get("/fall-alerts/{camera_id}/poll", response_model=FallAlertPollingResponse)
def poll_fall_alert(
    camera_id: str,
    last_incident_id: str | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> FallAlertPollingResponse:
    payload = runtime.fall_event_reporter.polling_alert(camera_id, last_incident_id=last_incident_id)
    return FallAlertPollingResponse(**payload)


def _best_person_object(objects):
    people = [item for item in objects if item.label == "person"]
    if not people:
        return None
    confirmed_people = [item for item in people if bool((item.alarm_preview or {}).get("confirmed"))]
    if confirmed_people:
        return max(confirmed_people, key=lambda item: float(item.confidence))
    return max(people, key=lambda item: float(item.confidence))


def _best_fall_probability(best_person, temporal: dict, shadow: dict) -> float | None:
    if best_person is None:
        return None
    candidates = [
        temporal.get("fall_probability"),
        shadow.get("fall_probability"),
        (best_person.fall_decision or {}).get("fall_probability"),
        (best_person.alarm_preview or {}).get("fall_probability"),
    ]
    values: list[float] = []
    for candidate in candidates:
        try:
            if candidate is not None:
                values.append(max(0.0, min(1.0, float(candidate))))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _target_payload(best_person) -> dict | None:
    if best_person is None:
        return None
    return {
        "target_id": best_person.person_id,
        "label": best_person.person_name or ("target" if best_person.is_target else "person"),
        "matched": bool(best_person.person_id or best_person.person_name),
        "confidence": float(best_person.confidence),
        "metadata": {
            "is_target": bool(best_person.is_target),
            "identity_state": best_person.identity_state,
        },
    }


def _score_payload(fall_prob: float | None, shadow: dict) -> dict:
    payload = {}
    if fall_prob is not None:
        payload["hybrid"] = fall_prob
        payload["detector"] = fall_prob
    shadow_probability = shadow.get("fall_probability") if isinstance(shadow, dict) else None
    if shadow_probability is not None:
        payload["posture"] = shadow_probability
    return payload


def _metadata_payload(best_person, latest_alert: dict | None, event_metadata: dict | None = None) -> dict:
    payload = {}
    if best_person is not None:
        payload["track_id"] = best_person.track_id
        payload["is_target"] = best_person.is_target
        payload["person_id"] = best_person.person_id
        payload["person_name"] = best_person.person_name
        payload["identity_state"] = best_person.identity_state
        payload["fall_decision"] = dict(best_person.fall_decision or {})
        payload["alarm_preview"] = dict(best_person.alarm_preview or {})
        payload["temporal"] = dict(best_person.temporal or {})
        payload["behavior"] = dict(best_person.behavior or {}) if isinstance(best_person.behavior, dict) else best_person.behavior
        payload["pose"] = dict(best_person.pose or {}) if isinstance(best_person.pose, dict) else best_person.pose
    if event_metadata:
        payload["event"] = dict(event_metadata)
    if latest_alert is not None:
        payload["incident_id"] = latest_alert.get("incident_id")
        payload["trigger"] = ((latest_alert.get("metadata") or {}).get("trigger") if isinstance(latest_alert.get("metadata"), dict) else None)
        payload["source_camera_name"] = ((latest_alert.get("metadata") or {}).get("source_camera_name") if isinstance(latest_alert.get("metadata"), dict) else None)
    return payload


def _object_event_metadata(best_person) -> dict:
    if best_person is None or not isinstance(best_person.temporal, dict):
        return {}
    metadata = best_person.temporal.get("event_metadata")
    if not isinstance(metadata, dict):
        return {}
    return dict(metadata)


def _coalesce_text(*values) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _vision_service_status(runtime: Runtime) -> str:
    runtimes = runtime.source_manager.list_runtimes()
    if not runtimes:
        return "unknown"
    target = next((item for item in runtimes if item.config.camera_id == runtime.settings.default_camera_id), None)
    if target is None:
        return "degraded"
    worker_status = runtime.source_manager.worker_status(runtime.settings.default_camera_id)
    if worker_status and worker_status.running:
        return "online"
    return "degraded"


def _main_system_status(main_base_url: str, *, health_path: str, timeout_seconds: float) -> str:
    path = health_path.strip() or "/api/integrations/fall-detection/health"
    if not path.startswith("/"):
        path = f"/{path}"
    healthz_url = f"{main_base_url.rstrip('/')}{path}"
    try:
        response = requests.get(healthz_url, timeout=timeout_seconds)
    except requests.Timeout:
        return "timeout"
    except requests.ConnectionError:
        return "connection_error"
    except requests.RequestException:
        return "unavailable"
    return "online" if response.status_code < 400 else "unavailable"


def _origin_from_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
