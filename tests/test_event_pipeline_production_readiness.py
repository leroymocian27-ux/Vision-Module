from __future__ import annotations

import unittest

from scripts.check_event_pipeline_production_readiness import ROOT, evaluate, read_env


class ProductionReadinessTest(unittest.TestCase):
    def test_safe_defaults_pass(self):
        report = evaluate(read_env(ROOT / ".env.example"))
        self.assertTrue(report["ok"])
        self.assertIn("checked_keys", report)

    def test_post_missing_auth_fails(self):
        report = evaluate({"EVENT_DELIVERY_MODE": "post", "EVENT_DELIVERY_BACKEND": "sqlite", "EVENT_DELIVERY_TIMEOUT_SECONDS": "2"})
        self.assertFalse(report["ok"])

    def test_invalid_vlm_and_nonlocal_ollama_fail(self):
        self.assertFalse(evaluate({"EVENT_VLM_ENABLED": "true", "EVENT_VLM_PROVIDER": "bad"})["ok"])
        self.assertFalse(evaluate({"EVENT_VLM_ENABLED": "true", "EVENT_VLM_PROVIDER": "ollama_qwen", "EVENT_OLLAMA_BASE_URL": "http://10.0.0.2:11434", "EVENT_OLLAMA_TIMEOUT_SECONDS": "8"})["ok"])

    def test_archive_outside_logs_fails(self):
        self.assertFalse(evaluate({"EVENT_ARCHIVE_ENABLED": "true", "EVENT_ARCHIVE_DIR": "C:/temp", "EVENT_ARCHIVE_RETENTION_DAYS": "1", "EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA": "1"})["ok"])

    def test_keyframe_static_mount_is_reported(self):
        report = evaluate(
            {
                "EVENT_KEYFRAME_SERVING_ENABLED": "true",
                "EVENT_ARCHIVE_DIR": "logs/event_archive",
                "EVENT_ARCHIVE_RETENTION_DAYS": "1",
                "EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA": "1",
            },
            main_source='app.mount("/archive", StaticFiles(directory="logs/event_archive"))',
        )
        self.assertFalse(report["ok"])
        self.assertIn("keyframe_static_mount", {finding["code"] for finding in report["findings"]})

    def test_keyframe_absolute_path_exposure_is_reported(self):
        report = evaluate(
            {
                "EVENT_KEYFRAME_SERVING_ENABLED": "true",
                "EVENT_ARCHIVE_DIR": "logs/event_archive",
                "EVENT_ARCHIVE_RETENTION_DAYS": "1",
                "EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA": "1",
            },
            event_api_source="def event_detail(): return {'archive_path': 'C:/unsafe'}",
        )
        self.assertFalse(report["ok"])
        self.assertIn("keyframe_absolute_path_exposure", {finding["code"] for finding in report["findings"]})
