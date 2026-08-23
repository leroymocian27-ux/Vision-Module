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


class EventKeyframeApiTest(unittest.TestCase):
    def _client(self, pipeline: EventPipelineService) -> TestClient:
        app = FastAPI()
        app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
        app.include_router(event_api.router)
        return TestClient(app)

    def _pipeline(self, archive_dir: str) -> EventPipelineService:
        return EventPipelineService(replace(
            Settings(),
            event_pipeline_enabled=True,
            event_archive_enabled=True,
            event_archive_dir=archive_dir,
            event_keyframe_serving_enabled=True,
        ))

    def _disabled_pipeline(self, archive_dir: str) -> EventPipelineService:
        return EventPipelineService(replace(
            Settings(),
            event_pipeline_enabled=False,
            event_archive_enabled=True,
            event_archive_dir=archive_dir,
        ))

    def _add_event(self, pipeline: EventPipelineService, evidence: EvidencePackage) -> None:
        pipeline.outbox.add_event(FallEventRecord(
            incident_id=evidence.incident_id,
            camera_id=evidence.camera_id,
            event_type="fall_candidate",
            fall_state="fallen_candidate",
            risk_level="high",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
        ))
        pipeline.outbox.mark_evidence_ready(evidence.incident_id, evidence)
        pipeline.outbox.mark_archive(evidence.incident_id, f"{evidence.camera_id}/{evidence.incident_id}", {})

    def test_keyframe_api_serves_only_archived_image_and_payload_uses_relative_url(self) -> None:
        with TemporaryDirectory() as directory:
            archive_file = Path(directory) / "camera_01" / "incident-keyframe" / "keyframes" / "t0.jpg"
            archive_file.parent.mkdir(parents=True)
            archive_file.write_bytes(b"\xff\xd8\xff\xd9")
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-keyframe",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
            ))

            with self._client(pipeline) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                image = client.get("/events/incident-keyframe/keyframes/t0")
                image_by_offset = client.get("/events/incident-keyframe/keyframes/by-offset/0")

            keyframe = latest.json()["event"]["evidence_package"]["keyframes"][0]
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(keyframe["label"], "T0")
            self.assertTrue(keyframe["available"])
            self.assertEqual(keyframe["keyframe_url"], "/events/incident-keyframe/keyframes/t0")
            self.assertNotIn(str(Path(directory)), latest.text)
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.headers["content-type"], "image/jpeg")
            self.assertEqual(image.content, b"\xff\xd8\xff\xd9")
            self.assertEqual(image_by_offset.status_code, 200)

    def test_disabled_pipeline_keyframe_api_is_not_500(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._disabled_pipeline(directory)
            with self._client(pipeline) as client:
                response = client.get("/events/incident-keyframe/keyframes/t0")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "EVENT_PIPELINE_DISABLED")

    def test_keyframe_serving_disabled_hides_image_metadata_and_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            archive_file = Path(directory) / "camera_01" / "incident-private" / "keyframes" / "t0.jpg"
            archive_file.parent.mkdir(parents=True)
            archive_file.write_bytes(b"\xff\xd8\xff\xd9")
            pipeline = EventPipelineService(replace(
                Settings(),
                event_pipeline_enabled=True,
                event_archive_enabled=True,
                event_archive_dir=directory,
                event_keyframe_serving_enabled=False,
            ))
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-private",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
            ))

            with self._client(pipeline) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                image = client.get("/events/incident-private/keyframes/t0")

            keyframe = latest.json()["event"]["evidence_package"]["keyframes"][0]
            self.assertFalse(keyframe["available"])
            self.assertIsNone(keyframe["image_path"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(keyframe["missing_reason"], "keyframe_serving_disabled")
            self.assertEqual(image.status_code, 404)
            self.assertEqual(image.json()["detail"]["reason"], "KEYFRAME_SERVING_DISABLED")

    def test_missing_event_returns_404_reason(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            with self._client(pipeline) as client:
                response = client.get("/events/not-found/keyframes/t0")

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "EVENT_NOT_FOUND")

    def test_invalid_incident_id_and_encoded_traversal_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            with self._client(pipeline) as client:
                invalid = client.get("/events/invalid.id/keyframes/t0")
                traversal = client.get("/events/%2E%2E/keyframes/t0")

            self.assertEqual(invalid.status_code, 404)
            self.assertEqual(invalid.json()["detail"]["reason"], "INVALID_INCIDENT_ID")
            self.assertIn(traversal.status_code, {400, 404})

    def test_missing_keyframe_returns_clear_404_reason(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-missing",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(
                    role="pre_context",
                    offset_ms=-3000,
                    missing_reason="no_frame_near_target",
                )],
            ))

            with self._client(pipeline) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                response = client.get("/events/incident-missing/keyframes/t_minus_3s")

            keyframe = latest.json()["event"]["evidence_package"]["keyframes"][0]
            self.assertFalse(keyframe["available"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(keyframe["missing_reason"], "no_frame_near_target")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "KEYFRAME_MISSING")
            self.assertEqual(response.json()["detail"]["missing_reason"], "no_frame_near_target")

    def test_keyframe_api_rejects_traversal_path(self) -> None:
        with TemporaryDirectory() as directory:
            Path(directory, "secret.jpg").write_bytes(b"secret")
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-traversal",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/../../secret.jpg")],
            ))

            with self._client(pipeline) as client:
                detail = client.get("/events/incident-traversal")
                response = client.get("/events/incident-traversal/keyframes/0")

            keyframe = detail.json()["evidence_package"]["keyframes"][0]
            self.assertIsNone(keyframe["image_path"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "INVALID_KEYFRAME_PATH")

    def test_keyframe_api_rejects_windows_drive_path(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-drive-path",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="C:/Windows/win.ini")],
            ))

            with self._client(pipeline) as client:
                detail = client.get("/events/incident-drive-path")
                response = client.get("/events/incident-drive-path/keyframes/t0")

            keyframe = detail.json()["evidence_package"]["keyframes"][0]
            self.assertFalse(keyframe["available"])
            self.assertIsNone(keyframe["image_path"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "INVALID_KEYFRAME_PATH")

    def test_keyframe_api_rejects_absolute_path(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-absolute-path",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="/tmp/keyframes/t0.jpg")],
            ))

            with self._client(pipeline) as client:
                detail = client.get("/events/incident-absolute-path")
                response = client.get("/events/incident-absolute-path/keyframes/t0")

            keyframe = detail.json()["evidence_package"]["keyframes"][0]
            self.assertFalse(keyframe["available"])
            self.assertIsNone(keyframe["image_path"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "INVALID_KEYFRAME_PATH")

    def test_keyframe_api_rejects_absolute_image_path_without_leaking_it(self) -> None:
        with TemporaryDirectory() as directory:
            outside = Path(directory) / "outside.jpg"
            outside.write_bytes(b"\xff\xd8\xff\xd9")
            pipeline = self._pipeline(directory)
            self._add_event(pipeline, EvidencePackage(
                incident_id="incident-absolute-path",
                camera_id="camera_01",
                trigger_timestamp="2026-07-17T09:30:00+00:00",
                keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path=str(outside))],
            ))

            with self._client(pipeline) as client:
                detail = client.get("/events/incident-absolute-path")
                response = client.get("/events/incident-absolute-path/keyframes/t0")

            self.assertNotIn(str(outside), detail.text)
            keyframe = detail.json()["evidence_package"]["keyframes"][0]
            self.assertIsNone(keyframe["image_path"])
            self.assertIsNone(keyframe["keyframe_url"])
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"]["reason"], "INVALID_KEYFRAME_PATH")


if __name__ == "__main__":
    unittest.main()
