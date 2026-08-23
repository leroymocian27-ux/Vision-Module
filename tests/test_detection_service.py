from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.detection_service import DetectionService


class _SourceManagerStub:
    @staticmethod
    def get_buffer(camera_id: str):
        del camera_id
        return None


class _DetectorStub:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls = 0

    def detect(self, frame):
        del frame
        self.calls += 1
        return [DetectedObject(label=self.label, confidence=0.9, bbox=[10.0, 20.0, 80.0, 160.0])]

    @staticmethod
    def status():
        return SimpleNamespace(enabled=True, loaded=True, model_name="stub", last_error=None)


class _ObservingFallDetector(_DetectorStub):
    def __init__(self, store: RealtimeResultStore) -> None:
        super().__init__("fall")
        self.store = store
        self.latest_detection_seen_during_fall = None

    def detect(self, frame):
        self.latest_detection_seen_during_fall = self.store.latest_detection("camera_01")
        return super().detect(frame)


class DetectionServiceTest(unittest.TestCase):
    def test_fall_hint_detector_is_rate_limited_separately(self) -> None:
        settings = replace(Settings(), fall_detector_interval_ms=10_000)
        store = RealtimeResultStore()
        person_detector = _DetectorStub("person")
        fall_detector = _DetectorStub("fall")
        with patch("app.services.detection_service.YoloPersonDetector", return_value=person_detector), patch(
            "app.services.detection_service.YoloFallDetector",
            return_value=fall_detector,
        ):
            service = DetectionService(settings, _SourceManagerStub(), store)

        packet = SimpleNamespace(
            camera_id="camera_01",
            seq=1,
            width=640,
            height=360,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
        )
        service._detect_packet(None, packet)  # type: ignore[arg-type]
        packet.seq = 2
        service._detect_packet(None, packet)  # type: ignore[arg-type]

        self.assertEqual(person_detector.calls, 2)
        self.assertEqual(fall_detector.calls, 1)
        status = service.status("camera_01")
        self.assertEqual(status.latest_fall_model_count, 1)
        self.assertIsNotNone(status.fall_inference_latency_ms)
        self.assertGreaterEqual(status.fall_hint_fps, 0.0)

    def test_person_detection_is_published_before_fall_hint_runs(self) -> None:
        settings = replace(Settings(), fall_detector_interval_ms=1)
        store = RealtimeResultStore()
        person_detector = _DetectorStub("person")
        fall_detector = _ObservingFallDetector(store)
        with patch("app.services.detection_service.YoloPersonDetector", return_value=person_detector), patch(
            "app.services.detection_service.YoloFallDetector",
            return_value=fall_detector,
        ):
            service = DetectionService(settings, _SourceManagerStub(), store)

        packet = SimpleNamespace(
            camera_id="camera_01",
            seq=7,
            width=640,
            height=360,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
        )

        service._detect_packet(None, packet)  # type: ignore[arg-type]

        self.assertIsNotNone(fall_detector.latest_detection_seen_during_fall)
        assert fall_detector.latest_detection_seen_during_fall is not None
        self.assertEqual(fall_detector.latest_detection_seen_during_fall.frame_seq, 7)
        self.assertEqual(fall_detector.latest_detection_seen_during_fall.objects[0].label, "person")

    def test_async_v1_detection_service_does_not_call_fall_hint(self) -> None:
        settings = replace(
            Settings(),
            pipeline_mode="async_v1",
            fall_hint_in_detection_service=False,
            fall_hint_worker_enabled=True,
        )
        store = RealtimeResultStore()
        person_detector = _DetectorStub("person")
        fall_detector = _DetectorStub("fall")
        with patch("app.services.detection_service.YoloPersonDetector", return_value=person_detector), patch(
            "app.services.detection_service.YoloFallDetector",
            return_value=fall_detector,
        ):
            service = DetectionService(settings, _SourceManagerStub(), store)

        packet = SimpleNamespace(
            camera_id="camera_01",
            seq=11,
            width=640,
            height=360,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
        )

        service._detect_packet(None, packet)  # type: ignore[arg-type]

        self.assertEqual(person_detector.calls, 1)
        self.assertEqual(fall_detector.calls, 0)
        self.assertIsNotNone(store.latest_detection("camera_01"))
        self.assertIsNone(store.latest_fall_detection("camera_01"))


if __name__ == "__main__":
    unittest.main()
