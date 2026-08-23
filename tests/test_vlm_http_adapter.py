from __future__ import annotations

import unittest

from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewInput
from app.events.vlm_adapter import EventVLMAdapter, InvalidVLMOutput, VLMAdapterError, VLMAdapterSkipped, VLMAdapterTimeout


class VLMHttpAdapterTest(unittest.TestCase):
    def test_http_provider_parses_json_string_response(self) -> None:
        def transport(request: VLMReviewInput, timeout_seconds: float) -> str:
            del request, timeout_seconds
            return """{
                "schema_version": "vlm_review_result_v1",
                "support_fall_alarm": true,
                "semantic_event_type": "fall_candidate",
                "observed_process": "standing to low posture",
                "adl_likelihood": "low",
                "uncertainty": [],
                "risk_interpretation": "consistent with fall-like motion",
                "alarm_title": "A very long title that should be truncated because it exceeds the adapter display safety limit for advisory titles",
                "alarm_body": "body",
                "recommended_action": "review"
            }"""

        result = EventVLMAdapter(provider="http", transport=transport).analyze(self._semantics(), self._evidence())

        self.assertEqual(result.provider, "http")
        self.assertLessEqual(len(result.alarm_title), 80)
        self.assertEqual(result.adl_likelihood, "low")

    def test_http_provider_rejects_markdown_wrapped_json(self) -> None:
        adapter = EventVLMAdapter(provider="http", transport=lambda request, timeout: "```json\n{}\n```")

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_http_provider_rejects_wrong_schema_version(self) -> None:
        adapter = EventVLMAdapter(
            provider="http",
            transport=lambda request, timeout: {
                "schema_version": "wrong.v1",
                "semantic_event_type": "fall_candidate",
            },
        )

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_http_provider_records_warning_for_missing_defaulted_fields(self) -> None:
        adapter = EventVLMAdapter(
            provider="http_mock",
            transport=lambda request, timeout: {"support_fall_alarm": True},
        )

        result = adapter.analyze(self._semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.semantic_event_type, "unknown")
        self.assertIn("schema_warning_missing_fields", result.parse_error or "")
        self.assertIn("alarm_body", result.parse_error or "")

    def test_http_provider_timeout_is_typed(self) -> None:
        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            del request, timeout_seconds
            raise TimeoutError("slow")

        with self.assertRaises(VLMAdapterTimeout):
            EventVLMAdapter(provider="http", transport=transport).analyze(self._semantics(), self._evidence())

    def test_http_provider_empty_endpoint_does_not_request(self) -> None:
        adapter = EventVLMAdapter(provider="http", endpoint_url="")

        with self.assertRaises(VLMAdapterError):
            adapter.analyze(self._semantics(), self._evidence())

    def test_http_provider_skips_before_request_when_no_images(self) -> None:
        called = False

        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            nonlocal called
            called = True
            return {}

        adapter = EventVLMAdapter(provider="http", transport=transport)

        with self.assertRaises(VLMAdapterSkipped):
            adapter.analyze(self._semantics(), EvidencePackage(incident_id="incident-http", camera_id="camera_01", trigger_timestamp="2026-07-17T09:30:00+00:00"))
        self.assertFalse(called)

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="incident-http",
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.8, "decision": "need_attention"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-http",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
        )


if __name__ == "__main__":
    unittest.main()
