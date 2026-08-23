from __future__ import annotations

import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.camera.frame_buffer import FrameBuffer, FramePacket
from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.detection.yolo_fall_detector import FallDetectorLockBusy
from app.schemas.vision_result import DetectedObject
from app.services.fall_hint_worker_service import FallHintWorkerService


class _SourceManagerStub:
    def __init__(self, buffer: FrameBuffer) -> None:
        self.buffer = buffer

    def get_buffer(self, camera_id: str):
        del camera_id
        return self.buffer


class _FallDetectorStub:
    def __init__(self, *, objects=None, error: Exception | None = None) -> None:
        self.objects = list(objects or [])
        self.error = error
        self.calls = 0

    def detect(self, frame, **kwargs):
        del frame, kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.objects)

    @staticmethod
    def status():
        return SimpleNamespace(enabled=True, loaded=True, model_name="fall-stub", last_error=None)


def _settings() -> Settings:
    return replace(
        Settings(),
        pipeline_mode="async_v1",
        fall_hint_in_detection_service=False,
        fall_hint_worker_enabled=True,
        fall_hint_max_frame_age_ms=800,
    )


class FallHintWorkerServiceTest(unittest.TestCase):
    def test_successful_empty_result_writes_fresh_snapshot(self) -> None:
        buffer = FrameBuffer("camera_01")
        buffer.update(np.zeros((240, 320, 3), dtype=np.uint8))
        store = RealtimeResultStore()
        detector = _FallDetectorStub(objects=[])
        with patch("app.services.fall_hint_worker_service.YoloFallDetector", return_value=detector):
            service = FallHintWorkerService(_settings(), _SourceManagerStub(buffer), store)

        service._tick("camera_01", 0)

        snapshot = store.latest_fall_detection("camera_01")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.objects, [])
        self.assertEqual(snapshot.detector["source_worker"], "FallHintWorkerService")
        self.assertEqual(detector.calls, 1)

    def test_duplicate_frame_is_skipped(self) -> None:
        buffer = FrameBuffer("camera_01")
        packet = buffer.update(np.zeros((240, 320, 3), dtype=np.uint8))
        store = RealtimeResultStore()
        detector = _FallDetectorStub()
        with patch("app.services.fall_hint_worker_service.YoloFallDetector", return_value=detector):
            service = FallHintWorkerService(_settings(), _SourceManagerStub(buffer), store)

        last_seq = service._tick("camera_01", 0)
        service._tick("camera_01", last_seq)

        self.assertEqual(last_seq, packet.seq)
        self.assertEqual(detector.calls, 1)
        self.assertEqual(service.status("camera_01").skipped_duplicate_frame_count, 1)

    def test_lock_busy_is_skipped_without_writing_snapshot(self) -> None:
        buffer = FrameBuffer("camera_01")
        buffer.update(np.zeros((240, 320, 3), dtype=np.uint8))
        store = RealtimeResultStore()
        detector = _FallDetectorStub(error=FallDetectorLockBusy("busy"))
        with patch("app.services.fall_hint_worker_service.YoloFallDetector", return_value=detector):
            service = FallHintWorkerService(_settings(), _SourceManagerStub(buffer), store)

        service._tick("camera_01", 0)

        self.assertIsNone(store.latest_fall_detection("camera_01"))
        self.assertEqual(service.status("camera_01").skipped_lock_busy_count, 1)

    def test_error_does_not_clear_previous_snapshot(self) -> None:
        buffer = FrameBuffer("camera_01")
        buffer.update(np.zeros((240, 320, 3), dtype=np.uint8))
        store = RealtimeResultStore()
        first_detector = _FallDetectorStub(
            objects=[DetectedObject(label="fall", confidence=0.9, bbox=[1, 2, 3, 4])]
        )
        with patch("app.services.fall_hint_worker_service.YoloFallDetector", return_value=first_detector):
            service = FallHintWorkerService(_settings(), _SourceManagerStub(buffer), store)
        last_seq = service._tick("camera_01", 0)
        previous = store.latest_fall_detection("camera_01")
        self.assertIsNotNone(previous)

        buffer.update(np.zeros((240, 320, 3), dtype=np.uint8))
        service.detector = _FallDetectorStub(error=RuntimeError("boom"))
        service._tick("camera_01", last_seq)

        self.assertIs(store.latest_fall_detection("camera_01"), previous)
        self.assertEqual(service.status("camera_01").error_count, 1)

    def test_stale_frame_is_skipped(self) -> None:
        settings = replace(_settings(), fall_hint_max_frame_age_ms=1)
        buffer = FrameBuffer("camera_01")
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        with buffer._lock:  # type: ignore[attr-defined]
            buffer._seq = 1  # type: ignore[attr-defined]
            buffer._packet = FramePacket(  # type: ignore[attr-defined]
                camera_id="camera_01",
                seq=1,
                captured_at=time.monotonic() - 1.0,
                frame=frame,
            )
        store = RealtimeResultStore()
        detector = _FallDetectorStub()
        with patch("app.services.fall_hint_worker_service.YoloFallDetector", return_value=detector):
            service = FallHintWorkerService(settings, _SourceManagerStub(buffer), store)

        service._tick("camera_01", 0)

        self.assertEqual(detector.calls, 0)
        self.assertEqual(service.status("camera_01").skipped_stale_frame_count, 1)


if __name__ == "__main__":
    unittest.main()
