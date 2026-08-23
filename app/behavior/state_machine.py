from __future__ import annotations

import time

from app.behavior.rules import BehaviorRules
from app.behavior.schemas import BehaviorFeatures, BehaviorResult, BehaviorState
from app.core.config import Settings


class BehaviorStateMachine:
    def __init__(self, settings: Settings, rules: BehaviorRules) -> None:
        self.settings = settings
        self.rules = rules
        self._state_by_track: dict[tuple[str, int], BehaviorState] = {}
        self._last_seen_at: dict[tuple[str, int], float] = {}

    def update(
        self,
        camera_id: str,
        track_id: int | None,
        features: BehaviorFeatures,
        identity_state: str | None = None,
    ) -> BehaviorResult:
        decision = self.rules.classify(features)
        state = decision.state
        confidence = decision.confidence

        if self.rules.has_rapid_descent(features):
            confidence = max(confidence, 0.78)
            if state not in {BehaviorState.LYING, BehaviorState.SITTING}:
                state = BehaviorState.BENDING
        if self.rules.has_long_still(features) and state in {BehaviorState.LYING, BehaviorState.SITTING}:
            confidence = min(0.95, confidence + 0.08)

        if identity_state == "target_reacquiring":
            self.reset(camera_id, track_id)
            state = BehaviorState.UNKNOWN
            confidence = 0.3

        if track_id is not None:
            key = (camera_id, track_id)
            self._state_by_track[key] = state
            self._last_seen_at[key] = time.monotonic()

        return BehaviorResult(
            behavior_state=state.value,
            behavior_confidence=round(confidence, 3),
            behavior_features=features,
        )

    def reset(self, camera_id: str, track_id: int | None = None) -> None:
        if track_id is None:
            for key in [key for key in self._state_by_track if key[0] == camera_id]:
                self._state_by_track.pop(key, None)
                self._last_seen_at.pop(key, None)
            return
        key = (camera_id, track_id)
        self._state_by_track.pop(key, None)
        self._last_seen_at.pop(key, None)

    def state_for(self, camera_id: str, track_id: int | None = None) -> BehaviorState:
        if track_id is not None:
            return self._state_by_track.get((camera_id, track_id), BehaviorState.UNKNOWN)
        candidates = [
            (seen_at, state)
            for (stored_camera_id, _stored_track_id), state in self._state_by_track.items()
            if stored_camera_id == camera_id
            for seen_at in [self._last_seen_at.get((stored_camera_id, _stored_track_id), 0.0)]
        ]
        if not candidates:
            return BehaviorState.UNKNOWN
        return max(candidates, key=lambda item: item[0])[1]
