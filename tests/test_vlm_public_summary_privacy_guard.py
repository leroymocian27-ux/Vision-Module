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
from app.events.schemas import EvidenceKeyframe, EvidencePackage, FallEventRecord, TrustedEventResult


class VLMPublicSummaryPrivacyGuardTest(unittest.TestCase):
    def test_public_event_summary_redacts_provider_private_payload_and_paths(self) -> None:
        with TemporaryDirectory() as directory:
            local_timeline = str(Path(directory) / "camera_01" / "privacy-public" / "timeline" / "timeline.jpg")
            pipeline = EventPipelineService(
                replace(
                    Settings(),
                    event_pipeline_enabled=True,
                    event_archive_enabled=True,
                    event_archive_dir=directory,
                    event_keyframe_serving_enabled=True,
                )
            )
            pipeline.outbox.add_event(
                FallEventRecord(
                    incident_id="privacy-public",
                    camera_id="camera_01",
                    event_type="fall_candidate",
                    fall_state="fallen_candidate",
                    risk_level="high",
                    trigger_timestamp="2026-07-18T09:30:00+00:00",
                )
            )
            pipeline.outbox.mark_evidence_ready(
                "privacy-public",
                EvidencePackage(
                    incident_id="privacy-public",
                    camera_id="camera_01",
                    trigger_timestamp="2026-07-18T09:30:00+00:00",
                    keyframes=[
                        EvidenceKeyframe(
                            role="trigger",
                            offset_ms=0,
                            image_path=str(Path(directory) / "keyframes" / "t0.jpg"),
                            snapshot_url=str(Path(directory) / "keyframes" / "t0.jpg"),
                        )
                    ],
                ),
            )
            pipeline.outbox.mark_reviewed(
                "privacy-public",
                TrustedEventResult(
                    incident_id="privacy-public",
                    support_fall_alarm=True,
                    final_event_type="fall_candidate",
                    final_risk_level="high",
                    confidence=0.82,
                    explanation="rule result",
                    alarm_title="review",
                    alarm_body="body",
                    recommended_action="action",
                    review_result="rule_with_vlm_advisory",
                    vlm_provider="qwen_ollama",
                    observed_process="structured text-only review",
                ),
            )
            pipeline.outbox.mark_archive(
                "privacy-public",
                "camera_01/privacy-public",
                {
                    "archive_id": "camera_01/privacy-public",
                    "timeline_image_path": local_timeline,
                    "raw_response": "provider raw response",
                    "keyframe_image_paths": [str(Path(directory) / "keyframes" / "t0.jpg")],
                    "provider_request_payload": {
                        "messages": [{"role": "user", "content": "secret structured request"}],
                        "image_path": str(Path(directory) / "keyframes" / "t0.jpg"),
                    },
                    "request_json": {"token": "secret-token"},
                    "encoded_image": "data:image/jpeg;base64,AAAA",
                    "local_path": str(Path(directory) / "camera_01" / "privacy-public"),
                },
            )
            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)

            with TestClient(app) as client:
                response = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(response.status_code, 200)
            payload_text = response.text
            for forbidden in (
                "provider raw response",
                "keyframe_image_paths",
                "provider_request_payload",
                "secret structured request",
                "request_json",
                "secret-token",
                "data:image",
                "base64",
                str(Path(directory)),
            ):
                self.assertNotIn(forbidden, payload_text)
            archive_summary = response.json()["event"]["archive_summary"]
            self.assertIsNone(archive_summary["timeline_image_path"])
            self.assertIsNone(archive_summary["encoded_image"])
            self.assertIsNone(archive_summary["local_path"])

    def test_public_event_summary_allows_safe_relative_timeline_image_path(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = EventPipelineService(
                replace(Settings(), event_pipeline_enabled=True, event_archive_enabled=True, event_archive_dir=directory)
            )
            pipeline.outbox.add_event(
                FallEventRecord(
                    incident_id="privacy-relative-timeline",
                    camera_id="camera_01",
                    event_type="fall_candidate",
                    fall_state="fallen_candidate",
                    risk_level="high",
                    trigger_timestamp="2026-07-18T09:30:00+00:00",
                )
            )
            pipeline.outbox.mark_reviewed(
                "privacy-relative-timeline",
                TrustedEventResult(
                    incident_id="privacy-relative-timeline",
                    support_fall_alarm=True,
                    final_event_type="fall_candidate",
                    final_risk_level="high",
                    confidence=0.82,
                    explanation="rule result",
                    alarm_title="review",
                    alarm_body="body",
                    recommended_action="action",
                ),
            )
            pipeline.outbox.mark_archive(
                "privacy-relative-timeline",
                "camera_01/privacy-relative-timeline",
                {"timeline_image_path": "timeline/timeline.jpg"},
            )
            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)

            with TestClient(app) as client:
                response = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["event"]["archive_summary"]["timeline_image_path"], "timeline/timeline.jpg")


if __name__ == "__main__":
    unittest.main()
