from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.probe_pose_runtime_status import fetch_status, status_url_candidates, summarize_samples


class ProbePoseRuntimeStatusTest(unittest.TestCase):
    def test_status_url_candidates_include_root_fallback_for_api_v1_base(self) -> None:
        self.assertEqual(
            status_url_candidates(base_url="http://127.0.0.1:8000/api/v1", camera_id="camera_01"),
            [
                "http://127.0.0.1:8000/api/v1/status?camera_id=camera_01",
                "http://127.0.0.1:8000/status?camera_id=camera_01",
            ],
        )

    def test_fetch_status_falls_back_from_api_v1_to_root_status_on_404(self) -> None:
        class FakeHttpError(Exception):
            def __init__(self, code: int, body: str) -> None:
                self.code = code
                self._body = body

            def read(self) -> bytes:
                return self._body.encode("utf-8")

        calls: list[str] = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return b'{"pose":{"pose_provider":"yolo11_legacy"}}'

        def fake_urlopen(request, timeout=5.0):
            url = request.full_url
            calls.append(url)
            if url.endswith("/api/v1/status?camera_id=camera_01"):
                raise FakeHttpError(404, '{"detail":"Not Found"}')
            return FakeResponse()

        with patch("scripts.probe_pose_runtime_status.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("scripts.probe_pose_runtime_status.urllib.error.HTTPError", FakeHttpError):
                payload = fetch_status(base_url="http://127.0.0.1:8000/api/v1", camera_id="camera_01")

        self.assertEqual(payload["pose"]["pose_provider"], "yolo11_legacy")
        self.assertEqual(
            calls,
            [
                "http://127.0.0.1:8000/api/v1/status?camera_id=camera_01",
                "http://127.0.0.1:8000/status?camera_id=camera_01",
            ],
        )

    def test_summarize_samples_computes_runtime_deltas_and_pass_gate(self) -> None:
        samples = [
            self._sample(target=10, attached=7, attempts=5, successes=5, busy=1),
            self._sample(target=20, attached=15, attempts=10, successes=10, busy=1),
        ]

        report = summarize_samples(
            samples,
            profile_name="B",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
            duration_seconds=120.0,
            interval_seconds=2.0,
        )
        summary = report["summary"]

        self.assertEqual(report["probe_config"]["duration_seconds"], 120.0)
        self.assertEqual(summary["requested_duration_seconds"], 120.0)
        self.assertEqual(summary["runtime_deltas"]["pose_target_object_count"], 10)
        self.assertEqual(summary["runtime_deltas"]["pose_attached_object_count"], 8)
        self.assertEqual(summary["runtime_pose_valid_rate"], 0.8)
        self.assertEqual(summary["pose_model_path"], "models/pose_runtime.pt")
        self.assertTrue(summary["gate"]["passed"])

    def test_summarize_samples_flags_busy_and_stale_blockers(self) -> None:
        samples = [
            self._sample(target=10, attached=4, attempts=5, successes=5, busy=1, stale=0),
            self._sample(target=20, attached=7, attempts=10, successes=10, busy=8, stale=2),
        ]

        report = summarize_samples(
            samples,
            profile_name="A",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
        )
        blockers = report["summary"]["gate"]["blockers"]

        self.assertIn("pose_valid_rate_below_0.70", blockers)
        self.assertIn("busy_skip_too_high", blockers)
        self.assertIn("pose_frame_stale", blockers)
        self.assertFalse(report["summary"]["gate"]["passed"])

    def test_gate_fails_when_only_stale_blocker_is_present(self) -> None:
        samples = [
            self._sample(target=10, attached=8, attempts=5, successes=5, busy=0, stale=0),
            self._sample(target=20, attached=16, attempts=10, successes=10, busy=0, stale=1),
        ]

        report = summarize_samples(
            samples,
            profile_name="B",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
        )
        gate = report["summary"]["gate"]

        self.assertIn("pose_frame_stale", gate["blockers"])
        self.assertFalse(gate["passed"])

    def test_gate_blocks_detection_lag_but_not_local_source_eof(self) -> None:
        detection_lag = summarize_samples(
            [
                self._sample(target=10, attached=8, attempts=5, successes=5, busy=0),
                self._sample(
                    target=20,
                    attached=16,
                    attempts=10,
                    successes=10,
                    busy=0,
                    skip_reasons={"pose_frame_stale_detection_lag": 1},
                ),
            ],
            profile_name="B",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
        )
        source_eof = summarize_samples(
            [
                self._sample(target=10, attached=8, attempts=5, successes=5, busy=0),
                self._sample(
                    target=20,
                    attached=16,
                    attempts=10,
                    successes=10,
                    busy=0,
                    skip_reasons={"pose_frame_stale_source_eof": 1},
                ),
            ],
            profile_name="B",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
        )

        self.assertIn("pose_frame_stale_detection_lag", detection_lag["summary"]["gate"]["blockers"])
        self.assertFalse(detection_lag["summary"]["gate"]["passed"])
        self.assertEqual(source_eof["summary"]["gate"]["blockers"], [])
        self.assertTrue(source_eof["summary"]["gate"]["passed"])

    def test_rates_are_bounded_when_async_counters_are_slightly_inconsistent(self) -> None:
        report = summarize_samples(
            [
                self._sample(target=10, attached=10, attempts=10, successes=10, busy=0),
                self._sample(target=12, attached=13, attempts=12, successes=13, busy=0),
            ],
            profile_name="B",
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
        )
        summary = report["summary"]

        self.assertEqual(summary["runtime_pose_valid_rate"], 1.0)
        self.assertEqual(summary["runtime_inference_success_rate"], 1.0)
        self.assertIn("pose_attached_delta_exceeds_target_delta", summary["counter_consistency_warnings"])
        self.assertIn("inference_success_delta_exceeds_attempt_delta", summary["counter_consistency_warnings"])

    @staticmethod
    def _sample(
        *,
        target: int,
        attached: int,
        attempts: int,
        successes: int,
        busy: int,
        stale: int = 0,
        skip_reasons: dict | None = None,
    ) -> dict:
        if skip_reasons is None:
            skip_reasons = {"pose_frame_stale": stale} if stale else {}
        return {
            "ok": True,
            "status": {
                "pose": {
                    "pose_provider": "yolo11_legacy",
                    "pose_model_path": "models/pose_runtime.pt",
                    "pose_fps": 2.5,
                    "pose_quality_level": "valid",
                    "worker_tick_count": attempts,
                    "inference_attempt_count": attempts,
                    "inference_success_count": successes,
                    "pose_target_object_count": target,
                    "pose_attached_object_count": attached,
                    "skipped_due_to_busy": busy,
                    "skip_reasons": skip_reasons,
                },
                "latest_result": {"pose_available": attached > 0},
            },
        }


if __name__ == "__main__":
    unittest.main()
