from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.events.delivery import DeliveryOutbox, build_main_system_payload
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, FallEventRecord, TrustedEventResult


class EventDeliverySecurityPayloadTest(unittest.TestCase):
    def test_payload_filters_local_paths_and_never_contains_image_bytes(self) -> None:
        payload = build_main_system_payload(
            self._trusted(),
            EvidencePackage(
                incident_id="security-1",
                camera_id="camera_01",
                trigger_timestamp="2026-07-18T10:00:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, snapshot_url=r"D:\Program\camera-service\camera_79\logs\event_archive\frame.jpg")],
            ),
            EventSemantics(incident_id="security-1", degradation_used=["vlm_timeout"]),
        )

        text = str(payload)
        self.assertIsNone(payload["snapshot_url"])
        self.assertNotIn("D:\\", text)
        self.assertNotIn("/workspace", text)
        self.assertNotIn("logs/event_archive", text)
        self.assertNotIn("image_bytes", payload)
        self.assertIn("vlm_timeout", payload["degradation_used"])

    def test_event_api_delivery_summary_hides_lock_token_and_raw_payload(self) -> None:
        settings = replace(Settings(), event_pipeline_enabled=True, event_delivery_enabled=True, event_delivery_mode="post")
        pipeline = EventPipelineService(settings)
        pipeline.outbox.add_event(FallEventRecord(
            incident_id="security-1",
            camera_id="camera_01",
            event_type="fall_candidate",
            fall_state="fallen_candidate",
            trigger_timestamp="2026-07-18T10:00:00+00:00",
        ))
        record = pipeline.delivery_outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="security-1"))
        claimed = pipeline.delivery_outbox.claim_next("worker-a", 30)
        self.assertIsNotNone(claimed)
        self.assertTrue(claimed.lock_token)

        app = FastAPI()
        app.state.runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)
        app.include_router(event_api.router)
        with TestClient(app) as client:
            latest = client.get("/events/latest?camera_id=camera_01")
            detail = client.get(f"/events/delivery/{record.delivery_id}")

        for response in (latest, detail):
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("lock_token", response.text)
            self.assertNotIn("payload_json", response.text)
        delivery = latest.json()["event"]["delivery"]
        self.assertEqual(delivery["delivery_status"], "pending")
        self.assertIn("retry_count", delivery)
        self.assertIn("delivery_backend", delivery)

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="security-1",
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
    def _evidence() -> EvidencePackage:
        return EvidencePackage(incident_id="security-1", camera_id="camera_01", trigger_timestamp="2026-07-18T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
