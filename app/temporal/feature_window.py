from __future__ import annotations

import threading
from collections import deque

from app.temporal.schemas import TargetFeature


class FeatureWindow:
    def __init__(self, window_size: int) -> None:
        self.window_size = window_size
        self._windows: dict[str, deque[TargetFeature]] = {}
        self._lock = threading.Lock()

    def append(self, key: str, feature: TargetFeature) -> None:
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                window = deque(maxlen=self.window_size)
                self._windows[key] = window
            window.append(feature)

    def get_window(self, key: str) -> list[TargetFeature]:
        with self._lock:
            window = self._windows.get(key)
            return list(window) if window is not None else []

    def clear(self, key: str) -> None:
        with self._lock:
            self._windows.pop(key, None)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._windows.keys())

    def previous(self, key: str) -> TargetFeature | None:
        with self._lock:
            window = self._windows.get(key)
            if not window:
                return None
            return window[-1]

    def status(self) -> dict:
        with self._lock:
            return {
                "window_size": self.window_size,
                "active_tracks": len(self._windows),
            }
