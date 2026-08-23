from __future__ import annotations

from typing import Protocol

import numpy as np

from app.tracking.schemas import TrackedObject, TrackingDetection, TrackingStatus


class Tracker(Protocol):
    def update(
        self,
        detections: list[TrackingDetection],
        frame: np.ndarray | None = None,
    ) -> list[TrackedObject]:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    def status(self) -> TrackingStatus:
        raise NotImplementedError
