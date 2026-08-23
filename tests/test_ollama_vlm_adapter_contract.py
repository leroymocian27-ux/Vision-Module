from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm_adapter import (
    OllamaVLMReviewAdapter,
    QwenOllamaReviewAdapter,
    VLMAdapterError,
    VLMAdapterTimeout,
    build_vlm_adapter_from_config,
)


class OllamaVLMAdapterContractTest(unittest.TestCase):
    def test_disabled_settings_do_not_build_ollama_adapter(self) -> None:
        settings = replace(Settings(), event_vlm_enabled=False, event_vlm_provider="qwen_ollama")

        self.assertEqual(settings.event_vlm_provider, "qwen_ollama")
        self.assertIsNone(build_vlm_adapter_from_config(settings))

    def test_ollama_provider_builds_only_when_enabled(self) -> None:
        adapter = build_vlm_adapter_from_config(replace(Settings(), event_vlm_enabled=True, event_vlm_provider="ollama"))

        self.assertIsInstance(adapter, OllamaVLMReviewAdapter)
        self.assertEqual(adapter.provider, "ollama")
        self.assertEqual(adapter.endpoint_url, "http://127.0.0.1:11434/api/chat")

    def test_qwen_ollama_provider_uses_configured_model(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(
                Settings(),
                event_vlm_enabled=True,
                event_vlm_provider="qwen_ollama",
                event_vlm_ollama_model="custom-qwen:latest",
            )
        )

        self.assertIsInstance(adapter, QwenOllamaReviewAdapter)
        self.assertEqual(adapter.provider, "qwen_ollama")
        self.assertEqual(adapter.model, "custom-qwen:latest")

    def test_empty_endpoint_fails_before_request(self) -> None:
        adapter = OllamaVLMReviewAdapter(provider="ollama", endpoint_url="", model="qwen-vision-cn:latest", timeout_seconds=1)

        with self.assertRaises(VLMAdapterError):
            adapter.analyze(self._semantics(), self._evidence())

    def test_connection_error_maps_to_adapter_error(self) -> None:
        def transport(payload, timeout_seconds):
            del payload, timeout_seconds
            raise ConnectionError("refused")

        adapter = OllamaVLMReviewAdapter(provider="ollama", endpoint_url="http://127.0.0.1:11434/api/chat", model="qwen-vision-cn:latest", timeout_seconds=1, transport=transport)

        with self.assertRaises(VLMAdapterError):
            adapter.analyze(self._semantics(), self._evidence())

    def test_timeout_is_typed(self) -> None:
        def transport(payload, timeout_seconds):
            del payload, timeout_seconds
            raise TimeoutError("slow")

        adapter = QwenOllamaReviewAdapter(endpoint_url="http://127.0.0.1:11434/api/chat", model="qwen-vision-cn:latest", timeout_seconds=1, transport=transport)

        with self.assertRaises(VLMAdapterTimeout):
            adapter.analyze(self._semantics(), self._evidence())

    def test_valid_ollama_json_returns_vlm_result(self) -> None:
        adapter = QwenOllamaReviewAdapter(
            endpoint_url="http://127.0.0.1:11434/api/chat",
            model="qwen-vision-cn:latest",
            timeout_seconds=1,
            transport=lambda payload, timeout: {
                "message": {
                    "content": """{
                        "schema_version": "vlm_review_result_v1",
                        "support_fall_alarm": true,
                        "semantic_event_type": "fall_candidate",
                        "observed_process": "structured descent evidence only",
                        "adl_likelihood": "low",
                        "uncertainty": ["text_only_no_images"],
                        "risk_interpretation": "structured signals are consistent with fall review",
                        "alarm_title": "Local advisory review",
                        "alarm_body": "Review live stream and onsite status.",
                        "recommended_action": "Check live stream and confirm onsite."
                    }"""
                }
            },
        )

        result = adapter.analyze(self._semantics(), self._evidence())

        self.assertEqual(result.provider, "qwen_ollama")
        self.assertEqual(result.adl_likelihood, "low")
        self.assertIn("text_only_no_images", result.uncertainty)
        self.assertIsNotNone(result.latency_ms)

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="ollama-contract",
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="ollama-contract",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            fall_probability=0.82,
            fall_evidence_score=0.86,
            adl_suppression_score=0.1,
        )


if __name__ == "__main__":
    unittest.main()
