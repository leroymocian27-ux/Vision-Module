from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


class EventPipelineEndToEndSmokeTest(unittest.TestCase):
    def _result(self) -> VisionResult:
        return VisionResult(
            camera_id="camera_01", timestamp="2026-07-17T09:30:00+00:00", frame_seq=10,
            frame_width=640, frame_height=360,
            objects=[DetectedObject(label="person", confidence=0.92, bbox=[1, 2, 30, 80], track_id=1,
                fall_decision={"fall_state": "fallen_confirmed", "risk_level": "critical", "fall_probability": 0.9},
                features={"motion": {"rapid_descent": True}}, temporal={"fall_probability": 0.9})],
        )

    def test_disabled_pipeline_has_no_side_effect(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=False))
        self.assertEqual(pipeline.observe_result(self._result()), [])
        self.assertEqual(pipeline.outbox.records(), [])

    def test_enabled_pipeline_persists_pending_before_worker(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=False))
        records = pipeline.observe_result(self._result())
        self.assertEqual(records[0].status, "pending")
        self.assertEqual(pipeline.outbox.get_event(records[0].incident_id).status, "pending")

    def test_processing_degrades_for_missing_frames_but_produces_rule_result(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=True, event_semantic_enabled=True))
        incident = pipeline.observe_result(self._result())[0].incident_id
        processed = pipeline.process_once("smoke-worker")
        self.assertEqual(processed.status, "delivery_pending")
        self.assertTrue(processed.evidence_package.degradation_used)
        self.assertIsNotNone(processed.trusted_result)
        self.assertEqual(processed.trusted_result.final_event_type, "fallen_confirmed")
        self.assertEqual(processed.incident_id, incident)
