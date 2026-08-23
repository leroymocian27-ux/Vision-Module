from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
from app.events.vlm_adapter import DummyVLMReviewAdapter, EventVLMAdapter, HttpVLMReviewAdapter, OllamaVLMReviewAdapter, QwenHttpVLMReviewAdapter, QwenOllamaReviewAdapter, build_vlm_adapter_from_config


class VLMAdapterConfigTest(unittest.TestCase):
    def test_default_settings_do_not_build_adapter(self) -> None:
        settings = Settings()

        self.assertFalse(settings.event_vlm_enabled)
        self.assertEqual(settings.event_vlm_provider, "dummy")
        self.assertEqual(settings.event_vlm_timeout_seconds, 8.0)
        self.assertEqual(settings.event_vlm_prompt_version, "fall_event_review_v1")
        self.assertEqual(settings.event_vlm_output_schema_version, "vlm_review_result_v1")
        self.assertIsNone(build_vlm_adapter_from_config(settings))

    def test_disabled_provider_builds_noop_adapter_when_explicitly_enabled(self) -> None:
        adapter = build_vlm_adapter_from_config(replace(Settings(), event_vlm_enabled=True, event_vlm_provider="disabled"))

        self.assertIsInstance(adapter, EventVLMAdapter)
        self.assertEqual(adapter.provider, "disabled")

    def test_dummy_provider_builds_dummy_adapter(self) -> None:
        adapter = build_vlm_adapter_from_config(replace(Settings(), event_vlm_enabled=True, event_vlm_provider="dummy"))

        self.assertIsInstance(adapter, DummyVLMReviewAdapter)
        self.assertEqual(adapter.provider, "dummy")

    def test_http_provider_builds_http_adapter(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(Settings(), event_vlm_enabled=True, event_vlm_provider="http", event_vlm_http_mock_url="http://127.0.0.1:9999/vlm")
        )

        self.assertIsInstance(adapter, HttpVLMReviewAdapter)
        self.assertEqual(adapter.provider, "http")
        self.assertEqual(adapter.endpoint_url, "http://127.0.0.1:9999/vlm")

    def test_qwen_http_provider_builds_qwen_http_adapter(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(Settings(), event_vlm_enabled=True, event_vlm_provider="qwen_http", event_vlm_http_mock_url="http://127.0.0.1:9999/qwen")
        )

        self.assertIsInstance(adapter, QwenHttpVLMReviewAdapter)
        self.assertEqual(adapter.provider, "qwen_http")

    def test_ollama_provider_builds_local_adapter(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(Settings(), event_vlm_enabled=True, event_vlm_provider="ollama")
        )

        self.assertIsInstance(adapter, OllamaVLMReviewAdapter)
        self.assertEqual(adapter.provider, "ollama")
        self.assertEqual(adapter.endpoint_url, "http://127.0.0.1:11434/api/chat")

    def test_qwen_ollama_provider_builds_local_adapter(self) -> None:
        adapter = build_vlm_adapter_from_config(
            replace(Settings(), event_vlm_enabled=True, event_vlm_provider="qwen_ollama")
        )

        self.assertIsInstance(adapter, QwenOllamaReviewAdapter)
        self.assertEqual(adapter.provider, "qwen_ollama")
        self.assertEqual(adapter.endpoint_url, "http://127.0.0.1:11434/api/chat")

    def test_invalid_provider_when_disabled_falls_back_without_startup_failure(self) -> None:
        settings = replace(Settings(), event_vlm_enabled=False, event_vlm_provider="surprise")

        self.assertEqual(settings.event_vlm_provider, "dummy")
        self.assertIsNone(build_vlm_adapter_from_config(settings))


if __name__ == "__main__":
    unittest.main()
