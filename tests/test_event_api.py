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
from app.events.pipeline import EventPipelineService
from app.events.schemas import EvidenceKeyframe, EvidencePackage, FallEventRecord


class EventApiTest(unittest.TestCase):
    def _client(self, pipeline: EventPipelineService) -> TestClient:
        app = FastAPI()
        app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
        app.include_router(event_api.router)
        return TestClient(app)

    def test_disabled_status_is_explicit(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=False))
        with self._client(pipeline) as client:
            response = client.get("/events/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["event_pipeline_enabled"])

    def test_outbox_and_latest_are_visible(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=True))
        pipeline.outbox.add_event(FallEventRecord(
            incident_id="api-incident", camera_id="camera_01", event_type="fall_candidate",
            fall_state="fallen_candidate", risk_level="high", trigger_timestamp="2026-07-17T09:30:00+00:00",
        ))
        with self._client(pipeline) as client:
            outbox = client.get("/events/outbox?camera_id=camera_01")
            latest = client.get("/events/latest?camera_id=camera_01")
            detail = client.get("/events/api-incident")
        self.assertEqual(outbox.status_code, 200)
        self.assertEqual(outbox.json()["items"][0]["event"]["incident_id"], "api-incident")
        self.assertEqual(latest.json()["event"]["event"]["incident_id"], "api-incident")
        self.assertEqual(detail.status_code, 200)

    def test_latest_includes_frontend_keyframe_summary_without_absolute_paths(self) -> None:
        with TemporaryDirectory() as directory:
            archive_file = Path(directory) / "camera_01" / "api-keyframes" / "keyframes" / "t0.jpg"
            archive_file.parent.mkdir(parents=True)
            archive_file.write_bytes(b"\xff\xd8\xff\xd9")
            pipeline = EventPipelineService(replace(
                Settings(),
                event_pipeline_enabled=True,
                event_archive_enabled=True,
                event_archive_dir=directory,
                event_keyframe_serving_enabled=True,
            ))
            pipeline.outbox.add_event(FallEventRecord(
                incident_id="api-keyframes",
                camera_id="camera_01",
                event_type="fall_candidate",
                fall_state="fallen_candidate",
                risk_level="high",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
            ))
            pipeline.outbox.mark_evidence_ready("api-keyframes", EvidencePackage(
                incident_id="api-keyframes",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[
                    EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg"),
                    EvidenceKeyframe(role="post_check", offset_ms=5000, missing_reason="no_frame_near_target"),
                ],
            ))
            pipeline.outbox.mark_archive(
                "api-keyframes",
                "camera_01/api-keyframes",
                {
                    "archive_id": "camera_01/api-keyframes",
                    "local_path": str(Path(directory) / "camera_01" / "api-keyframes"),
                    "nested": {"source_path": str(Path(directory) / "source.mp4")},
                },
            )

            with self._client(pipeline) as client:
                response = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(response.status_code, 200)
            payload_text = response.text
            self.assertNotIn(str(Path(directory)), payload_text)
            event = response.json()["event"]
            self.assertIsNone(event["archive_path"])
            self.assertEqual(event["archive_id"], "camera_01/api-keyframes")
            self.assertIsNone(event["archive_summary"]["local_path"])
            self.assertIsNone(event["archive_summary"]["nested"]["source_path"])
            keyframes = event["evidence_package"]["keyframes"]
            self.assertEqual(keyframes[0]["label"], "T0")
            self.assertTrue(keyframes[0]["available"])
            self.assertEqual(keyframes[0]["keyframe_url"], "/events/api-keyframes/keyframes/t0")
            self.assertEqual(keyframes[1]["label"], "T+5s")
            self.assertFalse(keyframes[1]["available"])
            self.assertIsNone(keyframes[1]["keyframe_url"])
            self.assertEqual(keyframes[1]["missing_reason"], "no_frame_near_target")

    def test_payload_redaction_covers_nested_and_delivery_fields(self) -> None:
        payload = event_api._redact_local_absolute_paths({
            "relative": "keyframes/t0.jpg",
            "nested": {"windows": r"D:\\Program\\event_archive\\frame.jpg"},
            "items": ["/var/lib/event_archive/frame.jpg", "safe"],
        })
        delivery = event_api._delivery_payload(SimpleNamespace(
            delivery_id="delivery-01",
            incident_id="incident-01",
            camera_id="camera_01",
            target_url=r"D:\\Program\\main-system",
            delivery_status="failed",
            delivery_mode="post",
            dry_run=False,
            attempt_count=1,
            last_http_status=None,
            last_error="copy failed: /var/lib/event_archive/frame.jpg",
            next_retry_at=None,
            lock_owner=None,
            lock_until=None,
            delivered_at=None,
            created_at="2026-07-18T00:00:00+00:00",
            updated_at="2026-07-18T00:00:00+00:00",
            payload_json={},
        ))

        self.assertEqual(payload["relative"], "keyframes/t0.jpg")
        self.assertIsNone(payload["nested"]["windows"])
        self.assertIsNone(payload["items"][0])
        self.assertNotIn("target_url", delivery)
        self.assertEqual(delivery["last_error"], "copy failed: [local-path-redacted]")
