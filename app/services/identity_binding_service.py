from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.integration.identity_client import IdentityClient
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


class IdentityBindingService:
    def __init__(self, settings: Settings, client: IdentityClient) -> None:
        self.settings = settings
        self.client = client
        self._lock = threading.Lock()
        self._last_attempt_at: dict[tuple[str, int], float] = {}
        self._track_bindings: dict[tuple[str, int], tuple[str, str | None, float | None]] = {}
        self._track_binding_at: dict[tuple[str, int], float] = {}
        self._inflight: set[tuple[str, int]] = set()
        self._bound_person_id: str | None = None
        self._bound_person_name: str | None = None
        self._last_match_score: float | None = None
        self._last_match_at: float | None = None
        self._last_match_latency_ms: float | None = None
        self._last_health_at: float | None = None
        self._service_available: bool = False
        self._recognizer_loaded: bool = False
        self._registered_count: int = 0
        self._last_error: str | None = None
        self._skipped_due_to_inflight = 0

    @property
    def service_available(self) -> bool:
        with self._lock:
            return self._service_available

    @property
    def recognizer_loaded(self) -> bool:
        with self._lock:
            return self._recognizer_loaded

    @property
    def registered_count(self) -> int:
        with self._lock:
            return self._registered_count

    @property
    def bound_person_id(self) -> str | None:
        with self._lock:
            return self._bound_person_id

    @property
    def bound_person_name(self) -> str | None:
        with self._lock:
            return self._bound_person_name

    @property
    def last_match_score(self) -> float | None:
        with self._lock:
            return self._last_match_score

    @property
    def last_match_latency_ms(self) -> float | None:
        with self._lock:
            return self._last_match_latency_ms

    @property
    def pending_requests(self) -> int:
        with self._lock:
            return len(self._inflight)

    @property
    def skipped_due_to_inflight(self) -> int:
        with self._lock:
            return self._skipped_due_to_inflight

    @property
    def cache_age_ms(self) -> float | None:
        with self._lock:
            if self._last_match_at is None:
                return None
            return round((time.monotonic() - self._last_match_at) * 1000, 2)

    @property
    def health_cache_age_ms(self) -> float | None:
        with self._lock:
            if self._last_health_at is None:
                return None
            return round((time.monotonic() - self._last_health_at) * 1000, 2)

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def reset_camera(self, camera_id: str) -> None:
        with self._lock:
            keys = [key for key in self._track_bindings if key[0] == camera_id]
            for key in keys:
                self._track_bindings.pop(key, None)
                self._track_binding_at.pop(key, None)
                self._last_attempt_at.pop(key, None)
                self._inflight.discard(key)
            self._bound_person_id = None
            self._bound_person_name = None
            self._last_match_score = None
            self._last_match_at = None
            self._last_match_latency_ms = None
            self._last_error = None

    def refresh_health(self) -> None:
        with self._lock:
            if self._last_health_at is not None:
                age_ms = (time.monotonic() - self._last_health_at) * 1000
                if age_ms < self.settings.identity_health_ttl_ms:
                    return
        health = self.client.healthz()
        with self._lock:
            self._service_available = health.available
            self._recognizer_loaded = health.recognizer_loaded
            self._registered_count = health.registered_count
            self._last_error = health.last_error
            self._last_health_at = time.monotonic()

    def enrich(
        self,
        camera_id: str,
        frame: np.ndarray,
        objects: list[DetectedObject],
    ) -> list[DetectedObject]:
        if not self.settings.enable_identity_binding:
            return objects

        if self.settings.identity_binding_async:
            return self.apply_cached(camera_id, objects)

        try:
            self.refresh_health()
            enriched = [self._apply_existing_binding(camera_id, item) for item in objects]
            target = self._select_match_candidate(enriched)
            if target is None or target.track_id is None:
                return enriched
            if not self._should_attempt(camera_id, target.track_id):
                return enriched

            image_bytes = self._crop_to_jpeg(frame, target.bbox)
            if image_bytes is None:
                return enriched

            match = self.client.match(image_bytes, threshold=self.settings.identity_match_threshold)
            with self._lock:
                self._service_available = match.available
                self._last_error = match.last_error
            if not match.available:
                return enriched
            if not match.matched or not match.person_id:
                return enriched

            with self._lock:
                self._track_bindings[(camera_id, target.track_id)] = (
                    match.person_id,
                    match.person_name,
                    match.score,
                )
                self._bound_person_id = match.person_id
                self._bound_person_name = match.person_name
                self._last_match_score = match.score
                self._last_error = None
            logger.info(
                "identity_track_bound camera_id=%s track_id=%s person_id=%s score=%s",
                camera_id,
                target.track_id,
                match.person_id,
                match.score,
            )
            return [self._apply_existing_binding(camera_id, item) for item in enriched]
        except Exception as exc:
            logger.exception("identity_binding_failed camera_id=%s", camera_id)
            with self._lock:
                self._last_error = str(exc)
            return objects

    def apply_cached(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        if not self.settings.enable_identity_binding:
            return objects
        return [self._apply_existing_binding(camera_id, item) for item in objects]

    def process_candidates(
        self,
        camera_id: str,
        frame: np.ndarray,
        objects: list[DetectedObject],
    ) -> None:
        if not self.settings.enable_identity_binding:
            return
        try:
            self.refresh_health()
            enriched = [self._apply_existing_binding(camera_id, item) for item in objects]
            target = self._select_match_candidate(enriched)
            if target is None or target.track_id is None:
                return
            if not self._should_attempt(camera_id, target.track_id):
                return

            request_key = (camera_id, target.track_id)
            if not self._try_mark_inflight(request_key):
                return
            try:
                image_bytes = self._crop_to_jpeg(frame, target.bbox)
                if image_bytes is None:
                    return

                started = time.monotonic()
                match = self.client.match(image_bytes, threshold=self.settings.identity_match_threshold)
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                with self._lock:
                    self._service_available = match.available
                    self._last_match_latency_ms = latency_ms
                    self._last_error = match.last_error
                if not match.available:
                    return
                if not match.matched or not match.person_id:
                    return

                with self._lock:
                    self._track_bindings[request_key] = (
                        match.person_id,
                        match.person_name,
                        match.score,
                    )
                    self._track_binding_at[request_key] = time.monotonic()
                    self._bound_person_id = match.person_id
                    self._bound_person_name = match.person_name
                    self._last_match_score = match.score
                    self._last_match_at = time.monotonic()
                    self._last_error = None
                logger.info(
                    "identity_track_bound camera_id=%s track_id=%s person_id=%s score=%s latency_ms=%s",
                    camera_id,
                    target.track_id,
                    match.person_id,
                    match.score,
                    latency_ms,
                )
            finally:
                self._clear_inflight(request_key)
        except Exception as exc:
            logger.exception("identity_binding_worker_failed camera_id=%s", camera_id)
            with self._lock:
                self._last_error = str(exc)

    def _select_match_candidate(self, objects: list[DetectedObject]) -> DetectedObject | None:
        targets = [item for item in objects if item.is_target and item.track_id is not None]
        if targets:
            return max(targets, key=self._area)
        candidates = [item for item in objects if item.track_id is not None]
        if not candidates:
            return None
        return max(candidates, key=self._area)

    def _apply_existing_binding(self, camera_id: str, item: DetectedObject) -> DetectedObject:
        if item.track_id is None:
            return item
        with self._lock:
            binding = self._track_bindings.get((camera_id, item.track_id))
        if binding is None:
            return item
        person_id, person_name, _score = binding
        return item.model_copy(
            update={
                "is_target": True,
                "person_id": person_id,
                "person_name": person_name,
                "identity_state": "target_locked",
            }
        )

    def _should_attempt(self, camera_id: str, track_id: int) -> bool:
        now = time.monotonic()
        key = (camera_id, track_id)
        with self._lock:
            if key in self._track_bindings:
                return False
            last_attempt_at = self._last_attempt_at.get(key)
            if last_attempt_at is not None:
                elapsed_ms = (now - last_attempt_at) * 1000
                min_interval_ms = max(
                    self.settings.identity_match_interval_ms,
                    self.settings.identity_match_ttl_ms,
                )
                if elapsed_ms < min_interval_ms:
                    return False
            self._last_attempt_at[key] = now
            return True

    def _try_mark_inflight(self, key: tuple[str, int]) -> bool:
        with self._lock:
            if key in self._inflight or len(self._inflight) >= max(self.settings.identity_max_inflight, 1):
                self._skipped_due_to_inflight += 1
                return False
            self._inflight.add(key)
            return True

    def _clear_inflight(self, key: tuple[str, int]) -> None:
        with self._lock:
            self._inflight.discard(key)

    def _crop_to_jpeg(self, frame: np.ndarray, bbox: list[float]) -> bytes | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        pad_x = (x2 - x1) * self.settings.identity_crop_padding_ratio
        pad_y = (y2 - y1) * self.settings.identity_crop_padding_ratio
        left = max(0, int(x1 - pad_x))
        top = max(0, int(y1 - pad_y))
        right = min(width, int(x2 + pad_x))
        bottom = min(height, int(y2 + pad_y))
        if right <= left or bottom <= top:
            return None
        crop = frame[top:bottom, left:right]
        ok, encoded = cv2.imencode(".jpg", crop)
        if not ok:
            return None
        return encoded.tobytes()

    @staticmethod
    def _area(item: DetectedObject) -> float:
        x1, y1, x2, y2 = item.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
