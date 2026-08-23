from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryApiTest(unittest.TestCase):
    def _client(self, runtime) -> TestClient:
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(event_api.router)
        return TestClient(app)

    def test_delivery_status_disabled_is_explicit(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=False)
        pipeline = EventPipelineService(settings)
        runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)

        with self._client(runtime) as client:
            response = client.get("/events/delivery/status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["event_delivery_enabled"])
        self.assertEqual(payload["delivery_backend"], "memory")
        self.assertFalse(payload["worker_running"])
        self.assertEqual(payload["total_count"], 0)

    def test_delivery_outbox_and_detail_are_read_only_and_sanitized(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        pipeline = EventPipelineService(settings)
        record = pipeline.delivery_outbox.enqueue(
            self._trusted(),
            self._evidence(snapshot_url="D:\\Program\\camera-service\\camera_79\\logs\\event.jpg"),
            EventSemantics(incident_id="delivery-api-1"),
        )
        before = pipeline.delivery_outbox.get(record.delivery_id).model_dump(mode="json")
        runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("delivery API must not POST")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            with self._client(runtime) as client:
                outbox = client.get("/events/delivery/outbox?camera_id=camera_01")
                detail = client.get(f"/events/delivery/{record.delivery_id}")
                by_incident = client.get("/events/delivery/by-incident/delivery-api-1")
        finally:
            delivery_module.requests.post = previous_post

        after = pipeline.delivery_outbox.get(record.delivery_id).model_dump(mode="json")
        self.assertEqual(calls, [])
        self.assertEqual(before, after)
        self.assertEqual(outbox.status_code, 200)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(by_incident.status_code, 200)
        detail_json = detail.json()
        self.assertNotIn("payload_json", detail_json)
        self.assertIn("payload_summary", detail_json)
        self.assertIsNone(detail_json["payload_summary"]["snapshot_url"])
        self.assertNotIn("D:\\", detail.text)
        self.assertEqual(outbox.json()["items"][0]["delivery_id"], record.delivery_id)

    def test_delivery_status_counts_and_outbox_status_filter(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        pipeline = EventPipelineService(settings)
        dry_run = pipeline.delivery_outbox.enqueue(
            self._trusted("delivery-api-dry"),
            self._evidence("delivery-api-dry"),
            EventSemantics(incident_id="delivery-api-dry"),
        )
        retry = pipeline.delivery_outbox.enqueue(
            self._trusted("delivery-api-retry"),
            self._evidence("delivery-api-retry"),
            EventSemantics(incident_id="delivery-api-retry"),
        )
        failed = pipeline.delivery_outbox.enqueue(
            self._trusted("delivery-api-failed"),
            self._evidence("delivery-api-failed"),
            EventSemantics(incident_id="delivery-api-failed"),
        )
        pipeline.delivery_outbox.deliver(dry_run.delivery_id)
        pipeline.delivery_outbox.mark_retry(retry.delivery_id, "http_500", 500, "2026-07-17T09:31:00+00:00")
        pipeline.delivery_outbox.mark_failed(failed.delivery_id, "http_500", 500)
        runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)

        with self._client(runtime) as client:
            status = client.get("/events/delivery/status")
            retry_items = client.get("/events/delivery/outbox?status=retry")

        self.assertEqual(status.status_code, 200)
        status_json = status.json()
        self.assertEqual(status_json["dry_run_sent_count"], 1)
        self.assertEqual(status_json["retry_count"], 1)
        self.assertEqual(status_json["failed_count"], 1)
        self.assertEqual(status_json["total_count"], 3)
        self.assertEqual(retry_items.status_code, 200)
        self.assertEqual(len(retry_items.json()["items"]), 1)
        self.assertEqual(retry_items.json()["items"][0]["delivery_status"], "retry")

    def test_delivery_detail_not_found_returns_404(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True)
        pipeline = EventPipelineService(settings)
        runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)

        with self._client(runtime) as client:
            response = client.get("/events/delivery/missing-delivery")

        self.assertEqual(response.status_code, 404)

    def test_sqlite_delivery_api_lists_reopened_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                event_delivery_enabled=True,
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=str(Path(temp_dir) / "delivery.sqlite3"),
            )
            pipeline = EventPipelineService(settings)
            record = pipeline.delivery_outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-api-1"))
            reopened = EventPipelineService(settings)
            runtime = SimpleNamespace(settings=settings, event_pipeline=reopened, event_delivery_worker=None)

            with self._client(runtime) as client:
                response = client.get("/events/delivery/outbox")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["items"][0]["delivery_id"], record.delivery_id)

    @staticmethod
    def _trusted(incident_id: str = "delivery-api-1") -> TrustedEventResult:
        return TrustedEventResult(
            incident_id=incident_id,
            support_fall_alarm=True,
            final_event_type="fallen_confirmed",
            final_risk_level="critical",
            confidence=0.9,
            explanation="confirmed",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="check",
        )

    @staticmethod
    def _evidence(
        incident_id: str = "delivery-api-1",
        snapshot_url: str = "http://testserver/fall-events/snapshots/delivery-api-1.jpg",
    ) -> EvidencePackage:
        return EvidencePackage(
            incident_id=incident_id,
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, snapshot_url=snapshot_url)],
        )


if __name__ == "__main__":
    unittest.main()
