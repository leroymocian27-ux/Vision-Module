from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.core.config import Settings
from app.detection.yolo_fall_detector import YoloFallDetector


class _FakeTensor:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value

    def tolist(self):
        return self.value


class _FakeBox:
    def __init__(self, cls_id: int, bbox: list[float], confidence: float = 0.9) -> None:
        self.cls = [_FakeTensor(cls_id)]
        self.conf = [_FakeTensor(confidence)]
        self.xyxy = [_FakeTensor(bbox)]


class _FakeModel:
    def __init__(self, labels: list[str]) -> None:
        self.labels = labels

    def predict(self, frame, **kwargs):
        del frame, kwargs
        return [
            SimpleNamespace(
                names={index: label for index, label in enumerate(self.labels)},
                boxes=[_FakeBox(index, [10.0, 20.0, 80.0, 160.0]) for index in range(len(self.labels))],
            )
        ]


class YoloFallDetectorTest(unittest.TestCase):
    def test_new_fall_hint_labels_are_not_filtered(self) -> None:
        labels = ["falling", "fallen", "lying", "sitting", "bending", "kneeling", "standing"]
        settings = replace(Settings(), yolo_fall_model_path="dummy.pt")

        with patch("ultralytics.YOLO", return_value=_FakeModel(labels)):
            detector = YoloFallDetector(settings)

        objects = detector.detect(np.zeros((100, 100, 3), dtype=np.uint8))

        self.assertEqual([item.label for item in objects], labels)


if __name__ == "__main__":
    unittest.main()
