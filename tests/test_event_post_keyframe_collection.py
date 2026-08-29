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


class EventPostKeyframeCollectionTest(unittest.TestCase):
    def test_collecting_then_complete_updates_all_six_keyframes(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            self._frames(pipeline, (-3000, -1000, 0))
            incident = pipeline.observe_result(self._result())[0].incident_id
            pipeline.process_once("initial")
            initial = pipeline.outbox.get_event(incident)
            self.assertEqual(initial.archive_summary["evidence_status"], "collecting")
            self.assertEqual(sum(not item.missing_reason for item in initial.evidence_package.keyframes), 3)

            self._frames(pipeline, (1000, 3000, 5000))
            pipeline._collect_post_keyframes(incident)  # test-only deterministic finalizer
            completed = pipeline.outbox.get_event(incident)
            self.assertEqual(completed.archive_summary["evidence_status"], "complete")
            self.assertEqual(sum(not item.missing_reason for item in completed.evidence_package.keyframes), 6)

    def test_missing_post_frames_degrade_and_api_remains_safe(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory)
            self._frames(pipeline, (-3000, -1000, 0))
            incident = pipeline.observe_result(self._result())[0].incident_id
            pipeline.process_once("initial")
            pipeline._collect_post_keyframes(incident)
            record = pipeline.outbox.get_event(incident)
            self.assertEqual(record.archive_summary["evidence_status"], "degraded")
            self.assertTrue(any(item.missing_reason == "no_frame_near_target" for item in record.evidence_package.keyframes))

            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)
            with TestClient(app) as client:
                latest = client.get("/events/latest?camera_id=camera_01")
                detail = client.get(f"/events/{incident}")

            self.assertEqual(latest.status_code, 200)
            self.assertEqual(detail.status_code, 200)
            keyframes = detail.json()["evidence_package"]["keyframes"]
            self.assertTrue(all(item["keyframe_url"] is None for item in keyframes))

    @staticmethod
    def _pipeline(directory: str) -> EventPipelineService:
        return EventPipelineService(replace(
            Settings(), event_pipeline_enabled=True, event_ring_buffer_enabled=True,
            event_worker_enabled=True, event_semantic_enabled=True,
            event_archive_enabled=True, event_archive_dir=directory,
            event_post_keyframe_collection_enabled=True,
            event_post_keyframe_window_seconds=60,
            event_keyframe_offsets_ms=(-3000, -1000, 0, 1000, 3000, 5000),
        ))

    @staticmethod
    def _frames(pipeline: EventPipelineService, offsets: tuple[int, ...]) -> None:
        trigger = datetime(2026, 7, 18, 10, 30, tzinfo=timezone.utc)
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        for offset in offsets:
            pipeline.ring_buffer.add_frame("camera_01", 400 + offset // 1000, (trigger + timedelta(milliseconds=offset)).isoformat(), image)

    @staticmethod
    def _result() -> VisionResult:
        return VisionResult(camera_id="camera_01", timestamp="2026-07-18T10:30:00+00:00", frame_seq=400, frame_width=640, frame_height=360, objects=[DetectedObject(
            label="person", confidence=0.9, bbox=[1, 2, 30, 50], track_id=4,
            fall_decision={"fall_state": "fallen_candidate", "risk_level": "high", "fall_probability": 0.8},
        )])
