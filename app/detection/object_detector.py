from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from app.ai.inference_guard import ultralytics_inference_lock
from app.core.config import Settings
from app.core.logger import get_logger
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


@dataclass
class DetectorStatus:
    enabled: bool
    loaded: bool = False
    model_name: str | None = None
    last_error: str | None = None


class PersonDetector:
    def detect(self, frame: np.ndarray) -> list[DetectedObject]:
        raise NotImplementedError

    def status(self) -> DetectorStatus:
        raise NotImplementedError


class YoloPersonDetector(PersonDetector):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._status = DetectorStatus(
            enabled=settings.detection_enabled,
            loaded=False,
            model_name=settings.yolo_model_path,
        )
        if settings.detection_enabled:
            self._load()

    def _load(self) -> None:
        try:
            from ultralytics import YOLO

            self._model = YOLO(self.settings.yolo_model_path)
            self._status.loaded = True
            self._status.last_error = None
            logger.info("yolo_loaded model=%s", self.settings.yolo_model_path)
        except Exception as exc:
            self._model = None
            self._status.loaded = False
            self._status.last_error = str(exc)
            logger.error("yolo_load_failed error=%s", exc)

    def detect(self, frame: np.ndarray) -> list[DetectedObject]:
        if not self._status.enabled or not self._model:
            return []

        kwargs = {
            "conf": self.settings.yolo_confidence,
            "imgsz": self.settings.yolo_imgsz,
            "verbose": False,
            "classes": [0],
        }
        if self.settings.yolo_device:
            kwargs["device"] = self.settings.yolo_device

        with ultralytics_inference_lock(blocking=True, owner="person_detector") as acquired:
            if not acquired:
                return []
            results = self._model.predict(frame, **kwargs)
        if not results:
            return []

        detections: list[DetectedObject] = []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return detections

        for box in boxes:
            xyxy = box.xyxy[0].tolist()
            confidence = float(box.conf[0].item())
            detections.append(
                DetectedObject(
                    label="person",
                    confidence=round(confidence, 4),
                    bbox=[round(float(v), 2) for v in xyxy],
                )
            )
        return detections

    def status(self) -> DetectorStatus:
        return DetectorStatus(**self._status.__dict__)


class NoopPersonDetector(PersonDetector):
    def __init__(self, message: str = "detection disabled") -> None:
        self._status = DetectorStatus(
            enabled=False,
            loaded=False,
            model_name=None,
            last_error=message,
        )

    def detect(self, frame: np.ndarray) -> list[DetectedObject]:
        return []

    def status(self) -> DetectorStatus:
        return DetectorStatus(**self._status.__dict__)


@dataclass
class DetectionRunStats:
    inference_latency_ms: float | None = None
    fall_inference_latency_ms: float | None = None
    last_error: str | None = None
    last_detected_at: float | None = None
    last_fall_detected_at: float | None = None
    latest_raw_person_count: int = 0
    latest_fall_model_count: int = 0
    latest_person_boxes: list[list[float]] | None = None
    latest_person_confidences: list[float] | None = None
    latest_fall_labels: list[str] | None = None
    latest_fall_confidences: list[float] | None = None
    latest_fall_boxes: list[list[float]] | None = None
