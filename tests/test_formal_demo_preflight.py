from __future__ import annotations

import unittest

from scripts.check_formal_demo_preflight import evaluate


class FormalDemoPreflightTest(unittest.TestCase):
    def test_live_only_safe_boundary_passes(self):
        def fetch(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok", "source_url": "must_not_be_reported"}
            return 200, {"event_pipeline_enabled": False, "vlm_enabled": False, "token": "must_not_be_reported"}

        report = evaluate(fetch_json=fetch)

        self.assertTrue(report["ok"])
        self.assertEqual(report["checked_targets"], ["live"])
        self.assertTrue(report["safety_boundary"]["sensitive_response_fields_recorded"] is False)
        self.assertNotIn("source_url", str(report))
        self.assertNotIn("must_not_be_reported", str(report))

    def test_dual_instance_requires_enabled_demo_and_disabled_vlm(self):
        def fetch(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok"}
            if ":8011/" in url:
                return 200, {"event_pipeline_enabled": True, "vlm_enabled": False}
            return 200, {"event_pipeline_enabled": False, "vlm_enabled": False}

        self.assertTrue(evaluate(demo_url="http://127.0.0.1:8011", fetch_json=fetch)["ok"])

    def test_enabled_live_pipeline_or_vlm_fails(self):
        def fetch(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok"}
            return 200, {"event_pipeline_enabled": True, "vlm_enabled": True}

        report = evaluate(fetch_json=fetch)

        self.assertFalse(report["ok"])
        self.assertEqual({item["code"] for item in report["findings"] if item["level"] == "fail"}, {"live_event_pipeline", "live_vlm"})

    def test_non_loopback_or_credential_url_is_rejected_without_fetching(self):
        calls: list[str] = []

        def fetch(url: str):
            calls.append(url)
            return 200, {"status": "ok"}

        report = evaluate(live_url="http://user:secret@10.0.0.2:8000", fetch_json=fetch)

        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])
        self.assertIn("live_url", {item["code"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
