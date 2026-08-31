from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PUBLIC_CAMERA_STATES = {
    "disabled",
    "initializing",
    "connecting",
    "connected",
    "streaming",
    "delayed",
    "stale",
    "reconnecting",
    "authentication_failed",
    "unreachable",
    "decode_error",
    "stopped",
}


@dataclass(frozen=True)
class FreshnessThresholds:
    delayed_ms: int = 1000
    stale_ms: int = 3000


@dataclass(frozen=True)
class FrameFreshness:
    frame_status: str
    is_stale: bool
    safe_to_interpret_as_no_fall: bool
    reason: str | None = None


def frame_freshness(age_ms: float | None, thresholds: FreshnessThresholds) -> FrameFreshness:
    if age_ms is None:
        return FrameFreshness(
            frame_status="no_frame",
            is_stale=False,
            safe_to_interpret_as_no_fall=False,
            reason="no_frame",
        )
    if age_ms > thresholds.stale_ms:
        return FrameFreshness(
            frame_status="stale",
            is_stale=True,
            safe_to_interpret_as_no_fall=False,
            reason="stale",
        )
    if age_ms > thresholds.delayed_ms:
        return FrameFreshness(
            frame_status="delayed",
            is_stale=False,
            safe_to_interpret_as_no_fall=True,
            reason="delayed",
        )
    return FrameFreshness(
        frame_status="fresh",
        is_stale=False,
        safe_to_interpret_as_no_fall=True,
    )


def normalize_camera_state(
    *,
    running: bool,
    connected: bool,
    internal_state: str | None,
    frame_status: str,
    last_error: str | None = None,
    reconnect_reason: str | None = None,
) -> str:
    if not running:
        return "stopped"
    error_state = _state_from_error(last_error or reconnect_reason)
    if error_state:
        return error_state
    state = (internal_state or "").strip().lower()
    if state == "reconnecting":
        return "reconnecting"
    if state == "connecting":
        return "connecting" if frame_status == "no_frame" else _streaming_state(frame_status)
    if state == "stale":
        return "stale"
    if state == "disconnected":
        return "unreachable" if not connected else "connected"
    if not connected:
        return "connecting" if frame_status == "no_frame" else "unreachable"
    if frame_status == "no_frame":
        return "connected"
    return _streaming_state(frame_status)


def unavailable_result(reason: str, *, camera_id: str | None = None) -> dict[str, Any]:
    return {
        "camera_id": camera_id,
        "fall_state": "unavailable",
        "reason": reason,
        "safe_to_interpret_as_no_fall": False,
    }


def _streaming_state(frame_status: str) -> str:
    if frame_status == "fresh":
        return "streaming"
    if frame_status == "delayed":
        return "delayed"
    if frame_status == "stale":
        return "stale"
    return "connected"


def _state_from_error(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    if any(token in lowered for token in ("auth", "401", "403", "unauthorized", "password")):
        return "authentication_failed"
    if any(token in lowered for token in ("stream closed", "closed", "eof", "open failed", "unreachable", "timed out", "timeout", "connect")):
        return "unreachable"
    if any(token in lowered for token in ("decode", "protocol", "invalid jpeg", "jpeg decode", "decode jpeg")):
        return "decode_error"
    return None
