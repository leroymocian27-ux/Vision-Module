from __future__ import annotations

import threading

from app.schemas.vision_result import VisionResult


class ResultStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, VisionResult] = {}

    def update(self, result: VisionResult) -> None:
        with self._lock:
            self._latest[result.camera_id] = result

    def latest(self, camera_id: str) -> VisionResult | None:
        with self._lock:
            return self._latest.get(camera_id)

    def all_latest(self) -> list[VisionResult]:
        with self._lock:
            return list(self._latest.values())

