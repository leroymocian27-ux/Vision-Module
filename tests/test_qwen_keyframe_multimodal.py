from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import event_api
from app.core.config import Settings
from app.events.pipeline import EventPipelineService
from app.events.qwen_keyframe import QwenKeyframeAnalyzer
from app.schemas.vision_result import DetectedObject, VisionResult


class QwenKeyframeMultimodalTest(unittest.TestCase):
    def test_confirmed_event_uses_local_image_bytes_and_archives_structured_advisory(self) -> None:
        received: list[dict] = []

        def transport(payload: dict, timeout: float) -> dict:
            received.append(payload)
            return {"message": {"content": json.dumps({
                "schema_version": "qwen_keyframe_advisory.v1",
                "scene_summary": "人员处于低姿态。",
                "posture_description": "疑似侧卧。",
                "movement_description": "画面内运动较少。",
                "possible_false_positive_reasons": ["局部遮挡"],
                "care_advice": ["建议工作人员复核现场。"],
                "confidence_explanation": "依据多个事件时间槽的可见姿态。",
                "advisory_confidence": "medium",
            }, ensure_ascii=False)}}

        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=transport)
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            processed = pipeline.process_once("qwen-test")
            advisory = self._wait_for_advisory(pipeline, incident_id)

            self.assertEqual(processed.trusted_result.final_event_type, "fallen_confirmed")
            self.assertEqual(advisory.analysis_status, "completed")
            self.assertEqual(advisory.scene_summary, "人员处于低姿态。")
            self.assertEqual(advisory.image_count, 6)
            self.assertEqual(len(received), 1)
            request = received[0]
            self.assertEqual(request["model"], "qwen-vision-cn:latest")
            self.assertEqual(len(request["messages"][1]["images"]), 6)
            request_text = json.dumps(request, ensure_ascii=False)
            self.assertIn("所有描述值必须使用简体中文", request_text)
            for forbidden in ("incident_id", "track_id", "camera_id", "image_path", "keyframe_url", "archive_path", "rtsp", "token", str(Path(directory))):
                self.assertNotIn(forbidden, request_text)

            advisory_file = Path(directory) / "camera_01" / incident_id / "qwen_advisory.json"
            archived = json.loads(advisory_file.read_text(encoding="utf-8"))
            self.assertEqual(archived["analysis_status"], "completed")
            self.assertNotIn(str(Path(directory)), json.dumps(archived, ensure_ascii=False))
            self.assertNotIn("image_path", archived)
            pipeline.stop()

    def test_invalid_model_json_degrades_without_changing_trusted_result(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=lambda *_: {"message": {"content": "not-json"}})
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            processed = pipeline.process_once("qwen-invalid")
            advisory = self._wait_for_advisory(pipeline, incident_id)

            self.assertEqual(processed.trusted_result.final_event_type, "fallen_confirmed")
            self.assertEqual(advisory.analysis_status, "degraded")
            self.assertEqual(advisory.error_code, "qwen_invalid_json")
            pipeline.stop()

    def test_model_output_with_url_is_rejected_and_degraded(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=lambda *_: {"message": {"content": json.dumps({
                "schema_version": "qwen_keyframe_advisory.v1",
                "scene_summary": "查看 http://example.invalid/private。",
                "posture_description": "躺卧。",
                "movement_description": "低运动。",
                "possible_false_positive_reasons": [],
                "care_advice": ["复核。"],
                "confidence_explanation": "关键帧可见。",
                "advisory_confidence": "low",
            }, ensure_ascii=False)}})
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            pipeline.process_once("qwen-url")
            advisory = self._wait_for_advisory(pipeline, incident_id)
            self.assertEqual(advisory.analysis_status, "degraded")
            self.assertEqual(advisory.error_code, "qwen_invalid_json")
            pipeline.stop()

    def test_english_model_description_is_rejected_and_never_published(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=lambda *_: {"message": {"content": json.dumps({
                "schema_version": "qwen_keyframe_advisory.v1",
                "scene_summary": "A person is kneeling on a mat.",
                "posture_description": "Kneeling posture.",
                "movement_description": "Controlled movement.",
                "possible_false_positive_reasons": ["Intentional exercise."],
                "care_advice": [],
                "confidence_explanation": "The sequence is stable.",
                "advisory_confidence": "high",
            })}})
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            pipeline.process_once("qwen-english")
            advisory = self._wait_for_advisory(pipeline, incident_id)
            self.assertEqual(advisory.analysis_status, "degraded")
            self.assertEqual(advisory.error_code, "qwen_non_chinese_output")
            self.assertIsNone(advisory.scene_summary)
            pipeline.stop()

    def test_candidate_event_does_not_send_images_by_default(self) -> None:
        calls: list[dict] = []
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=lambda payload, _: calls.append(payload) or {})
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_candidate"))[0].incident_id
            pipeline.process_once("qwen-candidate")
            time.sleep(0.1)
            record = pipeline.outbox.get_event(incident_id)
            self.assertIsNone(record.qwen_advisory)
            self.assertEqual(calls, [])
            pipeline.stop()

    def test_candidate_upgrade_to_confirmed_requeues_and_triggers_qwen(self) -> None:
        calls: list[dict] = []

        def transport(payload: dict, _: float) -> dict:
            calls.append(payload)
            return {"message": {"content": json.dumps({
                "schema_version": "qwen_keyframe_advisory.v1",
                "scene_summary": "低姿态。",
                "posture_description": "躺卧。",
                "movement_description": "低运动。",
                "possible_false_positive_reasons": [],
                "care_advice": ["复核。"],
                "confidence_explanation": "关键帧可见。",
                "advisory_confidence": "medium",
            }, ensure_ascii=False)}}

        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=transport)
            self._add_frames(pipeline)
            candidate_id = pipeline.observe_result(self._result("fallen_candidate"))[0].incident_id
            pipeline.process_once("candidate-first")
            self.assertEqual(pipeline.outbox.get_event(candidate_id).status, "delivery_pending")

            confirmed_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            upgraded = pipeline.outbox.get_event(confirmed_id)
            self.assertEqual(confirmed_id, candidate_id)
            self.assertEqual(upgraded.status, "pending")
            self.assertIsNone(upgraded.qwen_advisory)

            pipeline.process_once("confirmed-upgrade")
            advisory = self._wait_for_advisory(pipeline, confirmed_id)
            self.assertEqual(advisory.analysis_status, "completed")
            self.assertEqual(len(calls), 1)
            pipeline.stop()

    def test_public_event_payload_exposes_result_not_archive_path(self) -> None:
        with TemporaryDirectory() as directory:
            pipeline = self._pipeline(directory, transport=lambda *_: {"message": {"content": json.dumps({
                "schema_version": "qwen_keyframe_advisory.v1",
                "scene_summary": "低姿态。",
                "posture_description": "躺卧。",
                "movement_description": "低运动。",
                "possible_false_positive_reasons": [],
                "care_advice": ["复核。"],
                "confidence_explanation": "关键帧可见。",
                "advisory_confidence": "high",
            }, ensure_ascii=False)}})
            self._add_frames(pipeline)
            incident_id = pipeline.observe_result(self._result("fallen_confirmed"))[0].incident_id
            pipeline.process_once("qwen-api")
            self._wait_for_advisory(pipeline, incident_id)
            app = FastAPI()
            app.state.runtime = type("Runtime", (), {"event_pipeline": pipeline, "settings": pipeline.settings})()
            app.include_router(event_api.router)
            with TestClient(app) as client:
                response = client.get(f"/events/{incident_id}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["qwen_advisory"]["analysis_status"], "completed")
            self.assertNotIn(str(Path(directory)), response.text)
            pipeline.stop()

    def test_non_local_endpoint_is_rejected_by_startup_safety_gate(self) -> None:
        settings = replace(
            Settings(),
            event_pipeline_enabled=True,
            event_archive_enabled=True,
            event_archive_save_keyframes=True,
            event_archive_save_json=True,
            event_qwen_keyframe_analysis_enabled=True,
            event_qwen_keyframe_endpoint="http://10.0.0.8:11434/api/chat",
            qwen_media_input_enabled=True,
            qwen_media_privacy_approved=True,
        )
        self.assertIn("EVENT_QWEN_KEYFRAME_ENDPOINT must use localhost", settings.startup_safety_errors())

    def _pipeline(self, directory: str, *, transport) -> EventPipelineService:
        settings = replace(
            Settings(),
            event_pipeline_enabled=True,
            event_ring_buffer_enabled=True,
            event_worker_enabled=False,
            event_semantic_enabled=True,
            event_archive_enabled=True,
            event_archive_dir=directory,
            event_archive_save_keyframes=True,
            event_archive_save_json=True,
            event_qwen_keyframe_analysis_enabled=True,
            event_qwen_keyframe_timeout_seconds=1,
            qwen_media_input_enabled=True,
            qwen_media_privacy_approved=True,
        )
        analyzer = QwenKeyframeAnalyzer(
            endpoint_url=settings.event_qwen_keyframe_endpoint,
            model_name=settings.event_qwen_keyframe_model,
            timeout_seconds=1,
            transport=transport,
        )
        return EventPipelineService(settings, qwen_keyframe_analyzer=analyzer)

    @staticmethod
    def _add_frames(pipeline: EventPipelineService) -> None:
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        trigger = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        for sequence, offset in enumerate((-3000, -1000, 0, 1000, 3000, 5000), start=1):
            pipeline.ring_buffer.add_frame("camera_01", sequence, (trigger + timedelta(milliseconds=offset)).isoformat(), image)

    @staticmethod
    def _result(fall_state: str) -> VisionResult:
        return VisionResult(
            camera_id="camera_01",
            timestamp="2026-07-19T12:00:00+00:00",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            objects=[DetectedObject(
                label="person",
                confidence=0.9,
                bbox=[100, 100, 300, 300],
                track_id=17,
                fall_decision={
                    "fall_state": fall_state,
                    "risk_level": "critical" if fall_state == "fallen_confirmed" else "high",
                    "fall_probability": 0.95,
                    "fall_evidence_score": 0.9,
                    "adl_suppression_score": 0.1,
                },
                features={"motion": {"rapid_descent": True}},
                temporal={"fall_probability": 0.95},
            )],
        )

    @staticmethod
    def _wait_for_advisory(pipeline: EventPipelineService, incident_id: str):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            record = pipeline.outbox.get_event(incident_id)
            if record and record.qwen_advisory and record.qwen_advisory.analysis_status not in {"pending", "processing"}:
                return record.qwen_advisory
            time.sleep(0.02)
        raise AssertionError("Qwen keyframe worker did not finish")
