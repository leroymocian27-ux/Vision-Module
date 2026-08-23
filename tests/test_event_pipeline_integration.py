from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np

from app.core.config import Settings
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


class EventPipelineIntegrationTest(unittest.TestCase):
    def _result(self) -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-17T09:30:00+00:00",
            frame_seq=42,
            frame_width=640,
            frame_height=360,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.91,
                    bbox=[100.0, 120.0, 300.0, 340.0],
                    track_id=3,
                    fall_decision={
                        "fall_state": "fallen_candidate",
                        "risk_level": "high",
                        "fall_probability": 0.82,
                        "fall_evidence_score": 0.85,
                        "adl_suppression_score": 0.1,
                    },
                    features={"motion": {"tracking_stable": True, "rapid_descent": True}},
                    temporal={"fall_probability": 0.82, "post_event_stillness_ms": 3000},
                )
            ],
        )

    def test_disabled_by_default_does_not_write_events(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=False))

        records = pipeline.observe_result(self._result())

        self.assertEqual(records, [])
        self.assertEqual(pipeline.outbox.records(), [])

    def test_enabled_pipeline_builds_rule_based_event_result(self) -> None:
        settings = replace(
            Settings(),
            event_pipeline_enabled=True,
            event_ring_buffer_enabled=True,
            event_semantic_enabled=True,
            event_worker_enabled=False,
        )
        pipeline = EventPipelineService(settings)
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        trigger = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        for offset, sequence in [(-3000, 39), (-1000, 41), (0, 42), (1000, 43), (3000, 45), (5000, 47)]:
            timestamp = (trigger + timedelta(milliseconds=offset)).isoformat()
            pipeline.ring_buffer.add_frame("camera_01", sequence, timestamp, image)

        first = pipeline.observe_result(self._result())
        second = pipeline.observe_result(self._result())
        processed = pipeline.process_once("test-worker")

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].incident_id, second[0].incident_id)
        self.assertIsNotNone(processed)
        self.assertEqual(processed.status, "delivery_pending")
        self.assertIsNotNone(processed.evidence_package)
        self.assertIsNotNone(processed.event_semantics)
        self.assertIsNotNone(processed.trusted_result)
        self.assertTrue(processed.trusted_result.support_fall_alarm)
