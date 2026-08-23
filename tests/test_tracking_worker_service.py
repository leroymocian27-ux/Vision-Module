from __future__ import annotations

import unittest
from dataclasses import replace
import time

import numpy as np

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService


class TrackingWorkerServiceTest(unittest.TestCase):
    def test_fall_only_without_person_is_not_promoted(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_promote_unmatched=True,
            fall_detector_promote_min_confidence=0.12,
        )
        worker = TrackingWorkerService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            tracking_service=TrackingService(settings),
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[],
            detector={"name": "person"},
        )
        fall_detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="fall",
                    confidence=0.4,
                    bbox=[100.0, 50.0, 320.0, 260.0],
                )
            ],
            detector={"name": "fall"},
        )

        merged = worker._with_fall_promoted_objects(detection, fall_detection)  # type: ignore[attr-defined]

        self.assertEqual(merged.objects, [])
        self.assertEqual(merged.detector["fall_promoted_rejected_reason"], "fall_only_without_person")
        self.assertEqual(merged.detector["fall_promoted_rejected_count"], 1)

    def test_adl_fall_hint_label_is_not_promoted_without_person(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_promote_unmatched=True,
            fall_detector_promote_min_confidence=0.12,
        )
        worker = TrackingWorkerService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            tracking_service=TrackingService(settings),
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[],
            detector={"name": "person"},
        )
        fall_detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="kneeling",
                    confidence=0.9,
                    bbox=[100.0, 50.0, 320.0, 260.0],
                )
            ],
            detector={"name": "fall"},
        )

        merged = worker._with_fall_promoted_objects(detection, fall_detection)  # type: ignore[attr-defined]

        self.assertIs(merged, detection)
        self.assertEqual(merged.objects, [])

    def test_adl_fall_hint_label_is_not_promoted_as_extra_person(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_promote_unmatched=True,
            fall_detector_promote_min_confidence=0.12,
        )
        worker = TrackingWorkerService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            tracking_service=TrackingService(settings),
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[20.0, 50.0, 120.0, 260.0],
                )
            ],
            detector={"name": "person"},
        )
        fall_detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="sitting",
                    confidence=0.9,
                    bbox=[300.0, 80.0, 520.0, 280.0],
                )
            ],
            detector={"name": "fall"},
        )

        merged = worker._with_fall_promoted_objects(detection, fall_detection)  # type: ignore[attr-defined]

        self.assertIs(merged, detection)
        self.assertEqual(len(merged.objects), 1)
        self.assertEqual(merged.objects[0].label, "person")

    def test_strong_fall_hint_label_can_be_promoted_as_extra_person(self) -> None:
        settings = replace(
            Settings(),
            fall_detector_promote_unmatched=True,
            fall_detector_promote_min_confidence=0.12,
        )
        worker = TrackingWorkerService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            tracking_service=TrackingService(settings),
        )
        detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[20.0, 50.0, 120.0, 260.0],
                )
            ],
            detector={"name": "person"},
        )
        fall_detection = DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=0.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="falling",
                    confidence=0.9,
                    bbox=[300.0, 80.0, 520.0, 280.0],
                )
            ],
            detector={"name": "fall"},
        )

        merged = worker._with_fall_promoted_objects(detection, fall_detection)  # type: ignore[attr-defined]

        self.assertIsNot(merged, detection)
        self.assertEqual(len(merged.objects), 2)
        self.assertEqual(merged.objects[1].label, "person")
        self.assertEqual(merged.objects[1].fall_decision["detector_label"], "falling")

    def test_prediction_uses_last_corrected_snapshot_not_previous_prediction(self) -> None:
        settings = replace(Settings(), target_lost_after_ms=1000)
        worker = TrackingWorkerService(
            settings=settings,
            realtime_store=RealtimeResultStore(),
            tracking_service=TrackingService(settings),
        )
        now = time.monotonic()
        previous = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=1,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=now - 0.2,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[100.0, 100.0, 200.0, 300.0],
                    track_id=1,
                )
            ],
        )
        corrected = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=2,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=now - 0.1,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[110.0, 100.0, 210.0, 300.0],
                    track_id=1,
                )
            ],
        )
        worker._previous_corrected_tracking_snapshot["camera_01"] = previous  # type: ignore[attr-defined]
        worker._last_corrected_tracking_snapshot["camera_01"] = corrected  # type: ignore[attr-defined]

        first = worker._hold_or_predict("camera_01")  # type: ignore[attr-defined]
        self.assertIsNotNone(first)
        assert first is not None
        worker._last_emitted_tracking_snapshot["camera_01"] = ObjectSnapshot(  # type: ignore[attr-defined]
            camera_id="camera_01",
            frame_seq=2,
            frame_width=640,
            frame_height=360,
            timestamp="2026-06-18T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=first,
        )
        second = worker._hold_or_predict("camera_01")  # type: ignore[attr-defined]
        self.assertIsNotNone(second)
        assert second is not None

        self.assertLess(second[0].bbox[0], first[0].bbox[0] + 25.0)
        self.assertEqual(second[0].fusion_debug["tracking_source"], "predicted")


if __name__ == "__main__":
    unittest.main()
