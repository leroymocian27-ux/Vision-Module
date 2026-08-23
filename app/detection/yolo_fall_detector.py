from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.ai.inference_guard import ultralytics_inference_lock
from app.core.config import Settings
from app.core.logger import get_logger
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)

FALL_HINT_LABELS = {
    "fall",
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
}


@dataclass
class FallDetectorStatus:
    enabled: bool
    loaded: bool = False
    model_name: str | None = None
    last_error: str | None = None


class FallDetectorLockBusy(RuntimeError):
    pass


class YoloFallDetector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._status = FallDetectorStatus(
            enabled=settings.fall_detector_enabled,
            loaded=False,
            model_name=settings.yolo_fall_model_path,
        )
        if settings.fall_detector_enabled:
            self._load()

    def _load(self) -> None:
        try:
            from ultralytics import YOLO

            self._model = YOLO(self.settings.yolo_fall_model_path)
            self._status.loaded = True
            self._status.last_error = None
            logger.info("yolo_fall_loaded model=%s", self.settings.yolo_fall_model_path)
        except Exception as exc:
            self._model = None
            self._status.loaded = False
            self._status.last_error = str(exc)
            logger.error("yolo_fall_load_failed error=%s", exc)

    def detect(
        self,
        frame: np.ndarray,
        *,
        lock_timeout_ms: int | None = None,
        skip_if_busy: bool = False,
    ) -> list[DetectedObject]:
        if not self._status.enabled or not self._model:
            return []

        kwargs = {
            "conf": self.settings.yolo_fall_confidence,
            "imgsz": self.settings.yolo_fall_imgsz,
            "verbose": False,
        }
        if self.settings.yolo_fall_device:
            kwargs["device"] = self.settings.yolo_fall_device

        timeout = None if lock_timeout_ms is None else max(0.0, lock_timeout_ms / 1000)
        with ultralytics_inference_lock(
            blocking=True,
            owner="fall_detector",
            timeout=timeout,
        ) as acquired:
            if not acquired:
                if skip_if_busy:
                    raise FallDetectorLockBusy("fall_detector_lock_busy")
                return []
            results = self._model.predict(frame, **kwargs)
        if not results:
            return []

        detections: list[DetectedObject] = []
        result = results[0]
        boxes = getattr(result, "boxes", None)
        names = getattr(result, "names", {}) or {}
        if boxes is None:
            return detections

        for box in boxes:
            cls_id = int(box.cls[0].item()) if box.cls is not None else -1
            label = str(names.get(cls_id, cls_id)).lower()
            if label not in FALL_HINT_LABELS:
                continue
            xyxy = box.xyxy[0].tolist()
            confidence = float(box.conf[0].item())
            detections.append(
                DetectedObject(
                    label=label,
                    confidence=round(confidence, 4),
                    bbox=[round(float(v), 2) for v in xyxy],
                )
            )
        return detections

    def status(self) -> FallDetectorStatus:
        return FallDetectorStatus(**self._status.__dict__)
