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
from app.events.delivery import build_main_system_payload
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, FallEventRecord, TrustedEventResult


class EventDeliveryABCFinalIntegrationGuardTest(unittest.TestCase):
    def test_public_event_summary_keeps_delivery_fields_and_hides_internal_data(self) -> None:
        with TemporaryDirectory() as directory:
            settings = replace(
                Settings(),
                event_pipeline_enabled=True,
                event_delivery_enabled=True,
                event_delivery_mode="dry_run",
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=str(Path(directory) / "delivery.sqlite3"),
            )
            pipeline = EventPipelineService(settings)
            pipeline.outbox.add_event(FallEventRecord(
                incident_id="abc-final-guard",
                camera_id="camera_01",
                event_type="fall_candidate",
                fall_state="fallen_candidate",
                trigger_timestamp="2026-07-18T10:00:00+00:00",
            ))
            pipeline.outbox.mark_evidence_ready("abc-final-guard", self._evidence())
            pipeline.outbox.mark_semantic_ready("abc-final-guard", self._semantics())
            pipeline.outbox.mark_reviewed("abc-final-guard", self._trusted())
            pipeline.outbox.mark_delivery_pending("abc-final-guard")
            record = pipeline.delivery_outbox.enqueue(self._trusted(), self._evidence(), self._semantics())
            pipeline.delivery_outbox.deliver(record.delivery_id)

            app = FastAPI()
            app.state.runtime = SimpleNamespace(settings=settings, event_pipeline=pipeline, event_delivery_worker=None)
            app.include_router(event_api.router)
            with TestClient(app) as client:
                latest = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(latest.status_code, 200)
            text = latest.text
            for forbidden in (
                "lock_token",
                "lock_owner",
                "lock_until",
                "payload_json",
                "target_url",
                "auth header",
                "token",
                "D:\\",
                "/workspace",
                "logs/event_archive",
                "raw_response",
                "keyframe_image_paths",
                "timeline_image_path",
            ):
                self.assertNotIn(forbidden, text)
            delivery = latest.json()["event"]["delivery"]
            for key in ("delivery_status", "delivery_mode", "dry_run", "retry_count", "delivery_backend", "last_error", "delivered_at"):
                self.assertIn(key, delivery)
            self.assertEqual(delivery["delivery_status"], "dry_run_sent")
            self.assertEqual(delivery["delivery_mode"], "dry_run")
            self.assertTrue(delivery["dry_run"])
            self.assertEqual(delivery["delivery_backend"], "sqlite")

    def test_vlm_ollama_fields_do_not_contaminate_delivery_payload(self) -> None:
        payload = build_main_system_payload(self._trusted(), self._evidence(), self._semantics())

        text = str(payload)
        self.assertEqual(payload["delivery_mode"], "dry_run")
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["review_result"], "rule_confirmed_vlm_advisory")
        self.assertIn("ollama_disabled", payload["degradation_used"])
        for forbidden in ("raw_response", "keyframe_image_paths", "timeline_image_path", "D:\\", "/workspace", "logs/event_archive"):
            self.assertNotIn(forbidden, text)

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="abc-final-guard",
            support_fall_alarm=True,
            final_event_type="fallen_confirmed",
            final_risk_level="critical",
            confidence=0.92,
            explanation="rule result with optional VLM advisory fields available",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="check immediately",
            review_result="rule_confirmed_vlm_advisory",
            degradation_used=["ollama_disabled"],
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="abc-final-guard",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T10:00:00+00:00",
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    image_path=r"D:\Program\camera-service\camera_79\logs\event_archive\frame.jpg",
                    snapshot_url=r"D:\Program\camera-service\camera_79\logs\event_archive\frame.jpg",
                )
            ],
            degradation_used=["missing_keyframe"],
        )

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="abc-final-guard",
            uncertainty=["vlm_disabled"],
            degradation_used=["ollama_disabled"],
            evidence={
                "raw_response": "{\"unsafe\":\"provider raw text\"}",
                "keyframe_image_paths": [r"D:\Program\camera-service\camera_79\logs\event_archive\frame.jpg"],
                "timeline_image_path": r"D:\Program\camera-service\camera_79\logs\event_archive\timeline.jpg",
            },
        )


if __name__ == "__main__":
    unittest.main()
