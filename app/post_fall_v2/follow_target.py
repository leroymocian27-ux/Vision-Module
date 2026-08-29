from __future__ import annotations

import json
import math
import socket
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np

from app.core.logger import get_logger


logger = get_logger(__name__)

FOLLOW_TARGET_SCHEMA = "go2_follow_target.v1"
TargetTrackingState = Literal["disabled", "fresh", "grace", "stale", "unavailable"]


@dataclass(frozen=True)
class FollowTargetState:
    sequence: int
    target_valid: bool
    follow_active: bool
    bearing_deg: float | None
    distance_m: float | None
    relative_x_m: float | None = None
    relative_y_m: float | None = None
    source_timestamp_ms: int | None = None
    sent_timestamp_ms: int | None = None
    received_monotonic: float = 0.0
    schema_version: str = FOLLOW_TARGET_SCHEMA

    def age_ms(self, now_monotonic: float | None = None) -> float:
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        return max(0.0, (now - self.received_monotonic) * 1000.0)

    def freshness(self, *, fresh_ms: int, grace_ms: int, now_monotonic: float | None = None) -> TargetTrackingState:
        age_ms = self.age_ms(now_monotonic)
        if age_ms <= max(0, int(fresh_ms)):
            return "fresh"
        if age_ms <= max(int(fresh_ms), int(grace_ms)):
            return "grace"
        return "stale"

    def to_record(self, now_monotonic: float | None = None) -> dict[str, Any]:
        record = asdict(self)
        record["age_ms"] = round(self.age_ms(now_monotonic), 2)
        return record


@dataclass(frozen=True)
class TargetRegionConfig:
    enabled: bool
    fresh_ms: int = 300
    grace_ms: int = 700
    camera_hfov_deg: float = 90.0
    camera_yaw_offset_deg: float = 0.0
    fresh_width_ratio: float = 0.50
    grace_width_ratio: float = 0.70


@dataclass(frozen=True)
class TargetRegionResult:
    frame: np.ndarray | None
    tracking_state: TargetTrackingState
    target_binding: dict[str, Any]
    processing_ms: float

    @property
    def available(self) -> bool:
        return self.tracking_state in {"disabled", "fresh", "grace"}


class FollowTargetReceiver:
    """Latest-only UDP receiver for Go2 follow-target telemetry."""

    def __init__(self, *, host: str = "0.0.0.0", port: int = 8766, enabled: bool = True) -> None:
        self.host = host
        self.port = int(port)
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._latest_state: FollowTargetState | None = None
        self._last_sequence: int | None = None
        self._packet_count = 0
        self._invalid_count = 0
        self._out_of_order_count = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"follow-target-udp-{self.port}",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def latest(self) -> FollowTargetState | None:
        with self._lock:
            return self._latest_state

    def status(self, *, now_monotonic: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now_monotonic is None else float(now_monotonic)
        with self._lock:
            latest = self._latest_state
            running = bool(self._thread is not None and self._thread.is_alive())
            return {
                "enabled": self.enabled,
                "running": running,
                "host": self.host,
                "port": self.port,
                "latest_state": latest.to_record(now) if latest is not None else None,
                "latest_age_ms": round(latest.age_ms(now), 2) if latest is not None else None,
                "latest_sequence": latest.sequence if latest is not None else None,
                "packet_count": self._packet_count,
                "invalid_count": self._invalid_count,
                "out_of_order_count": self._out_of_order_count,
                "last_error": self._last_error,
            }

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.05)
        try:
            sock.bind((self.host, self.port))
            self._socket = sock
            logger.info("follow_target_receiver_started host=%s port=%s", self.host, self.port)
            while not self._stop_event.is_set():
                try:
                    data, _addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError as exc:
                    if not self._stop_event.is_set():
                        self._set_error(str(exc))
                    break
                self._handle_packet(data, time.monotonic())
        finally:
            try:
                sock.close()
            except OSError:
                pass
            self._socket = None
            logger.info("follow_target_receiver_stopped host=%s port=%s", self.host, self.port)

    def _handle_packet(self, data: bytes, received_monotonic: float) -> None:
        try:
            payload = json.loads(data.decode("utf-8"))
            state = _parse_state(payload, received_monotonic)
        except Exception as exc:
            with self._lock:
                self._invalid_count += 1
                self._last_error = str(exc)
            return
        with self._lock:
            last_sequence = self._last_sequence
            if last_sequence is not None and state.sequence <= last_sequence:
                self._out_of_order_count += 1
                return
            self._packet_count += 1
            self._last_sequence = state.sequence
            self._latest_state = state
            self._last_error = None

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message


class TargetRegionExtractor:
    def __init__(self, config: TargetRegionConfig) -> None:
        self.config = config

    def extract(self, frame: np.ndarray, state: FollowTargetState | None) -> TargetRegionResult:
        started = time.monotonic()
        height, width = frame.shape[:2]
        if not self.config.enabled:
            return self._result(frame, "disabled", width, height, None, None, started, reason="disabled")
        if state is None:
            return self._result(None, "unavailable", width, height, None, None, started, reason="no_target_packet")
        if not state.target_valid:
            return self._result(None, "unavailable", width, height, state, None, started, reason="target_invalid")
        if not _valid_bearing(state.bearing_deg):
            return self._result(None, "unavailable", width, height, state, None, started, reason="bearing_invalid")
        freshness = state.freshness(
            fresh_ms=self.config.fresh_ms,
            grace_ms=self.config.grace_ms,
        )
        if freshness == "stale":
            return self._result(None, "unavailable", width, height, state, None, started, reason="target_stale")

        width_ratio = self.config.fresh_width_ratio if freshness == "fresh" else self.config.grace_width_ratio
        roi = self._roi_from_bearing(width, height, state.bearing_deg, width_ratio)
        x1, y1, x2, y2 = roi
        cropped = frame[y1:y2, x1:x2].copy()
        return self._result(cropped, freshness, width, height, state, roi, started, reason="target_roi")

    def status_from_state(self, state: FollowTargetState | None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"tracking_state": "disabled", "valid": False, "age_ms": None}
        if state is None:
            return {"tracking_state": "unavailable", "valid": False, "age_ms": None}
        tracking_state = state.freshness(fresh_ms=self.config.fresh_ms, grace_ms=self.config.grace_ms)
        valid = bool(state.target_valid and _valid_bearing(state.bearing_deg) and tracking_state in {"fresh", "grace"})
        return {
            "tracking_state": tracking_state if valid else "unavailable",
            "valid": valid,
            "age_ms": round(state.age_ms(), 2),
            "bearing_deg": state.bearing_deg,
            "distance_m": state.distance_m,
            "sequence": state.sequence,
            "follow_active": state.follow_active,
        }

    def _roi_from_bearing(self, width: int, height: int, bearing_deg: float, width_ratio: float) -> tuple[int, int, int, int]:
        effective_bearing = math.radians(float(bearing_deg) + self.config.camera_yaw_offset_deg)
        half_fov = math.radians(max(1.0, min(179.0, self.config.camera_hfov_deg)) / 2.0)
        normalized = math.tan(effective_bearing) / math.tan(half_fov)
        x_center = width * 0.5 + normalized * width * 0.5
        x_center = max(0.0, min(float(width - 1), x_center))
        roi_width = max(1.0, float(width) * max(0.05, min(1.0, float(width_ratio))))
        x1 = max(0, min(width - 1, int(round(x_center - roi_width / 2.0))))
        x2 = max(x1 + 1, min(width, int(round(x_center + roi_width / 2.0))))
        return (x1, 0, x2, height)

    def _result(
        self,
        frame: np.ndarray | None,
        tracking_state: TargetTrackingState,
        original_width: int,
        original_height: int,
        state: FollowTargetState | None,
        roi: tuple[int, int, int, int] | None,
        started: float,
        *,
        reason: str,
    ) -> TargetRegionResult:
        binding = {
            "schema_version": "post_fall_v2_target_binding.v1",
            "source": "go2_follow_target_udp" if self.config.enabled else "disabled",
            "target_tracking_state": tracking_state,
            "reason": reason,
            "original_width": original_width,
            "original_height": original_height,
            "roi": list(roi) if roi is not None else None,
            "roi_width": (roi[2] - roi[0]) if roi is not None else None,
            "roi_height": (roi[3] - roi[1]) if roi is not None else None,
            "fresh_ms": self.config.fresh_ms,
            "grace_ms": self.config.grace_ms,
            "camera_hfov_deg": self.config.camera_hfov_deg,
            "camera_yaw_offset_deg": self.config.camera_yaw_offset_deg,
            "processing_ms": round((time.monotonic() - started) * 1000.0, 3),
        }
        if state is not None:
            binding.update(
                {
                    "target_valid": state.target_valid,
                    "follow_active": state.follow_active,
                    "target_age_ms": round(state.age_ms(), 2),
                    "bearing_deg": state.bearing_deg,
                    "distance_m": state.distance_m,
                    "relative_x_m": state.relative_x_m,
                    "relative_y_m": state.relative_y_m,
                    "sequence": state.sequence,
                    "source_timestamp_ms": state.source_timestamp_ms,
                    "sent_timestamp_ms": state.sent_timestamp_ms,
                }
            )
        else:
            binding.update(
                {
                    "target_valid": False,
                    "follow_active": False,
                    "target_age_ms": None,
                    "bearing_deg": None,
                    "distance_m": None,
                    "sequence": None,
                }
            )
        return TargetRegionResult(
            frame=frame,
            tracking_state=tracking_state,
            target_binding=binding,
            processing_ms=binding["processing_ms"],
        )


def _parse_state(payload: Any, received_monotonic: float) -> FollowTargetState:
    if not isinstance(payload, dict):
        raise ValueError("follow target packet must be a JSON object")
    schema_version = str(payload.get("schema_version") or payload.get("schema") or "")
    if schema_version != FOLLOW_TARGET_SCHEMA:
        raise ValueError(f"unsupported schema_version: {schema_version!r}")
    sequence = int(payload["sequence"])
    target_valid = bool(payload.get("target_valid", False))
    follow_active = bool(payload.get("follow_active", False))
    return FollowTargetState(
        schema_version=schema_version,
        sequence=sequence,
        target_valid=target_valid,
        follow_active=follow_active,
        bearing_deg=_optional_float(payload.get("bearing_deg")),
        distance_m=_optional_float(payload.get("distance_m")),
        relative_x_m=_optional_float(payload.get("relative_x_m")),
        relative_y_m=_optional_float(payload.get("relative_y_m")),
        source_timestamp_ms=_optional_int(payload.get("source_timestamp_ms")),
        sent_timestamp_ms=_optional_int(payload.get("sent_timestamp_ms") or payload.get("timestamp_ms")),
        received_monotonic=received_monotonic,
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _valid_bearing(value: float | None) -> bool:
    return value is not None and math.isfinite(float(value))
