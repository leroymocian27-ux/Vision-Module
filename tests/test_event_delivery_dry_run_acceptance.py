from __future__ import annotations

import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery_worker import DeliveryWorker
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


class EventDeliveryDryRunAcceptanceTest(unittest.TestCase):
    def test_dry_run_sqlite_event_to_delivery_api_acceptance(self) -> None:
        defaults = Settings()
        self.assertFalse(defaults.event_delivery_enabled)
        self.assertFalse(defaults.event_delivery_worker_enabled)
        self.assertEqual(defaults.event_delivery_backend, "memory")

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "event_delivery_outbox.sqlite3"
            settings = replace(
                defaults,
                event_pipeline_enabled=True,
                event_ring_buffer_enabled=True,
                event_worker_enabled=True,
                event_semantic_enabled=True,
                event_delivery_enabled=True,
                event_delivery_mode="dry_run",
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=str(db_path),
                event_delivery_worker_enabled=True,
                event_delivery_target_url="http://not-used.invalid/video-bridge/fall-events",
                main_system_alert_enabled=False,
            )
            pipeline = EventPipelineService(settings)
            delivery_worker = DeliveryWorker(settings, pipeline.delivery_outbox)
            self._add_trigger_frames(pipeline)
            post_calls: list[dict] = []

            def fake_post(*args, **kwargs):
                post_calls.append({"args": args, "kwargs": kwargs})
                raise AssertionError("dry-run must never call requests.post")

            previous_post = delivery_module.requests.post
            delivery_module.requests.post = fake_post
            try:
                delivery_worker.start()
                self.assertTrue(delivery_worker.status()["running"])
                observed = pipeline.observe_result(self._result())
                processed = pipeline.process_once("dry-run-acceptance-event-worker")
                self.assertIsNotNone(processed)
                self.assertEqual(len(observed), 1)
                self.assertIsNotNone(processed.trusted_result)
                self.assertIsNotNone(processed.evidence_package)
                self.assertIsNotNone(processed.event_semantics)

                incident_id = processed.incident_id
                first = pipeline.delivery_outbox.for_incident(incident_id)
                self.assertIsNotNone(first)
                self.assertEqual(first.delivery_status, "dry_run_sent")
                self.assertTrue(first.dry_run)
                self.assertEqual(first.delivery_mode, "dry_run")
                self.assertEqual(first.attempt_count, 0)
                self.assertEqual(
                    pipeline.delivery_outbox.enqueue(
                        processed.trusted_result,
                        processed.evidence_package,
                        processed.event_semantics,
                    ).delivery_id,
                    first.delivery_id,
                )
                self.assertEqual(len(pipeline.delivery_outbox.list_deliveries()), 1)
                self.assertTrue({
                    "incident_id", "camera_id", "event_type", "state", "status",
                    "severity", "risk", "risk_level", "fall_detected", "timestamp",
                    "injury", "recommended_action",
                }.issubset(first.payload_json))

                runtime = SimpleNamespace(
                    settings=settings,
                    event_pipeline=pipeline,
                    event_delivery_worker=delivery_worker,
                )
                self._assert_delivery_api(runtime, first.delivery_id, incident_id)
            finally:
                delivery_worker.stop()
                delivery_module.requests.post = previous_post

            reopened_pipeline = EventPipelineService(settings)
            persisted = reopened_pipeline.delivery_outbox.for_incident(incident_id)
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted.delivery_id, first.delivery_id)
            self.assertEqual(persisted.delivery_status, "dry_run_sent")
            self._assert_delivery_api(
                SimpleNamespace(settings=settings, event_pipeline=reopened_pipeline, event_delivery_worker=None),
                first.delivery_id,
                incident_id,
            )
            self.assertEqual(post_calls, [])

    @staticmethod
    def _assert_delivery_api(runtime, delivery_id: str, incident_id: str) -> None:
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(event_api.router)
        with TestClient(app) as client:
            status = client.get("/events/delivery/status")
            outbox = client.get("/events/delivery/outbox?camera_id=camera_01")
            detail = client.get(f"/events/delivery/{delivery_id}")
            by_incident = client.get(f"/events/delivery/by-incident/{incident_id}")

        for response in (status, outbox, detail, by_incident):
            if response.status_code != 200:
                raise AssertionError(f"delivery API failed: {response.status_code} {response.text}")
        assert status.json()["event_delivery_enabled"] is True
        assert status.json()["delivery_mode"] == "dry_run"
        assert status.json()["delivery_backend"] == "sqlite"
        assert outbox.json()["items"][0]["delivery_id"] == delivery_id
        assert detail.json()["delivery_status"] == "dry_run_sent"
        assert by_incident.json()["incident_id"] == incident_id

    @staticmethod
    def _add_trigger_frames(pipeline: EventPipelineService) -> None:
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        trigger = datetime(2026, 7, 18, 9, 45, tzinfo=timezone.utc)
        for offset_ms in (-3000, -1000, 0, 1000, 3000, 5000):
            pipeline.ring_buffer.add_frame(
                "camera_01",
                500 + int(offset_ms / 1000),
                (trigger + timedelta(milliseconds=offset_ms)).isoformat(),
                image,
            )

    @staticmethod
    def _result() -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-18T09:45:00+00:00",
            frame_seq=500,
            frame_width=640,
            frame_height=360,
            objects=[DetectedObject(
                label="person",
                confidence=0.96,
                bbox=[100.0, 120.0, 310.0, 340.0],
                track_id=73,
                fall_decision={
                    "fall_state": "fallen_confirmed",
                    "risk_level": "critical",
                    "fall_probability": 0.93,
                    "fall_evidence_score": 0.95,
                    "adl_suppression_score": 0.05,
                },
                features={
                    "motion": {"tracking_stable": True, "rapid_descent": True},
                    "fall_state_sequence": ["standing", "falling", "fallen_confirmed"],
                },
                temporal={"fall_probability": 0.93, "post_event_stillness_ms": 3000},
            )],
        )


if __name__ == "__main__":
    unittest.main()
