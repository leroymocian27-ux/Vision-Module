from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.events.delivery import DeliveryOutbox
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, FallEventRecord, TrustedEventResult


class EventFrontendPublicSummaryGuardTest(unittest.TestCase):
    def _client(self, pipeline: EventPipelineService) -> TestClient:
        app = FastAPI()
        app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
        app.include_router(event_api.router)
        return TestClient(app)

    def test_latest_public_summary_keeps_frontend_safe_contract(self) -> None:
        with TemporaryDirectory() as directory:
            archive_file = Path(directory) / "camera_01" / "freeze-guard" / "keyframes" / "t0.jpg"
            archive_file.parent.mkdir(parents=True)
            archive_file.write_bytes(b"\xff\xd8\xff\xd9")

            settings = replace(
                Settings(),
                event_pipeline_enabled=True,
                event_archive_enabled=True,
                event_archive_dir=directory,
                event_keyframe_serving_enabled=True,
                event_delivery_enabled=True,
                event_delivery_mode="dry_run",
                event_delivery_target_url="http://internal-main.example/events?token=secret",
            )
            pipeline = EventPipelineService(settings)
            pipeline.outbox.add_event(FallEventRecord(
                incident_id="freeze-guard",
                camera_id="camera_01",
                event_type="fall_candidate",
                fall_state="fallen_candidate",
                risk_level="high",
                trigger_timestamp="2026-07-18T09:30:00+00:00",
            ))
            evidence = EvidencePackage(
                incident_id="freeze-guard",
                camera_id="camera_01",
                trigger_timestamp="2026-07-18T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
            )
            trusted = TrustedEventResult(
                incident_id="freeze-guard",
                support_fall_alarm=True,
                final_event_type="fall_candidate",
                final_risk_level="high",
                confidence=0.86,
                explanation="rule result",
                alarm_title="Freeze guard",
                alarm_body="Freeze guard demo event.",
                recommended_action="review",
                review_result="rule_only",
                degradation_used=["vlm_timeout"],
            )
            pipeline.outbox.mark_evidence_ready("freeze-guard", evidence)
            pipeline.outbox.mark_reviewed("freeze-guard", trusted)
            pipeline.outbox.mark_archive(
                "freeze-guard",
                "camera_01/freeze-guard",
                {
                    "archive_id": "camera_01/freeze-guard",
                    "timeline_image_url": "/events/freeze-guard/keyframes/t0",
                    "timeline_image_path": "timeline/timeline.jpg",
                    "local_path": str(Path(directory) / "camera_01" / "freeze-guard"),
                    "raw_response": {"token": "secret"},
                },
            )
            pipeline.delivery_outbox = DeliveryOutbox(settings)
            delivery = pipeline.delivery_outbox.enqueue(trusted, evidence, None)
            pipeline.delivery_outbox.deliver(delivery.delivery_id)

            with self._client(pipeline) as client:
                response = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(response.status_code, 200)
            text = response.text
            payload = response.json()["event"]
            keyframe = payload["evidence_package"]["keyframes"][0]

            self.assertEqual(keyframe["keyframe_url"], "/events/freeze-guard/keyframes/t0")
            self.assertTrue(keyframe["keyframe_url"].startswith("/events/"))
            self.assertEqual(payload["archive_summary"]["timeline_image_url"], "/events/freeze-guard/keyframes/t0")

            forbidden_tokens = (
                str(Path(directory)),
                "target_url",
                "lock_token",
                "payload_json",
                "raw_response",
                "http://internal-main.example",
                "token=secret",
            )
            for token in forbidden_tokens:
                self.assertNotIn(token, text)
            self.assertEqual(payload["archive_summary"]["timeline_image_path"], "timeline/timeline.jpg")

            delivery_summary = payload["delivery"]
            self.assertEqual(delivery_summary["delivery_status"], "dry_run_sent")
            self.assertTrue(delivery_summary["dry_run"])
            self.assertIn("payload_summary", delivery_summary)
            json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
