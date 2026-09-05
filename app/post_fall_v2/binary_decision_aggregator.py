from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from statistics import mean
from uuid import uuid4

from app.post_fall_v2.schemas import (
    BinaryAggregateDecision,
    BinaryAggregateState,
    BinaryDecisionEvidence,
    BinaryFrameResult,
    utc_now_iso,
)


@dataclass(frozen=True)
class BinaryDecisionAggregatorConfig:
    threshold: float
    window_size: int = 8
    min_positive_frames: int = 4
    min_consecutive_frames: int = 3
    candidate_min_ms: int = 0
    high_confidence_threshold: float = 0.90
    high_confidence_min_consecutive_frames: int = 2
    recovery_threshold: float = 0.45
    recovery_min_consecutive_frames: int = 5
    recovery_min_ms: int = 1500
    cooldown_ms: int = 3000


class BinaryDecisionAggregator:
    """Turns binary frame scores into one debounced incident stream."""

    def __init__(self, config: BinaryDecisionAggregatorConfig) -> None:
        self.config = config
        self._windows: dict[str, deque[tuple[float, BinaryFrameResult]]] = {}
        self._state: dict[str, BinaryAggregateState] = {}
        self._candidate_started_at: dict[str, float] = {}
        self._recovery_started_at: dict[str, float] = {}
        self._cooldown_started_at: dict[str, float] = {}
        self._active_incident_id: dict[str, str] = {}
        self._last_decision: dict[str, BinaryAggregateDecision] = {}
        self._event_count: dict[str, int] = {}

    def update(self, result: BinaryFrameResult, *, now: float | None = None) -> BinaryAggregateDecision:
        now = time.monotonic() if now is None else now
        camera_id = result.camera_id
        window = self._windows.setdefault(camera_id, deque(maxlen=max(1, self.config.window_size)))
        window.append((now, result))

        state = self._state.get(camera_id, "NORMAL")
        is_positive = self._is_positive(result)
        recovery_low_count = self._recovery_low_count(window)
        recovered = recovery_low_count >= self.config.recovery_min_consecutive_frames
        normal_candidate = self._normal_candidate_condition(window, now)
        high_conf_candidate = self._high_confidence_candidate_condition(window)
        candidate_triggered = False
        trigger_reason = "none"
        event_created = False
        rearmed = False
        reason = "none"

        if state == "NORMAL":
            if normal_candidate or high_conf_candidate:
                self._candidate_started_at[camera_id] = now
                incident_id = self._active_incident_id.get(camera_id) or self._new_incident_id(camera_id)
                self._active_incident_id[camera_id] = incident_id
                self._event_count[camera_id] = self._event_count.get(camera_id, 0) + 1
                state = "EVENT_ACTIVE"
                event_created = True
                candidate_triggered = True
                trigger_reason = "high_confidence_fast_path" if high_conf_candidate else "normal_temporal_confirmation"
                reason = trigger_reason
            elif is_positive:
                reason = "temporal_collecting"
            else:
                reason = "non_fall"
        elif state == "FALL_CANDIDATE":
            if recovered:
                self._cooldown_started_at[camera_id] = now
                self._active_incident_id.pop(camera_id, None)
                self._candidate_started_at.pop(camera_id, None)
                state = "COOLDOWN"
                reason = "recovery_confirmed"
            else:
                state = "EVENT_ACTIVE"
                reason = "event_active_fall_persisting"
        elif state == "EVENT_ACTIVE":
            if recovered:
                self._cooldown_started_at[camera_id] = now
                self._active_incident_id.pop(camera_id, None)
                self._candidate_started_at.pop(camera_id, None)
                self._recovery_started_at.pop(camera_id, None)
                state = "COOLDOWN"
                reason = "recovery_confirmed"
            elif recovery_low_count > 0:
                self._recovery_started_at.setdefault(camera_id, now)
                state = "RECOVERY_PENDING"
                reason = "recovery_pending"
            else:
                self._recovery_started_at.pop(camera_id, None)
                reason = "event_active_fall_persisting"
        elif state == "RECOVERY_PENDING":
            if recovered:
                self._cooldown_started_at[camera_id] = now
                self._active_incident_id.pop(camera_id, None)
                self._candidate_started_at.pop(camera_id, None)
                self._recovery_started_at.pop(camera_id, None)
                state = "COOLDOWN"
                reason = "recovery_confirmed"
            elif recovery_low_count > 0:
                self._recovery_started_at.setdefault(camera_id, now)
                reason = "recovery_collecting"
            else:
                self._recovery_started_at.pop(camera_id, None)
                state = "EVENT_ACTIVE"
                reason = "fall_returned_before_recovery"
        elif state == "COOLDOWN":
            if now - self._cooldown_started_at.get(camera_id, now) >= self.config.cooldown_ms / 1000:
                state = "NORMAL"
                rearmed = True
                reason = "post_fall_v2_rearmed"
                self._cooldown_started_at.pop(camera_id, None)
                if normal_candidate or high_conf_candidate:
                    self._candidate_started_at[camera_id] = now
                    incident_id = self._active_incident_id.get(camera_id) or self._new_incident_id(camera_id)
                    self._active_incident_id[camera_id] = incident_id
                    self._event_count[camera_id] = self._event_count.get(camera_id, 0) + 1
                    state = "EVENT_ACTIVE"
                    event_created = True
                    candidate_triggered = True
                    trigger_reason = "high_confidence_fast_path" if high_conf_candidate else "normal_temporal_confirmation"
                    reason = trigger_reason
            else:
                reason = "cooldown"

        self._state[camera_id] = state
        decision = self._build_decision(
            camera_id=camera_id,
            result=result,
            state=state,
            window=window,
            event_created=event_created,
            rearmed=rearmed,
            reason=reason,
            frame_positive=is_positive,
            normal_candidate_condition=normal_candidate,
            high_conf_candidate_condition=high_conf_candidate,
            candidate_triggered=candidate_triggered,
            recovery_low_count=recovery_low_count,
            trigger_reason=trigger_reason,
            now=now,
        )
        self._last_decision[camera_id] = decision
        return decision

    def status(self, camera_id: str | None = None) -> dict:
        if camera_id:
            return self._status_one(camera_id)
        return {
            "cameras": {key: self._status_one(key) for key in sorted(self._state)},
            "event_count": sum(self._event_count.values()),
        }

    def latest(self, camera_id: str) -> BinaryAggregateDecision | None:
        return self._last_decision.get(camera_id)

    def recent_probabilities(self, camera_id: str, *, limit: int = 3) -> list[float]:
        window = self._windows.get(camera_id)
        if not window:
            return []
        probabilities = [
            float(item.fall_probability)
            for _, item in window
            if item.valid and item.fall_probability is not None
        ]
        return [round(value, 6) for value in probabilities[-max(1, int(limit)):]]

    def persistent_strong_candidate(
        self,
        camera_id: str,
        *,
        threshold: float = 0.8,
        min_count: int = 2,
        limit: int = 3,
    ) -> bool:
        probabilities = self.recent_probabilities(camera_id, limit=limit)
        return sum(1 for value in probabilities if value >= threshold) >= max(1, int(min_count))

    def reset(self, camera_id: str) -> None:
        self._windows.pop(camera_id, None)
        self._state.pop(camera_id, None)
        self._candidate_started_at.pop(camera_id, None)
        self._recovery_started_at.pop(camera_id, None)
        self._cooldown_started_at.pop(camera_id, None)
        self._active_incident_id.pop(camera_id, None)
        self._last_decision.pop(camera_id, None)
        self._event_count.pop(camera_id, None)

    def _is_confirmed(self, camera_id: str, window: deque[tuple[float, BinaryFrameResult]], now: float) -> bool:
        candidate_started = self._candidate_started_at.get(camera_id)
        if candidate_started is None:
            return False
        duration_ms = int((now - candidate_started) * 1000)
        return (
            self._positive_count(window) >= self.config.min_positive_frames
            and self._consecutive_positive_count(window) >= self.config.min_consecutive_frames
            and duration_ms >= self.config.candidate_min_ms
        )

    def _normal_candidate_condition(self, window: deque[tuple[float, BinaryFrameResult]], now: float) -> bool:
        if len(window) < self.config.window_size:
            return False
        duration_ms = self._positive_duration_ms(window, now)
        return (
            self._positive_count(window) >= self.config.min_positive_frames
            and self._consecutive_positive_count(window) >= self.config.min_consecutive_frames
            and duration_ms >= self.config.candidate_min_ms
        )

    def _high_confidence_candidate_condition(self, window: deque[tuple[float, BinaryFrameResult]]) -> bool:
        return self._high_confidence_consecutive_count(window) >= self.config.high_confidence_min_consecutive_frames

    def _build_decision(
        self,
        *,
        camera_id: str,
        result: BinaryFrameResult,
        state: BinaryAggregateState,
        window: deque[tuple[float, BinaryFrameResult]],
        event_created: bool,
        rearmed: bool,
        reason: str,
        frame_positive: bool,
        normal_candidate_condition: bool,
        high_conf_candidate_condition: bool,
        candidate_triggered: bool,
        recovery_low_count: int,
        trigger_reason: str,
        now: float,
    ) -> BinaryAggregateDecision:
        probabilities = [
            item.fall_probability
            for _, item in window
            if item.valid and item.fall_probability is not None
        ]
        candidate_started = self._candidate_started_at.get(camera_id)
        candidate_duration_ms = int((now - candidate_started) * 1000) if candidate_started is not None else 0
        evidence = BinaryDecisionEvidence(
            window_size=len(window),
            positive_count=self._positive_count(window),
            consecutive_positive_count=self._consecutive_positive_count(window),
            mean_fall_probability=round(mean(probabilities), 6) if probabilities else None,
            max_fall_probability=round(max(probabilities), 6) if probabilities else None,
            candidate_duration_ms=candidate_duration_ms,
            threshold=self.config.threshold,
            frame_positive=frame_positive,
            tail_consecutive_positive=self._consecutive_positive_count(window),
            high_conf_consecutive=self._high_confidence_consecutive_count(window),
            normal_candidate_condition=normal_candidate_condition,
            high_conf_candidate_condition=high_conf_candidate_condition,
            candidate_triggered=candidate_triggered,
            recovery_low_count=recovery_low_count,
            candidate_active=state in {"FALL_CANDIDATE", "EVENT_ACTIVE", "RECOVERY_PENDING", "FALL_CONFIRMED"},
            trigger_reason=trigger_reason,
            probability_window=self.recent_probabilities(camera_id, limit=3),
            persistent_strong_candidate=self.persistent_strong_candidate(camera_id),
        )
        return BinaryAggregateDecision(
            state=state,
            camera_id=camera_id,
            frame_id=result.frame_id,
            frame_seq=result.frame_seq,
            decision_label=result.decision_label,
            fall_probability=result.fall_probability,
            incident_id=self._active_incident_id.get(camera_id),
            event_created=event_created,
            rearmed=rearmed,
            evidence=evidence,
            reason=reason,
            updated_at=utc_now_iso(),
        )

    def _positive_count(self, window: deque[tuple[float, BinaryFrameResult]]) -> int:
        return sum(
            1
            for _, item in window
            if self._is_positive(item)
        )

    def _consecutive_positive_count(self, window: deque[tuple[float, BinaryFrameResult]]) -> int:
        count = 0
        for _, item in reversed(window):
            if self._is_positive(item):
                count += 1
                continue
            break
        return count

    def _high_confidence_consecutive_count(self, window: deque[tuple[float, BinaryFrameResult]]) -> int:
        count = 0
        for _, item in reversed(window):
            if (
                item.valid
                and item.fall_probability is not None
                and item.fall_probability >= self.config.high_confidence_threshold
            ):
                count += 1
                continue
            break
        return count

    def _recovery_low_count(self, window: deque[tuple[float, BinaryFrameResult]]) -> int:
        count = 0
        for _, item in reversed(window):
            if (
                item.valid
                and item.fall_probability is not None
                and item.fall_probability < self.config.recovery_threshold
            ):
                count += 1
                continue
            break
        return count

    def _is_positive(self, result: BinaryFrameResult) -> bool:
        return bool(
            result.valid
            and result.fall_probability is not None
            and result.fall_probability >= self.config.threshold
        )

    def _positive_duration_ms(self, window: deque[tuple[float, BinaryFrameResult]], now: float) -> int:
        for item_time, item in window:
            if self._is_positive(item):
                return max(0, int((now - item_time) * 1000))
        return 0

    def _status_one(self, camera_id: str) -> dict:
        latest = self._last_decision.get(camera_id)
        return {
            "state": self._state.get(camera_id, "NORMAL"),
            "active_incident_id": self._active_incident_id.get(camera_id),
            "event_count": self._event_count.get(camera_id, 0),
            "last_probability": latest.fall_probability if latest else None,
            "last_decision_label": latest.decision_label if latest else None,
            "last_reason": latest.reason if latest else None,
        }

    @staticmethod
    def _new_incident_id(camera_id: str) -> str:
        return f"pfv2-{camera_id}-{uuid4().hex[:12]}"
