from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


class EventDeliveryFinalE2ERunbookTest(unittest.TestCase):
    def test_delivery_final_e2e_dry_run_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[dict] = []
            pipeline = EventPipelineService(self._settings(temp_dir, event_delivery_mode="dry_run"))

            def fake_post(*args, **kwargs):
                calls.append({"args": args, "kwargs": kwargs})
                raise AssertionError("dry-run must not call POST")

            previous = delivery_module.requests.post
            delivery_module.requests.post = fake_post
            try:
                incident_id = pipeline.observe_result(self._result("final-dry-run", "fallen_confirmed"))[0].incident_id
                processed = pipeline.process_once("final-e2e-dry-run")
            finally:
                delivery_module.requests.post = previous

            delivery = pipeline.delivery_outbox.for_incident(incident_id)
            reopened = EventPipelineService(self._settings(temp_dir, event_delivery_mode="dry_run"))
            restored = reopened.delivery_outbox.for_incident(incident_id)

            self.assertEqual(calls, [])
            self.assertIsNotNone(processed)
            self.assertIsNotNone(delivery)
            self.assertEqual(delivery.delivery_status, "dry_run_sent")
            self.assertEqual(delivery.delivery_mode, "dry_run")
            self.assertTrue(delivery.dry_run)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.delivery_id, delivery.delivery_id)

    def test_delivery_final_e2e_mock_post_sent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            calls: list[dict] = []
            pipeline = EventPipelineService(
                self._settings(temp_dir, event_delivery_mode="post", event_delivery_target_url="http://mock-main.local/events")
            )

            class Response:
                status_code = 200

            def fake_post(url: str, json: dict, timeout: float) -> Response:
                calls.append({"url": url, "json": json, "timeout": timeout})
                return Response()

            previous = delivery_module.requests.post
            delivery_module.requests.post = fake_post
            try:
                incident_id = pipeline.observe_result(self._result("final-post-sent", "fallen_confirmed"))[0].incident_id
                processed = pipeline.process_once("final-e2e-post")
            finally:
                delivery_module.requests.post = previous

            delivery = pipeline.delivery_outbox.for_incident(incident_id)
            self.assertEqual(processed.status, "sent")
            self.assertEqual(delivery.delivery_status, "sent")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["json"]["incident_id"], incident_id)
            self.assertEqual(calls[0]["json"]["delivery_mode"], "post")
            self.assertFalse(calls[0]["json"]["dry_run"])

    def test_delivery_final_e2e_mock_post_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = EventPipelineService(
                self._settings(temp_dir, event_delivery_mode="post", event_delivery_target_url="http://mock-main.local/events")
            )

            class Response:
                status_code = 500

            previous = delivery_module.requests.post
            delivery_module.requests.post = lambda *args, **kwargs: Response()
            try:
                incident_id = pipeline.observe_result(self._result("final-post-retry", "fallen_confirmed"))[0].incident_id
                processed = pipeline.process_once("final-e2e-retry")
            finally:
                delivery_module.requests.post = previous

            delivery = pipeline.delivery_outbox.for_incident(incident_id)
            self.assertEqual(processed.status, "retry")
            self.assertEqual(delivery.delivery_status, "retry")
            self.assertEqual(delivery.last_http_status, 500)
            self.assertIsNotNone(delivery.next_retry_at)

    def test_delivery_final_e2e_retry_to_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = EventPipelineService(
                self._settings(
                    temp_dir,
                    event_delivery_mode="post",
                    event_delivery_target_url="http://mock-main.local/events",
                    event_delivery_retry_limit=2,
                )
            )

            class Response:
                status_code = 503

            previous = delivery_module.requests.post
            delivery_module.requests.post = lambda *args, **kwargs: Response()
            try:
                incident_id = pipeline.observe_result(self._result("final-post-failed", "fallen_confirmed"))[0].incident_id
                pipeline.process_once("final-e2e-failed-1")
                delivery = pipeline.delivery_outbox.for_incident(incident_id)
                assert delivery is not None
                pipeline.delivery_outbox.mark_retry(delivery.delivery_id, "http_503", 503, "2026-07-18T00:00:00+00:00")
                pipeline.outbox.mark_retry(incident_id, "http_503", "2026-07-18T00:00:00+00:00")
                processed = pipeline.process_once("final-e2e-failed-2")
            finally:
                delivery_module.requests.post = previous

            failed = pipeline.delivery_outbox.for_incident(incident_id)
            self.assertEqual(processed.status, "retry")
            self.assertEqual(failed.delivery_status, "failed")
            self.assertEqual(failed.attempt_count, 2)

    def test_delivery_final_e2e_api_summary_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pipeline = EventPipelineService(self._settings(temp_dir, event_delivery_mode="dry_run"))
            incident_id = pipeline.observe_result(self._result("final-api-safe", "fallen_confirmed"))[0].incident_id
            pipeline.process_once("final-e2e-api")
            delivery = pipeline.delivery_outbox.for_incident(incident_id)
            assert delivery is not None

            app = FastAPI()
            app.state.runtime = SimpleNamespace(settings=pipeline.settings, event_pipeline=pipeline, event_delivery_worker=None)
            app.include_router(event_api.router)
            with TestClient(app) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                detail = client.get(f"/events/{incident_id}")

            for response in (latest, detail):
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("lock_token", response.text)
                self.assertNotIn("lock_owner", response.text)
                self.assertNotIn("lock_until", response.text)
                self.assertNotIn("payload_json", response.text)
                self.assertNotIn(str(Path(temp_dir)), response.text)
            summary = latest.json()["event"]["delivery"]
            self.assertEqual(summary["delivery_status"], "dry_run_sent")
            self.assertEqual(summary["delivery_backend"], "sqlite")
            self.assertIn("payload_summary", summary)

    def test_delivery_final_e2e_legacy_reporter_unchanged(self) -> None:
        settings = Settings()
        self.assertFalse(settings.event_delivery_enabled)
        self.assertFalse(settings.event_delivery_worker_enabled)
        self.assertEqual(settings.event_delivery_mode, "dry_run")

    @staticmethod
    def _settings(temp_dir: str, **overrides) -> Settings:
        return replace(
            Settings(),
            event_pipeline_enabled=True,
            event_worker_enabled=True,
            event_semantic_enabled=True,
            event_vlm_enabled=False,
            event_outbox_backend="sqlite",
            event_outbox_sqlite_path=str(Path(temp_dir) / "event_outbox.sqlite3"),
            event_delivery_enabled=True,
            event_delivery_worker_enabled=False,
            event_delivery_backend="sqlite",
            event_delivery_sqlite_path=str(Path(temp_dir) / "event_delivery_outbox.sqlite3"),
            event_delivery_retry_backoff_seconds=0.1,
            **overrides,
        )

    @staticmethod
    def _result(incident_key: str, fall_state: str) -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-18T10:00:00+00:00",
            frame_seq=100,
            frame_width=640,
            frame_height=360,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.93,
                    bbox=[100.0, 120.0, 310.0, 340.0],
                    track_id=abs(hash(incident_key)) % 10000 + 1,
                    fall_decision={
                        "fall_state": fall_state,
                        "risk_level": "critical",
                        "fall_probability": 0.93,
                        "fall_evidence_score": 0.91,
                        "adl_suppression_score": 0.08,
                    },
                    features={"fall_state_sequence": ["standing", "falling", fall_state]},
                    temporal={"fall_probability": 0.93, "post_event_stillness_ms": 3000},
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
