from __future__ import annotations

import time

from app.core.config import Settings
from app.tracking.schemas import TargetState, TrackedObject


class TargetManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._state = TargetState.IDLE
        self._target_track_id: int | None = None
        self._last_seen_at: float | None = None

    @property
    def state(self) -> TargetState:
        return self._state

    @property
    def target_track_id(self) -> int | None:
        return self._target_track_id

    @property
    def active_target_exists(self) -> bool:
        return self._target_track_id is not None

    def update(self, objects: list[TrackedObject]) -> list[TrackedObject]:
        now = time.monotonic()
        if not objects:
            self._handle_no_objects(now)
            return []

        target = self._find_target(objects)
        if target is None and self._can_select_new_target(now):
            target = self._select_initial_target(objects)
            self._target_track_id = target.track_id

        if target is not None:
            self._state = TargetState.TARGET_LOCKED
            self._last_seen_at = now

        return [self._mark_object(item) for item in objects]

    def reset(self) -> None:
        self._state = TargetState.IDLE
        self._target_track_id = None
        self._last_seen_at = None

    def _find_target(self, objects: list[TrackedObject]) -> TrackedObject | None:
        if self._target_track_id is None:
            return None
        for item in objects:
            if item.track_id == self._target_track_id:
                return item
        return None

    def _select_initial_target(self, objects: list[TrackedObject]) -> TrackedObject:
        return max(objects, key=lambda item: (item.area, item.confidence))

    def _can_select_new_target(self, now: float) -> bool:
        if self._target_track_id is None:
            return True
        if self._state != TargetState.TARGET_REACQUIRING:
            return False
        if self._last_seen_at is None:
            return True
        elapsed_ms = (now - self._last_seen_at) * 1000
        return elapsed_ms >= self.settings.target_reacquire_after_ms

    def _handle_no_objects(self, now: float) -> None:
        if self._target_track_id is None:
            self._state = TargetState.IDLE
            return
        if self._last_seen_at is None:
            self._state = TargetState.TARGET_LOST
            self._last_seen_at = now
            return

        elapsed_ms = (now - self._last_seen_at) * 1000
        if elapsed_ms >= self.settings.target_reacquire_after_ms:
            self._state = TargetState.TARGET_REACQUIRING
        elif elapsed_ms >= self.settings.target_lost_after_ms:
            self._state = TargetState.TARGET_LOST

    def _mark_object(self, item: TrackedObject) -> TrackedObject:
        is_target = self._target_track_id is not None and item.track_id == self._target_track_id
        return item.model_copy(
            update={
                "is_target": is_target,
                "person_id": None,
                "person_name": None,
                "identity_state": self._state.value if is_target else TargetState.IDLE.value,
            }
        )
