from __future__ import annotations

from typing import Protocol

import numpy as np

from app.pose.schemas import PoseResult
from app.schemas.vision_result import DetectedObject


class PoseEstimator(Protocol):
    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        raise NotImplementedError
