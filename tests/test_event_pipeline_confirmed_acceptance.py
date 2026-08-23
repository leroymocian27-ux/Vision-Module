from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


class EventPipelineConfirmedAcceptanceTest(unittest.TestCase):
    def test_synthetic_confirmed_event_reaches_event_api_with_no_delivery_or_vlm(self) -> None:
        with TemporaryDirectory() as directory:
            settings = replace(
                Settings(), event_pipeline_enabled=True, event_ring_buffer_enabled=True,
                event_worker_enabled=True, event_semantic_enabled=True,
                event_archive_enabled=True, event_archive_dir=directory,
                event_keyframe_serving_enabled=False, event_delivery_enabled=False,
                event_vlm_enabled=False, main_system_alert_enabled=False,
            )
            pipeline = EventPipelineService(settings)
            trigger = datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc)
            image = np.zeros((4, 4, 3), dtype=np.uint8)
            for offset in (-3000, -1000, 0):
                pipeline.ring_buffer.add_frame("camera_01", 600 + offset // 1000, (trigger + timedelta(milliseconds=offset)).isoformat(), image)
            result = VisionResult(camera_id="camera_01", timestamp=trigger.isoformat(), frame_seq=600, frame_width=640, frame_height=360, objects=[DetectedObject(
                label="person", confidence=0.96, bbox=[100, 100, 300, 340], track_id=88,
                fall_decision={"fall_state": "fallen_confirmed", "risk_level": "critical", "fall_probability": 0.96, "fall_evidence_score": 0.95},
            )])
            incident_id = pipeline.observe_result(result)[0].incident_id
            processed = pipeline.process_once("confirmed-acceptance")

            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)
            with TestClient(app) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                detail = client.get(f"/events/{incident_id}")

            self.assertEqual(processed.event.fall_state, "fallen_confirmed")
            self.assertEqual(processed.trusted_result.final_event_type, "fallen_confirmed")
            self.assertTrue(processed.trusted_result.support_fall_alarm)
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(detail.status_code, 200)
            payload = detail.json()
            self.assertEqual(payload["event"]["fall_state"], "fallen_confirmed")
            self.assertIsNotNone(payload["evidence_package"])
            self.assertIsNotNone(payload["event_semantics"])
            self.assertIsNotNone(payload["trusted_result"])
            self.assertTrue(payload["archive_summary"])
            self.assertIsNone(payload["delivery"])
            self.assertTrue(all(item["keyframe_url"] is None for item in payload["evidence_package"]["keyframes"]))
