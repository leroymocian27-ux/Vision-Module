from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from app.core.config import Settings
from app.detection.object_detector import DetectionRunStats
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.detection_service import DetectionService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.temporal_worker_service import TemporalWorkerService


class _SourceManagerStub:
    def get_buffer(self, camera_id: str):
        del camera_id
        return None


class _RaisingDetector:
    def detect(self, frame):
        del frame
        raise RuntimeError("detector boom")

    @staticmethod
    def status():
        return SimpleNamespace(enabled=True, loaded=True, model_name="raising", last_error=None)


class _RaisingTemporal:
    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        del camera_id, objects
        raise RuntimeError("temporal boom")


class _RaisingResultBuilder:
    def build_result_snapshot(self, camera_id: str):
        del camera_id
        raise RuntimeError("fusion boom")


def _person() -> DetectedObject:
    return DetectedObject(
        label="person",
        confidence=0.9,
        bbox=[10.0, 20.0, 120.0, 220.0],
        track_id=1,
        is_target=True,
    )


def test_detection_exception_is_recorded_without_escaping_worker_tick():
    settings = replace(
        Settings(),
        pipeline_mode="fall_disabled",
        fall_detector_enabled=False,
        fall_hint_in_detection_service=False,
        fall_hint_worker_enabled=False,
    )
    store = RealtimeResultStore()
    with patch("app.services.detection_service.YoloPersonDetector", return_value=_RaisingDetector()):
        service = DetectionService(settings, _SourceManagerStub(), store)

    packet = SimpleNamespace(
        camera_id="camera_01",
        seq=3,
        width=640,
        height=360,
        frame=np.zeros((360, 640, 3), dtype=np.uint8),
    )

    service._detect_packet(None, packet)  # type: ignore[arg-type]

    status = service.status("camera_01")
    assert status.last_error == "detector boom"
    assert store.latest_detection("camera_01") is None


def test_temporal_worker_exception_is_counted_without_escaping_tick():
    settings = replace(Settings(), enable_temporal=True, temporal_worker_enabled=True)
    store = RealtimeResultStore()
    worker = TemporalWorkerService(settings, store, _RaisingTemporal())  # type: ignore[arg-type]
    store.update_tracking(
        ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=8,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-20T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[_person()],
        )
    )

    worker._tick("camera_01")  # type: ignore[attr-defined]

    status = worker.status("camera_01")
    assert status.error_count == 1
    assert status.last_error == "temporal boom"
    assert store.latest_temporal("camera_01") is None


def test_fusion_worker_exception_is_counted_without_escaping_tick():
    settings = replace(Settings(), fusion_worker_enabled=True)
    store = RealtimeResultStore()
    worker = FusionWorkerService(settings, store, _RaisingResultBuilder())  # type: ignore[arg-type]

    worker._tick("camera_01")  # type: ignore[attr-defined]

    status = worker.status("camera_01")
    assert status.error_count == 1
    assert status.last_error == "fusion boom"
    assert store.latest_fused("camera_01") is None
