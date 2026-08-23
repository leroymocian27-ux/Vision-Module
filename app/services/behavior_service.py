from __future__ import annotations

import threading

from app.behavior.feature_extractor import BehaviorFeatureExtractor
from app.behavior.rules import BehaviorRules
from app.behavior.schemas import BehaviorState, BehaviorStatus
from app.behavior.state_machine import BehaviorStateMachine
from app.core.config import Settings
from app.core.logger import get_logger
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


class BehaviorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._extractor = BehaviorFeatureExtractor(settings)
        self._rules = BehaviorRules(settings)
        self._state_machine = BehaviorStateMachine(settings, self._rules)
        self._state: dict[str, str] = {}
        self._last_error: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        if not self.settings.enable_behavior:
            return objects

        try:
            targets = self._select_behavior_targets(objects)
            if not targets:
                return objects

            behavior_by_track: dict[int, dict] = {}
            for target in targets:
                if target.track_id is None or not target.pose:
                    continue
                features = self._extractor.extract(camera_id, target)
                result = self._state_machine.update(
                    camera_id=camera_id,
                    track_id=target.track_id,
                    features=features,
                    identity_state=target.identity_state,
                )
                behavior_by_track[target.track_id] = result.model_dump()
                with self._lock:
                    self._state[camera_id] = result.behavior_state

            if not behavior_by_track:
                return objects

            enriched: list[DetectedObject] = []
            for item in objects:
                behavior = behavior_by_track.get(item.track_id) if item.track_id is not None else None
                enriched.append(item.model_copy(update={"behavior": behavior} if behavior else {}))
            with self._lock:
                self._last_error[camera_id] = None
            return enriched
        except Exception as exc:
            logger.exception("behavior_enrich_failed camera_id=%s", camera_id)
            with self._lock:
                self._last_error[camera_id] = str(exc)
            return objects

    def status(self, camera_id: str | None = None) -> BehaviorStatus:
        key = camera_id or ""
        with self._lock:
            state = self._state.get(key, BehaviorState.UNKNOWN.value)
            last_error = self._last_error.get(key)
        return BehaviorStatus(
            enabled=self.settings.enable_behavior,
            state=state,
            last_error=last_error,
        )

    @staticmethod
    def _select_behavior_targets(objects: list[DetectedObject]) -> list[DetectedObject]:
        targets = [
            item
            for item in objects
            if item.is_target and item.track_id is not None and item.pose is not None
        ]
        if targets:
            return targets[:1]
        candidates = [
            item
            for item in objects
            if item.track_id is not None and item.pose is not None
        ]
        if not candidates:
            return []
        return [max(candidates, key=BehaviorService._area)]

    @staticmethod
    def _area(item: DetectedObject) -> float:
        x1, y1, x2, y2 = item.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
