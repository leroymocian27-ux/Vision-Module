from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from app.events.schemas import EventType, FallEventRecord, RiskLevel


@dataclass(frozen=True)
class IncidentResolution:
    record: FallEventRecord
    created: bool
    upgraded: bool


class IncidentManager:
    """Own a short-lived incident lifecycle for one camera and tracked person."""

    def __init__(
        self,
        *,
        cooldown_window_seconds: float = 30.0,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cooldown_window_seconds = max(0.0, float(cooldown_window_seconds))
        self._monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._active: dict[str, tuple[FallEventRecord, float]] = {}
        self._sequence = 0

    def resolve(
        self,
        *,
        camera_id: str,
        track_id: int | None,
        fall_state: str,
        risk_level: RiskLevel = "medium",
        timestamp: str,
        stream_name: str = "primary",
        person_id: str | None = None,
        trigger_frame_seq: int | None = None,
        bbox: list[float] | None = None,
        risk_score: float | None = None,
        fall_probability: float | None = None,
        fall_evidence_score: float | None = None,
        adl_suppression_score: float | None = None,
        metadata: dict | None = None,
    ) -> IncidentResolution:
        event_type = _event_type_for_state(fall_state)
        key = self._identity_key(camera_id, track_id)
        now = self._monotonic_clock()
        with self._lock:
            existing = self._active.get(key)
            if existing is not None and now - existing[1] <= self.cooldown_window_seconds:
                previous, _ = existing
                upgraded = previous.event_type != "fallen_confirmed" and event_type == "fallen_confirmed"
                record = previous.model_copy(
                    update={
                        "stream_name": stream_name,
                        "person_id": person_id or previous.person_id,
                        "event_type": "fallen_confirmed" if upgraded else previous.event_type,
                        "fall_state": fall_state,
                        "risk_level": _max_risk_level(previous.risk_level, risk_level),
                        "risk_score": _max_optional(previous.risk_score, risk_score),
                        "trigger_frame_seq": trigger_frame_seq or previous.trigger_frame_seq,
                        "trigger_timestamp": timestamp,
                        "bbox": bbox or previous.bbox,
                        "fall_probability": _max_optional(previous.fall_probability, fall_probability),
                        "fall_evidence_score": _max_optional(previous.fall_evidence_score, fall_evidence_score),
                        "adl_suppression_score": adl_suppression_score
                        if adl_suppression_score is not None
                        else previous.adl_suppression_score,
                        "metadata": {**previous.metadata, **(metadata or {})},
                    }
                )
                self._active[key] = (record, now)
                return IncidentResolution(record=record, created=False, upgraded=upgraded)

            self._sequence += 1
            record = FallEventRecord(
                incident_id=self._new_incident_id(camera_id, track_id, timestamp),
                camera_id=camera_id,
                stream_name=stream_name,
                track_id=track_id,
                person_id=person_id,
                event_type=event_type,
                fall_state=fall_state,
                risk_level=risk_level,
                risk_score=risk_score,
                trigger_frame_seq=trigger_frame_seq,
                trigger_timestamp=timestamp,
                bbox=bbox,
                fall_probability=fall_probability,
                fall_evidence_score=fall_evidence_score,
                adl_suppression_score=adl_suppression_score,
                metadata=metadata or {},
            )
            self._active[key] = (record, now)
            return IncidentResolution(record=record, created=True, upgraded=False)

    def get_active(self, *, camera_id: str, track_id: int | None) -> FallEventRecord | None:
        key = self._identity_key(camera_id, track_id)
        now = self._monotonic_clock()
        with self._lock:
            active = self._active.get(key)
            if active is None:
                return None
            record, seen_at = active
            if now - seen_at > self.cooldown_window_seconds:
                self._active.pop(key, None)
                return None
            return record.model_copy(deep=True)

    def _new_incident_id(self, camera_id: str, track_id: int | None, timestamp: str) -> str:
        camera_slug = _safe_slug(camera_id)
        track_slug = "untracked" if track_id is None else str(track_id)
        timestamp_slug = _timestamp_slug(timestamp)
        return f"vision-fall-{camera_slug}-track-{track_slug}-{timestamp_slug}-{self._sequence:04d}"

    @staticmethod
    def _identity_key(camera_id: str, track_id: int | None) -> str:
        return f"{camera_id}:track:{track_id if track_id is not None else 'untracked'}"


def _event_type_for_state(fall_state: str) -> EventType:
    return "fallen_confirmed" if fall_state.lower() in {"fallen_confirmed", "confirmed_fall"} else "fall_candidate"


def _max_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _max_risk_level(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    levels: dict[RiskLevel, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return left if levels[left] >= levels[right] else right


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return slug or "camera"


def _timestamp_slug(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
