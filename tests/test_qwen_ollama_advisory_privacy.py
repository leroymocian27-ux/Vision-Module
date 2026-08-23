from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm_adapter import OllamaQwenVLMReviewAdapter, VLMAdapterError


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"content": json.dumps({
            "schema_version": "ollama_qwen_advisory.v1",
            "scene_summary": "Structured event indicates low posture after descent.",
            "possible_false_positive_reason": "No image was reviewed; sitting remains possible.",
            "care_advice": "Inspect live video and confirm onsite.",
            "confidence_explanation": "Based only on structured evidence.",
            "advisory_confidence": 0.42,
        })}}


class QwenOllamaAdvisoryPrivacyTest(unittest.TestCase):
    def test_local_request_is_structured_only_and_advisory_only(self) -> None:
        calls = []

        def fake_post(url, json, timeout):
            calls.append((url, json, timeout))
            return _Response()

        adapter = OllamaQwenVLMReviewAdapter(
            base_url="http://127.0.0.1:11434",
            model="qwen-vision-cn:latest",
            timeout_seconds=8,
        )
        with patch("app.events.vlm_adapter.requests.post", fake_post):
            result = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(self._confirmed(), self._evidence())

        request_text = json.dumps(calls[0][1], ensure_ascii=False)
        self.assertEqual(calls[0][0], "http://127.0.0.1:11434/api/chat")
        self.assertFalse(calls[0][1]["stream"])
        self.assertEqual(calls[0][1]["format"], "json")
        for forbidden in (
            "keyframes",
            "image_path",
            "archive_path",
            "snapshot_url",
            "incident_id",
            "track_id",
            "camera_id",
            "secret-incident",
            "secret-track",
            "camera_01",
            "C:\\",
            "/tmp",
            "base64",
        ):
            self.assertNotIn(forbidden, request_text)
        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertEqual(result.final_risk_level, "critical")
        self.assertEqual(result.vlm_provider, "ollama_qwen")
        self.assertEqual(result.care_advice, "Inspect live video and confirm onsite.")

    def test_non_localhost_is_rejected_before_http(self) -> None:
        adapter = OllamaQwenVLMReviewAdapter(base_url="http://10.0.0.8:11434", model="qwen-vision-cn:latest", timeout_seconds=8)
        with self.assertRaises(VLMAdapterError):
            adapter.analyze(self._candidate(), self._evidence())

    @staticmethod
    def _confirmed() -> EventSemantics:
        return EventSemantics(
            incident_id="secret-incident",
            actor={"track_id": "secret-track", "camera_id": "camera_01"},
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.95},
        )

    @staticmethod
    def _candidate() -> EventSemantics:
        return EventSemantics(incident_id="secret-incident", risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.8})

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(incident_id="secret-incident", camera_id="camera_01", track_id=7, trigger_timestamp="2026-07-18T00:00:00+00:00", keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="C:/private/t0.jpg")])
