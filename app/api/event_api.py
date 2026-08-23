from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.events.schemas import EvidenceKeyframe, EventOutboxRecord

router = APIRouter(prefix="/events", tags=["events"])

_KEYFRAME_ID_TO_OFFSET = {
    "t_minus_3s": -3000,
    "t_minus_1s": -1000,
    "t0": 0,
    "t_plus_1s": 1000,
    "t_plus_3s": 3000,
    "t_plus_5s": 5000,
}
_OFFSET_TO_KEYFRAME_ID = {offset: keyframe_id for keyframe_id, offset in _KEYFRAME_ID_TO_OFFSET.items()}
_SAFE_INCIDENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_EMBEDDED_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/][^\s<>\"']+)")
_EMBEDDED_UNIX_PATH = re.compile(r"(?<![A-Za-z0-9:/\\])/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+")
_PUBLIC_FORBIDDEN_KEYS = {
    "lock_owner",
    "lock_token",
    "lock_until",
    "payload_json",
    "target_url",
    "raw_response",
    "keyframe_image_paths",
    "timeline_image_path",
    "provider_request_payload",
    "request_payload",
    "request_json",
    "auth_header",
    "authorization",
    "token",
}


@router.get("/status")
def event_status(runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = runtime.event_pipeline
    if pipeline is None:
        return _disabled_status()
    status = pipeline.status()
    return {
        "event_pipeline_enabled": status["enabled"],
        "ring_buffer_enabled": status["ring_buffer_enabled"],
        "worker_enabled": status["worker_enabled"],
        "semantic_enabled": status["semantic_enabled"],
        "vlm_enabled": status["vlm_enabled"],
        "qwen_keyframe_analysis_enabled": status.get("qwen_keyframe_analysis_enabled", False),
        "qwen_keyframe_worker": status.get("qwen_keyframe_worker", {}),
        "outbox_backend": status["outbox_backend"],
        "worker_running": status["worker_running"],
        "pending_count": status["pending_count"],
        "processing_count": status["processing_count"],
        "reviewed_count": status["reviewed_count"],
        "failed_count": status["failed_count"],
        "outbox_count": status["outbox_count"],
    }


@router.get("/outbox")
def event_outbox(
    status: str | None = None,
    camera_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    pipeline = runtime.event_pipeline
    if pipeline is None:
        return {"enabled": False, "items": []}
    records = pipeline.outbox.list_events(status=status, camera_id=camera_id, limit=limit)
    return {"enabled": pipeline.enabled, "items": [_record_payload(record, pipeline) for record in records]}


@router.get("/latest")
def latest_event(camera_id: str, runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = runtime.event_pipeline
    if pipeline is None:
        return {"enabled": False, "event": None}
    records = pipeline.outbox.list_events(camera_id=camera_id, limit=1)
    return {"enabled": pipeline.enabled, "event": _record_payload(records[0], pipeline) if records else None}


@router.get("/delivery/status")
def delivery_status(runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = getattr(runtime, "event_pipeline", None)
    settings = runtime.settings
    worker = getattr(runtime, "event_delivery_worker", None)
    if pipeline is None:
        counts = _delivery_counts([])
    else:
        counts = _delivery_counts(pipeline.delivery_outbox.list_deliveries(limit=1000))
    worker_status = worker.status() if worker is not None else {}
    return {
        "event_delivery_enabled": bool(settings.event_delivery_enabled),
        "delivery_backend": settings.event_delivery_backend,
        "delivery_mode": settings.event_delivery_mode,
        "delivery_worker_enabled": bool(settings.event_delivery_worker_enabled),
        "worker_running": bool(worker_status.get("running", False)),
        "pending_count": counts["pending"],
        "sending_count": counts["sending"],
        "retry_count": counts["retry"],
        "failed_count": counts["failed"],
        "sent_count": counts["sent"],
        "dry_run_sent_count": counts["dry_run_sent"],
        "total_count": sum(counts.values()),
    }


@router.get("/delivery/outbox")
def delivery_outbox(
    status: str | None = None,
    camera_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    runtime: Runtime = Depends(get_runtime),
) -> dict:
    pipeline = getattr(runtime, "event_pipeline", None)
    if pipeline is None:
        return {"enabled": False, "items": []}
    records = pipeline.delivery_outbox.list_deliveries(status=status, camera_id=camera_id, limit=limit)
    return {"enabled": bool(runtime.settings.event_delivery_enabled), "items": [_delivery_payload(record, runtime.settings.event_delivery_backend) for record in records]}


@router.get("/delivery/by-incident/{incident_id}")
def delivery_by_incident(incident_id: str, runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = getattr(runtime, "event_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="EVENT_PIPELINE_DISABLED")
    record = pipeline.delivery_outbox.for_incident(incident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="DELIVERY_NOT_FOUND")
    return _delivery_payload(record, runtime.settings.event_delivery_backend)


@router.get("/delivery/{delivery_id}")
def delivery_detail(delivery_id: str, runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = getattr(runtime, "event_pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="EVENT_PIPELINE_DISABLED")
    record = pipeline.delivery_outbox.get(delivery_id)
    if record is None:
        raise HTTPException(status_code=404, detail="DELIVERY_NOT_FOUND")
    return _delivery_payload(record, runtime.settings.event_delivery_backend)


@router.get("/{incident_id}/keyframes/by-offset/{offset_ms}")
def event_keyframe_by_offset(incident_id: str, offset_ms: int, runtime: Runtime = Depends(get_runtime)) -> FileResponse:
    return _event_keyframe_response(incident_id, offset_ms, runtime)


@router.get("/{incident_id}/keyframes/{selector}")
def event_keyframe(incident_id: str, selector: str, runtime: Runtime = Depends(get_runtime)) -> FileResponse:
    return _event_keyframe_response(incident_id, selector, runtime)


def _event_keyframe_response(incident_id: str, selector: str | int, runtime: Runtime) -> FileResponse:
    pipeline = runtime.event_pipeline
    if pipeline is None or not pipeline.enabled:
        raise _not_found("EVENT_PIPELINE_DISABLED")
    if not _is_safe_incident_id(incident_id):
        raise _not_found("INVALID_INCIDENT_ID")
    if not pipeline.settings.event_keyframe_serving_enabled:
        raise _not_found("KEYFRAME_SERVING_DISABLED")
    record = pipeline.outbox.get_event(incident_id)
    if record is None:
        raise _not_found("EVENT_NOT_FOUND")
    keyframe = _find_keyframe(record, selector)
    if keyframe is None:
        raise _not_found("KEYFRAME_NOT_FOUND", selector=selector)
    if keyframe.missing_reason:
        raise _not_found("KEYFRAME_MISSING", missing_reason=keyframe.missing_reason)
    if not keyframe.image_path:
        raise _not_found("KEYFRAME_IMAGE_NOT_ARCHIVED")
    resolved = _resolve_keyframe_file(record, keyframe.image_path, pipeline)
    if resolved is None:
        raise _not_found("INVALID_KEYFRAME_PATH")
    if not resolved.exists() or not resolved.is_file():
        raise _not_found("KEYFRAME_FILE_NOT_FOUND")
    return FileResponse(resolved, media_type=_image_media_type(resolved))


@router.get("/{incident_id}")
def event_detail(incident_id: str, runtime: Runtime = Depends(get_runtime)) -> dict:
    pipeline = runtime.event_pipeline
    if pipeline is None:
        raise HTTPException(status_code=404, detail="EVENT_PIPELINE_DISABLED")
    if not _is_safe_incident_id(incident_id):
        raise _not_found("INVALID_INCIDENT_ID")
    record = pipeline.outbox.get_event(incident_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EVENT_NOT_FOUND")
    return _record_payload(record, pipeline)


def _record_payload(record, pipeline) -> dict:
    payload = _redact_public_sensitive_fields(_redact_local_absolute_paths(record.model_dump(mode="json")))
    payload["archive_id"] = record.archive_path if record.archive_path and _safe_posix_relative(record.archive_path) is not None else None
    payload["archive_path"] = None
    payload["archive_summary"] = _public_archive_summary(record.archive_summary or {})
    evidence = payload.get("evidence_package")
    source_keyframes = record.evidence_package.keyframes if record.evidence_package is not None else []
    if isinstance(evidence, dict):
        for index, keyframe in enumerate(evidence.get("keyframes") or []):
            if isinstance(keyframe, dict):
                source = source_keyframes[index] if index < len(source_keyframes) else None
                keyframe.update(_keyframe_summary(record, source, pipeline))
    delivery = pipeline.delivery_outbox.for_incident(record.incident_id)
    payload["delivery"] = _delivery_payload(delivery, pipeline.settings.event_delivery_backend) if delivery is not None else None
    return _redact_local_absolute_paths(payload)


def _delivery_counts(records: list) -> dict[str, int]:
    counts = {status: 0 for status in ("pending", "sending", "sent", "dry_run_sent", "retry", "failed")}
    for record in records:
        status = str(getattr(record, "delivery_status", "") or "")
        if status in counts:
            counts[status] += 1
    return counts


def _delivery_payload(record, delivery_backend: str | None = None) -> dict:
    return _redact_local_absolute_paths({
        "delivery_id": record.delivery_id,
        "incident_id": record.incident_id,
        "camera_id": record.camera_id,
        "delivery_status": record.delivery_status,
        "delivery_mode": record.delivery_mode,
        "dry_run": record.dry_run,
        "attempt_count": record.attempt_count,
        "retry_count": max(0, int(record.attempt_count or 0) - (1 if record.delivery_status in {"sent", "dry_run_sent"} else 0)),
        "last_http_status": record.last_http_status,
        "last_error": _bounded_text(record.last_error),
        "next_retry_at": record.next_retry_at,
        "delivered_at": record.delivered_at,
        "delivery_backend": delivery_backend,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "payload_summary": _delivery_payload_summary(record.payload_json),
    })


def _delivery_payload_summary(payload: dict) -> dict:
    summary = {}
    for key in (
        "incident_id",
        "camera_id",
        "event_type",
        "state",
        "status",
        "severity",
        "risk_level",
        "fall_detected",
        "timestamp",
    ):
        if key in payload:
            summary[key] = payload.get(key)
    snapshot_url = payload.get("snapshot_url")
    summary["snapshot_url"] = snapshot_url if isinstance(snapshot_url, str) and not _looks_like_local_absolute_path(snapshot_url) else None
    return summary


def _bounded_text(value: str | None, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= limit else f"{text[:limit]}..."


def _keyframe_summary(record: EventOutboxRecord, keyframe: EvidenceKeyframe | None, pipeline) -> dict:
    if keyframe is None:
        return {
            "label": None,
            "available": False,
            "image_path": None,
            "keyframe_url": None,
        }
    serving_enabled = bool(getattr(pipeline.settings, "event_keyframe_serving_enabled", False))
    image_path = keyframe.image_path if keyframe.image_path and _safe_archive_relative_path(keyframe.image_path) is not None else None
    resolved = _resolve_keyframe_file(record, image_path, pipeline) if image_path else None
    available = bool(
        serving_enabled
        and _is_safe_incident_id(record.incident_id)
        and image_path
        and not keyframe.missing_reason
        and resolved is not None
        and resolved.exists()
        and resolved.is_file()
    )
    return {
        "role": keyframe.role,
        "offset_ms": keyframe.offset_ms,
        "label": _timeline_label(keyframe.offset_ms),
        "available": available,
        "missing_reason": keyframe.missing_reason or (None if available else _unavailable_reason(image_path, resolved, serving_enabled)),
        "image_path": image_path if serving_enabled else None,
        "keyframe_url": _keyframe_url(record.incident_id, keyframe.offset_ms) if available else None,
    }


def _unavailable_reason(image_path: str | None, resolved: Path | None, serving_enabled: bool) -> str:
    if not serving_enabled:
        return "keyframe_serving_disabled"
    if image_path is None:
        return "image_not_archived"
    if resolved is None:
        return "invalid_keyframe_path"
    return "keyframe_file_not_found"


def _keyframe_url(incident_id: str, offset_ms: int) -> str:
    keyframe_id = _keyframe_id(offset_ms)
    return f"/events/{incident_id}/keyframes/{keyframe_id}"


def _keyframe_id(offset_ms: int) -> str:
    return _OFFSET_TO_KEYFRAME_ID.get(offset_ms, str(offset_ms))


def _timeline_label(offset_ms: int) -> str:
    if offset_ms == 0:
        return "T0"
    seconds = abs(offset_ms) // 1000
    return f"T-{seconds}s" if offset_ms < 0 else f"T+{seconds}s"


def _find_keyframe(record: EventOutboxRecord, selector: str | int) -> EvidenceKeyframe | None:
    evidence = record.evidence_package
    if evidence is None:
        return None
    normalized = str(selector).strip().lower()
    offset = _parse_offset_selector(normalized)
    if offset is not None:
        for keyframe in evidence.keyframes:
            if keyframe.offset_ms == offset:
                return keyframe
        return None
    for keyframe in evidence.keyframes:
        if keyframe.role == normalized:
            return keyframe
    return None


def _parse_offset_selector(value: str) -> int | None:
    if value in _KEYFRAME_ID_TO_OFFSET:
        return _KEYFRAME_ID_TO_OFFSET[value]
    if value in {"t0", "0"}:
        return 0
    if value.startswith("t-") and value.endswith("s"):
        return _seconds_to_ms(value[2:-1], -1)
    if value.startswith("t+") and value.endswith("s"):
        return _seconds_to_ms(value[2:-1], 1)
    try:
        return int(value)
    except ValueError:
        return None


def _seconds_to_ms(value: str, sign: int) -> int | None:
    try:
        return int(float(value) * 1000) * sign
    except ValueError:
        return None


def _resolve_keyframe_file(record: EventOutboxRecord, image_path: str, pipeline) -> Path | None:
    archive_dir = _resolve_event_archive_dir(record, pipeline)
    relative_path = _safe_archive_relative_path(image_path)
    if archive_dir is None or relative_path is None:
        return None
    candidate = (archive_dir / relative_path).resolve()
    root = Path(pipeline.archive.root_dir).resolve()
    if not _is_relative_to(candidate, root) or not _is_relative_to(candidate, archive_dir):
        return None
    return candidate


def _resolve_event_archive_dir(record: EventOutboxRecord, pipeline) -> Path | None:
    if not record.archive_path:
        return None
    relative = _safe_posix_relative(record.archive_path)
    expected = Path(_safe_segment(record.event.camera_id)) / _safe_segment(record.incident_id)
    if relative is None or relative != expected:
        return None
    root = Path(pipeline.archive.root_dir).resolve()
    candidate = (root / relative).resolve()
    return candidate if _is_relative_to(candidate, root) else None


def _safe_archive_relative_path(value: str) -> Path | None:
    relative = _safe_posix_relative(value)
    if relative is None:
        return None
    parts = relative.parts
    if not parts or parts[0] != "keyframes":
        return None
    if relative.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        return None
    return relative


def _safe_posix_relative(value: str) -> Path | None:
    if not value or value.startswith(("/", "\\")):
        return None
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if any(":" in part for part in path.parts):
        return None
    return Path(*path.parts)


def _safe_segment(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)[:120] or "unknown"


def _is_safe_incident_id(value: str) -> bool:
    return bool(_SAFE_INCIDENT_ID.fullmatch(value))


def _public_archive_summary(summary: dict) -> dict:
    return _redact_local_absolute_paths(_redact_archive_summary_sensitive_fields(summary))


def _redact_archive_summary_sensitive_fields(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _PUBLIC_FORBIDDEN_KEYS and normalized != "timeline_image_path":
                continue
            redacted[key] = _redact_archive_summary_sensitive_fields(item)
        return redacted
    if isinstance(value, list):
        return [_redact_archive_summary_sensitive_fields(item) for item in value]
    return value


def _redact_local_absolute_paths(value):
    """Prevent future archive metadata fields from leaking local filesystem paths."""
    if isinstance(value, str):
        if _is_public_relative_api_url(value):
            return value
        if _looks_like_encoded_image_payload(value):
            return None
        if _looks_like_local_absolute_path(value):
            return None
        return _redact_embedded_local_paths(value)
    if isinstance(value, dict):
        return {key: _redact_local_absolute_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_local_absolute_paths(item) for item in value]
    return value


def _redact_public_sensitive_fields(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _PUBLIC_FORBIDDEN_KEYS:
                continue
            redacted[key] = _redact_public_sensitive_fields(item)
        return redacted
    if isinstance(value, list):
        return [_redact_public_sensitive_fields(item) for item in value]
    return value


def _is_public_relative_api_url(value: str) -> bool:
    return value.startswith("/events/")


def _redact_embedded_local_paths(value: str) -> str:
    value = _EMBEDDED_WINDOWS_PATH.sub("[local-path-redacted]", value)
    return _EMBEDDED_UNIX_PATH.sub("[local-path-redacted]", value)


def _looks_like_local_absolute_path(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if stripped.startswith(("/", "\\")):
        return True
    return len(stripped) >= 3 and stripped[1] == ":" and stripped[2] in {"/", "\\"}


def _looks_like_encoded_image_payload(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("data:image") or "base64," in lowered


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _image_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "application/octet-stream"


def _not_found(reason: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=404, detail={"reason": reason, **extra})


def _disabled_status() -> dict:
    return {
        "event_pipeline_enabled": False,
        "ring_buffer_enabled": False,
        "worker_enabled": False,
        "semantic_enabled": False,
        "vlm_enabled": False,
        "outbox_backend": "memory",
        "worker_running": False,
        "pending_count": 0,
        "processing_count": 0,
        "reviewed_count": 0,
        "failed_count": 0,
        "outbox_count": 0,
    }
