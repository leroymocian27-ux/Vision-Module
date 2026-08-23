from __future__ import annotations

from typing import Any


SYSTEM_HEALTH_STATES = {"healthy", "degraded", "blocked", "stopped"}
FALL_BUSINESS_STATES = {
    "normal",
    "fall_candidate",
    "fall_high_risk",
    "fall_confirmed",
    "cooldown",
    "unavailable",
}

UNAVAILABLE_REASONS = {
    "no_frame",
    "camera_disconnected",
    "frame_stale",
    "stale",
    "stopped",
    "reconnecting",
    "unreachable",
    "authentication_failed",
    "decode_error",
    "capture_stopped",
    "end_of_file",
}


def camera_unavailable_reason(worker_status: Any) -> str | None:
    if worker_status is None:
        return "camera_disconnected"
    frame_status = str(getattr(worker_status, "frame_status", "no_frame") or "no_frame")
    stream_state = str(getattr(worker_status, "stream_state", "") or "")
    reconnect_reason = str(getattr(worker_status, "reconnect_reason", "") or "")
    connected = bool(getattr(worker_status, "connected", False))
    running = bool(getattr(worker_status, "running", False))
    if reconnect_reason == "eof":
        return "end_of_file"
    if not running:
        return "stopped"
    if stream_state in {"stopped", "reconnecting", "unreachable", "authentication_failed", "decode_error"}:
        return stream_state
    if frame_status == "no_frame":
        return "no_frame"
    if frame_status == "stale":
        return "frame_stale"
    if not connected and frame_status != "fresh":
        return "camera_disconnected"
    return None


def normalize_fall_state(value: str | None, *, alarm_confirmed: bool = False) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"fallen_confirmed", "confirmed_fall", "fall_confirmed"} or alarm_confirmed:
        return "fall_confirmed"
    if raw in {"fallen_candidate", "falling", "suspicious", "fall_candidate"}:
        return "fall_candidate"
    if raw in {"high", "critical", "fall_high_risk"}:
        return "fall_high_risk"
    if raw == "cooldown":
        return "cooldown"
    if raw == "unavailable":
        return "unavailable"
    return "normal"


def confidence_level(*, fall_state: str | None, fall_probability: float | None, safe_to_interpret_as_no_fall: bool) -> str:
    state = normalize_fall_state(fall_state)
    if not safe_to_interpret_as_no_fall or state == "unavailable":
        return "unavailable"
    if state == "fall_confirmed":
        return "high"
    if state in {"fall_candidate", "fall_high_risk"}:
        return "medium"
    if fall_probability is None:
        return "low"
    if fall_probability >= 0.7:
        return "high"
    if fall_probability >= 0.35:
        return "medium"
    return "low"


def degraded_by_from_payload(
    *,
    pose_available: bool,
    pose_debug: dict | None = None,
    detector_debug: dict | None = None,
    extra: list[str] | None = None,
) -> list[str]:
    reasons: list[str] = []
    if not pose_available:
        reason = None
        if isinstance(pose_debug, dict):
            reason = pose_debug.get("runtime_reason") or pose_debug.get("rejected_reason")
            if pose_debug.get("pose_disabled") is True:
                reason = "pose_disabled"
        reasons.append(str(reason or "pose_disabled"))
    if isinstance(detector_debug, dict):
        freshness = detector_debug.get("evidence_freshness")
        if isinstance(freshness, dict):
            for name, state in freshness.items():
                if state not in {"fresh", "disabled"}:
                    reasons.append(f"{name}_{state}")
    if extra:
        reasons.extend(extra)
    return list(dict.fromkeys(reason for reason in reasons if reason))
