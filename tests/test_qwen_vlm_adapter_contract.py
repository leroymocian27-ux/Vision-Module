from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewInput
from app.events.vlm_adapter import QwenHttpVLMReviewAdapter, VLMAdapterError, VLMAdapterSkipped, build_vlm_adapter_from_config


class QwenVLMAdapterContractTest(unittest.TestCase):
    def test_qwen_http_config_builds_thin_http_shell(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(
                Settings(),
                event_vlm_enabled=True,
                event_vlm_provider="qwen_http",
                event_vlm_http_mock_url="http://127.0.0.1:9999/qwen-review",
            )
        )

        self.assertIsInstance(adapter, QwenHttpVLMReviewAdapter)
        self.assertEqual(adapter.provider, "qwen_http")
        self.assertEqual(adapter.endpoint_url, "http://127.0.0.1:9999/qwen-review")

    def test_qwen_http_uses_configured_json_contract(self) -> None:
        calls: list[VLMReviewInput] = []

        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            del timeout_seconds
            calls.append(request)
            return {
                "schema_version": "vlm_review_result_v1",
                "support_fall_alarm": True,
                "semantic_event_type": "fall_candidate",
                "observed_process": "standing to low posture across timeline",
                "adl_likelihood": "low",
                "uncertainty": [],
                "risk_interpretation": "qwen_http mock supports rule review",
                "alarm_title": "Qwen advisory",
                "alarm_body": "Review event evidence.",
                "recommended_action": "Check live stream.",
            }

        result = QwenHttpVLMReviewAdapter(endpoint_url="http://local/qwen", transport=transport).analyze(self._semantics(), self._evidence())

        self.assertEqual(result.provider, "qwen_http")
        self.assertEqual(result.latency_ms is not None, True)
        self.assertEqual(calls[0].prompt_version, "fall_event_review_v1")
        self.assertEqual(calls[0].output_schema_version, "vlm_review_result_v1")

    def test_qwen_http_empty_endpoint_does_not_request(self) -> None:
        adapter = QwenHttpVLMReviewAdapter(endpoint_url="")

        with self.assertRaises(VLMAdapterError):
            adapter.analyze(self._semantics(), self._evidence())

    def test_qwen_http_skips_before_transport_when_no_images(self) -> None:
        called = False

        def transport(request: VLMReviewInput, timeout_seconds: float) -> dict:
            nonlocal called
            called = True
            return {}

        adapter = QwenHttpVLMReviewAdapter(endpoint_url="http://local/qwen", transport=transport)

        with self.assertRaises(VLMAdapterSkipped):
            adapter.analyze(self._semantics(), EvidencePackage(incident_id="qwen-no-image", camera_id="camera_01", trigger_timestamp="2026-07-18T09:30:00+00:00"))
        self.assertFalse(called)

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="qwen-incident",
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
            evidence={"adl_suppression_score": 0.1},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="qwen-incident",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
        )


if __name__ == "__main__":
    unittest.main()
