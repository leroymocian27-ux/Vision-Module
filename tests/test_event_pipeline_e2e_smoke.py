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
from app.detection.realtime_result_store import RealtimeResultStore
from app.events.pipeline import EventPipelineService
from app.events.outbox import SQLiteEventOutbox
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.result_publisher_service import ResultPublisherService


class _ChannelSpy:
    def __init__(self, stop_event: threading.Event | None = None) -> None:
        self.stop_event = stop_event
        self.payloads: list[VisionResult] = []

    def publish(self, result: VisionResult) -> None:
        self.payloads.append(result)
        if self.stop_event is not None:
            self.stop_event.set()


class _RealtimeStoreSpy(RealtimeResultStore):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[VisionResult] = []

    def update_published(self, result: VisionResult) -> None:
        self.published.append(result)
        super().update_published(result)


class _ReporterSpy:
    def __init__(self) -> None:
        self.seen: list[VisionResult] = []

    def inspect_result(self, result: VisionResult) -> None:
        self.seen.append(result)


class EventPipelineE2ESmokeTest(unittest.TestCase):
    def test_enabled_without_worker_only_writes_pending_outbox(self) -> None:
        pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=False))

        records = pipeline.observe_result(self._result(fall_state="fallen_candidate", event_track_id=6, frame_seq=80))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "pending")
        self.assertIsNone(records[0].evidence_package)
        pipeline.start()
        self.assertFalse(pipeline.status()["worker_running"])
        self.assertEqual(pipeline.outbox.get_event(records[0].incident_id).status, "pending")

    def test_candidate_runs_full_lifecycle_with_sqlite_delivery(self) -> None:
        with TemporaryDirectory() as temp_dir:
            pipeline = EventPipelineService(
                replace(
                    Settings(),
                    event_pipeline_enabled=True,
                    event_ring_buffer_enabled=True,
                    event_worker_enabled=True,
                    event_semantic_enabled=True,
                    event_delivery_enabled=True,
                    event_delivery_mode="dry_run",
                    event_outbox_backend="sqlite",
                    event_outbox_sqlite_path=f"{temp_dir}/event_outbox.sqlite3",
                )
            )
            transitions = self._record_status_transitions(pipeline)
            self._add_trigger_frames(pipeline, camera_id="camera_01", trigger_seq=100)

            observed = pipeline.observe_result(
                self._result(
                    fall_state="fallen_candidate",
                    event_track_id=7,
                    frame_seq=100,
                    fall_probability=0.82,
                    fall_evidence_score=0.86,
                    adl_suppression_score=0.1,
                )
            )
            processed = pipeline.process_once("e2e-smoke")

            self.assertEqual([item.status for item in observed], ["pending"])
            self.assertEqual(
                transitions,
                ["pending", "processing", "evidence_ready", "semantic_ready", "reviewed", "delivery_pending"],
            )
            self.assertEqual(processed.status, "delivery_pending")
            self.assertEqual(processed.event.event_type, "fall_candidate")
            self.assertEqual(processed.event_semantics.risk["decision"], "need_attention")
            self.assertTrue(processed.trusted_result.support_fall_alarm)
            delivery = pipeline.delivery_outbox.for_incident(processed.incident_id)
            self.assertIsNotNone(delivery)
            self.assertEqual(delivery.delivery_status, "dry_run_sent")

    def test_confirmed_missing_keyframes_degrades_but_still_reviews(self) -> None:
        pipeline = EventPipelineService(
            replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=True, event_semantic_enabled=True)
        )

        pipeline.observe_result(self._result(fall_state="fallen_confirmed", event_track_id=8, frame_seq=120))
        processed = pipeline.process_once("missing-frame-smoke")

        self.assertEqual(processed.status, "delivery_pending")
        self.assertEqual(processed.event.event_type, "fallen_confirmed")
        self.assertTrue(processed.evidence_package.degradation_used)
        self.assertTrue(any(item.startswith("missing_") for item in processed.evidence_package.degradation_used))
        self.assertEqual(processed.trusted_result.final_event_type, "fallen_confirmed")
        self.assertTrue(processed.trusted_result.support_fall_alarm)
        self.assertNotEqual(processed.trusted_result.final_risk_level, "low")

    def test_adl_suppression_high_generates_need_review(self) -> None:
        pipeline = EventPipelineService(
            replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=True, event_semantic_enabled=True)
        )

        pipeline.observe_result(
            self._result(
                fall_state="fallen_candidate",
                event_track_id=9,
                frame_seq=140,
                fall_probability=0.8,
                fall_evidence_score=0.83,
                adl_suppression_score=0.9,
            )
        )
        processed = pipeline.process_once("adl-smoke")

        self.assertEqual(processed.event_semantics.risk["decision"], "need_review")
        self.assertFalse(processed.trusted_result.support_fall_alarm)
        self.assertEqual(processed.trusted_result.review_result, "rule_only")

    def test_disabled_event_chain_does_not_block_publisher_or_legacy_reporter(self) -> None:
        disabled_pipeline = EventPipelineService(replace(Settings(), event_pipeline_enabled=False))
        stop_event = threading.Event()
        store = _RealtimeStoreSpy()
        channels = _ChannelSpy(stop_event)
        reporter = _ReporterSpy()
        publisher = ResultPublisherService(
            settings=replace(Settings(), result_publish_fps=100),
            realtime_store=store,
            result_channels=channels,
            fall_event_reporter=reporter,
            event_pipeline=disabled_pipeline,
        )
        result = self._result(fall_state="fallen_confirmed", event_track_id=10, frame_seq=160)
        publisher._build_result = lambda camera_id: result  # type: ignore[method-assign]

        publisher._run_loop("camera_01", stop_event)  # type: ignore[attr-defined]

        self.assertEqual(disabled_pipeline.outbox.records(), [])
        self.assertEqual(channels.payloads, [result])
        self.assertEqual(store.published, [result])
        self.assertEqual(reporter.seen, [result])
        self.assertIsNone(publisher.last_error("camera_01"))

    def test_sqlite_outbox_can_be_reopened_and_claim_retry_state_persists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "event_outbox.sqlite3"
            pipeline = EventPipelineService(
                replace(Settings(), event_pipeline_enabled=True, event_worker_enabled=False, event_outbox_backend="sqlite", event_outbox_sqlite_path=str(db_path))
            )
            incident_id = pipeline.observe_result(self._result(fall_state="fallen_candidate", event_track_id=11, frame_seq=180))[0].incident_id

            reopened = SQLiteEventOutbox(db_path)
            claimed = reopened.claim_next("sqlite-smoke", 30)
            retry = reopened.mark_retry(incident_id, "synthetic_retry")

            self.assertEqual(claimed.incident_id, incident_id)
            self.assertEqual(retry.status, "retry")
            self.assertEqual(SQLiteEventOutbox(db_path).get_event(incident_id).status, "retry")

    def test_archive_enabled_writes_json_even_when_keyframes_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir) / "archive"
            pipeline = EventPipelineService(
                replace(
                    Settings(),
                    event_pipeline_enabled=True,
                    event_worker_enabled=True,
                    event_semantic_enabled=True,
                    event_archive_enabled=True,
                    event_archive_dir=str(archive_dir),
                    event_keyframe_serving_enabled=True,
                )
            )

            incident_id = pipeline.observe_result(self._result(fall_state="fallen_candidate", event_track_id=12, frame_seq=200))[0].incident_id
            processed = pipeline.process_once("archive-smoke")

            event_dir = archive_dir / "camera_01" / incident_id
            self.assertEqual(processed.status, "delivery_pending")
            self.assertTrue(processed.archive_summary["json_saved"])
            self.assertTrue((event_dir / "evidence_package.json").exists())
            self.assertTrue((event_dir / "event_semantics.json").exists())
            self.assertTrue((event_dir / "trusted_event_result.json").exists())

    def test_event_api_reads_synthetic_event_and_keyframe_summary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir) / "archive"
            pipeline = EventPipelineService(
                replace(
                    Settings(),
                    event_pipeline_enabled=True,
                    event_ring_buffer_enabled=True,
                    event_worker_enabled=True,
                    event_semantic_enabled=True,
                    event_archive_enabled=True,
                    event_archive_dir=str(archive_dir),
                    event_keyframe_serving_enabled=True,
                )
            )
            self._add_trigger_frames(pipeline, camera_id="camera_01", trigger_seq=220)
            pipeline.observe_result(self._result(fall_state="fallen_candidate", event_track_id=13, frame_seq=220))
            processed = pipeline.process_once("api-smoke")

            app = FastAPI()
            app.state.runtime = SimpleNamespace(event_pipeline=pipeline)
            app.include_router(event_api.router)
            with TestClient(app) as client:
                latest = client.get("/events/latest?camera_id=camera_01")

            self.assertEqual(latest.status_code, 200)
            self.assertNotIn(str(archive_dir), latest.text)
            event = latest.json()["event"]
            self.assertEqual(event["event"]["incident_id"], processed.incident_id)
            keyframes = event["evidence_package"]["keyframes"]
            self.assertTrue(keyframes)
            self.assertTrue({"label", "available", "missing_reason", "keyframe_url"}.issubset(keyframes[0]))
            self.assertTrue(any(item["keyframe_url"] and item["keyframe_url"].startswith("/events/") for item in keyframes))

    @staticmethod
    def _record_status_transitions(pipeline: EventPipelineService) -> list[str]:
        transitions: list[str] = []

        def wrap(name: str) -> None:
            original = getattr(pipeline.outbox, name)

            def recorded(*args, **kwargs):
                record = original(*args, **kwargs)
                if record is not None:
                    transitions.append(record.status)
                return record

            setattr(pipeline.outbox, name, recorded)

        for method in (
            "add_event",
            "claim_next",
            "mark_evidence_ready",
            "mark_semantic_ready",
            "mark_reviewed",
            "mark_delivery_pending",
        ):
            wrap(method)
        return transitions

    @staticmethod
    def _add_trigger_frames(pipeline: EventPipelineService, *, camera_id: str, trigger_seq: int) -> None:
        image = np.zeros((4, 4, 3), dtype=np.uint8)
        trigger = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        for offset_ms in (-3000, -1000, 0, 1000, 3000, 5000):
            timestamp = (trigger + timedelta(milliseconds=offset_ms)).isoformat()
            pipeline.ring_buffer.add_frame(camera_id, trigger_seq + int(offset_ms / 1000), timestamp, image)

    @staticmethod
    def _result(
        *,
        fall_state: str,
        event_track_id: int,
        frame_seq: int,
        fall_probability: float = 0.9,
        fall_evidence_score: float = 0.9,
        adl_suppression_score: float = 0.1,
    ) -> VisionResult:
        risk_level = "critical" if fall_state == "fallen_confirmed" else "high"
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-17T09:30:00+00:00",
            frame_seq=frame_seq,
            frame_width=640,
            frame_height=360,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.93,
                    bbox=[100.0, 120.0, 310.0, 340.0],
                    track_id=event_track_id,
                    fall_decision={
                        "fall_state": fall_state,
                        "risk_level": risk_level,
                        "fall_probability": fall_probability,
                        "fall_evidence_score": fall_evidence_score,
                        "adl_suppression_score": adl_suppression_score,
                    },
                    features={
                        "motion": {"tracking_stable": True, "rapid_descent": True},
                        "fall_state_sequence": ["standing", "falling", fall_state],
                    },
                    temporal={"fall_probability": fall_probability, "post_event_stillness_ms": 3000},
                )
            ],
        )
