from __future__ import annotations

import time
import unittest
from dataclasses import replace

import numpy as np

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.result_publisher_service import ResultPublisherService


class _Channels:
    def publish(self, result: VisionResult) -> None:
        del result


class FusedResultFallbackTest(unittest.TestCase):
    def _publisher(self, *, fusion_enabled: bool) -> tuple[ResultPublisherService, RealtimeResultStore]:
        store = RealtimeResultStore()
        store.update_detection(DetectionSnapshot(
            camera_id="camera_01", frame_seq=9, frame_width=640, frame_height=360,
            timestamp="2026-07-17T09:30:00+00:00", monotonic_at=time.monotonic(),
            frame=np.zeros((2, 2, 3), dtype=np.uint8),
            objects=[DetectedObject(label="person", confidence=0.9, bbox=[1, 1, 10, 10], track_id=1)],
        ))
        return ResultPublisherService(replace(Settings(), fusion_worker_enabled=fusion_enabled), store, _Channels()), store

    def test_empty_fusion_slot_falls_back_to_snapshot(self) -> None:
        publisher, _ = self._publisher(fusion_enabled=True)
        result = publisher._build_result("camera_01")
        self.assertIsNotNone(result)
        self.assertEqual(result.detector["result_source"], "snapshot_fallback")

    def test_fresh_fusion_slot_is_preferred(self) -> None:
        publisher, store = self._publisher(fusion_enabled=True)
        store.update_fused(VisionResult(camera_id="camera_01", timestamp="2026-07-17T09:30:00+00:00", frame_seq=10, frame_width=640, frame_height=360, detector={"_monotonic_at": time.monotonic(), "marker": "fused"}))
        result = publisher._build_result("camera_01")
        self.assertEqual(result.detector["result_source"], "fusion_slot")
        self.assertEqual(result.detector["marker"], "fused")

    def test_disabled_fusion_keeps_snapshot_path(self) -> None:
        publisher, _ = self._publisher(fusion_enabled=False)
        result = publisher._build_result("camera_01")
        self.assertEqual(result.detector["result_source"], "snapshot")
