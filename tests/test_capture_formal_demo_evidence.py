from __future__ import annotations

import unittest

from scripts.capture_formal_demo_evidence import evaluate


class CaptureFormalDemoEvidenceTest(unittest.TestCase):
    def test_safe_synthetic_demo_passes_with_six_keyframes(self):
        incident_id = "demo-rehearsal-20260718-candidate"

        def fetch_json(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok", "source_url": "redacted-by-collector"}
            if url.endswith("/events/status"):
                return 200, {"event_pipeline_enabled": ":8011/" in url, "vlm_enabled": False}
            return 200, {
                "incident_id": incident_id,
                "archive_id": f"camera_01/{incident_id}",
                "evidence_package": {"keyframes": [{"keyframe_url": f"/events/{incident_id}/keyframes/t0"}]},
                "trusted_result": {"review_result": "demo_seed_rule_only"},
                "delivery": {"delivery_mode": "dry_run", "delivery_status": "dry_run_sent", "dry_run": True},
            }

        def fetch_binary(url: str):
            return 200, "image/jpeg"

        report = evaluate(fetch_json=fetch_json, fetch_binary=fetch_binary)

        self.assertTrue(report["ok"])
        self.assertEqual(report["keyframe_count"], 6)
        self.assertNotIn("source_url", str(report))

    def test_absolute_path_or_forbidden_delivery_field_fails(self):
        incident_id = "demo-rehearsal-20260718-candidate"

        def fetch_json(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok"}
            if url.endswith("/events/status"):
                return 200, {"event_pipeline_enabled": ":8011/" in url, "vlm_enabled": False}
            return 200, {
                "incident_id": incident_id,
                "archive_path": "C:/unsafe/archive",
                "trusted_result": {"review_result": "rule"},
                "delivery": {"delivery_mode": "dry_run", "delivery_status": "dry_run_sent", "dry_run": True, "token": "unsafe"},
            }

        report = evaluate(fetch_json=fetch_json, fetch_binary=lambda _: (200, "image/jpeg"))

        self.assertFalse(report["ok"])
        self.assertIn("public_event_payload", {check["name"] for check in report["checks"] if check["result"] == "fail"})

    def test_nested_event_incident_id_matches_public_detail_contract(self):
        incident_id = "demo-rehearsal-20260718-candidate"

        def fetch_json(url: str):
            if url.endswith("/healthz"):
                return 200, {"status": "ok"}
            if url.endswith("/events/status"):
                return 200, {"event_pipeline_enabled": ":8011/" in url, "vlm_enabled": False}
            return 200, {
                "event": {"incident_id": incident_id},
                "trusted_result": {"review_result": "demo_seed_rule_only"},
                "delivery": {"delivery_mode": "dry_run", "delivery_status": "dry_run_sent", "dry_run": True},
            }

        report = evaluate(fetch_json=fetch_json, fetch_binary=lambda _: (200, "image/jpeg"))

        self.assertTrue(report["ok"])
        self.assertEqual(report["keyframe_count"], 6)

    def test_external_or_credential_url_is_rejected_without_fetching(self):
        calls: list[str] = []

        def fetch_json(url: str):
            calls.append(url)
            return 200, {"status": "ok"}

        report = evaluate(live_url="http://name:secret@10.0.0.8:8000", fetch_json=fetch_json)

        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])
        self.assertIn("live_url", {check["name"] for check in report["checks"]})

    def test_unavailable_demo_fails_fast_without_keyframe_requests(self):
        binary_calls: list[str] = []

        def fetch_json(url: str):
            if ":8011/" in url:
                raise ConnectionError("demo is offline")
            if url.endswith("/healthz"):
                return 200, {"status": "ok"}
            return 200, {"event_pipeline_enabled": False, "vlm_enabled": False}

        report = evaluate(fetch_json=fetch_json, fetch_binary=lambda url: (binary_calls.append(url), (200, "image/jpeg"))[1])

        self.assertFalse(report["ok"])
        self.assertEqual(binary_calls, [])
        failed = {check["name"] for check in report["checks"] if check["result"] == "fail"}
        self.assertIn("public_event_payload", failed)
        self.assertIn("keyframe_t0", failed)


if __name__ == "__main__":
    unittest.main()
