from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_pose_production_preflight import (
    build_preflight_report,
    check_live_status,
    check_production_parameters,
    check_pose_runtime_config,
    check_required_files,
    status_url,
    status_url_candidates,
    validate_live_status_payload,
)


class CheckPoseProductionPreflightTest(unittest.TestCase):
    def test_required_files_reports_missing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / "labels.jsonl"
            existing.write_text("{}", encoding="utf-8")

            report = check_required_files({"labels": existing, "model": root / "missing.onnx"})

        self.assertFalse(report["passed"])
        self.assertIn("required_file_missing:model", report["blockers"])

    def test_production_parameters_block_dev_like_evidence(self) -> None:
        report = check_production_parameters(
            duration_seconds=30.0,
            temporal_output_dir=Path("data/temporal_sequences_pose_dev_smoke"),
            lstm_eval_split="all",
        )

        self.assertFalse(report["passed"])
        self.assertIn("runtime_duration_below_120s", report["blockers"])
        self.assertIn("temporal_output_dir_looks_like_dev_evidence", report["blockers"])
        self.assertIn("lstm_eval_split_is_not_test", report["blockers"])

    def test_pose_runtime_config_blocks_missing_model_and_cpu_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_MODEL_PATH=models/missing_pose.pt",
                        "YOLO11_POSE_DEVICE=cpu",
                    ]
                ),
                encoding="utf-8",
            )

            report = check_pose_runtime_config(env_file=env_file, requested_device="cuda:0")

        self.assertFalse(report["passed"])
        self.assertIn("active_pose_model_file_missing", report["blockers"])
        self.assertIn("active_pose_device_is_not_cuda", report["blockers"])

    def test_pose_runtime_config_passes_active_cuda_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "pose.pt"
            model.write_text("weights", encoding="utf-8")
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        f"YOLO11_POSE_MODEL_PATH={model}",
                        "YOLO11_POSE_DEVICE=cuda:0",
                    ]
                ),
                encoding="utf-8",
            )

            report = check_pose_runtime_config(env_file=env_file, requested_device="cuda:0")

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["active_pose_model"], str(model))
        self.assertEqual(report["metrics"]["active_pose_device"], "cuda:0")

    def test_live_status_passes_when_pose_provider_and_model_match(self) -> None:
        payload = {
            "pose": {
                "pose_enabled": True,
                "pose_provider": "yolo11_legacy",
                "pose_model_path": "D:/Program/vision_service/yolo11n-pose.pt",
            }
        }

        with patch("scripts.check_pose_production_preflight.urllib.request.urlopen", return_value=FakeResponse(payload)):
            report = check_live_status(
                base_url="http://127.0.0.1:8000/api/v1",
                camera_id="camera_01",
                expected_pose_provider="yolo11_legacy",
                expected_pose_model="yolo11n-pose.pt",
            )

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])

    def test_live_status_blocks_pose_provider_and_model_mismatch(self) -> None:
        payload = {
            "pose": {
                "pose_enabled": True,
                "pose_provider": "yolo",
                "pose_model_path": "models/other_pose.pt",
            }
        }

        with patch("scripts.check_pose_production_preflight.urllib.request.urlopen", return_value=FakeResponse(payload)):
            report = check_live_status(
                base_url="http://127.0.0.1:8000/api/v1",
                camera_id="camera_01",
                expected_pose_provider="yolo11_legacy",
                expected_pose_model="yolo11n-pose.pt",
            )

        self.assertFalse(report["passed"])
        self.assertIn("live_status_pose_provider_mismatch", report["blockers"])
        self.assertIn("live_status_pose_model_path_mismatch", report["blockers"])

    def test_live_status_payload_accepts_pose_model_path_from_latest_result_pose_debug(self) -> None:
        payload = {
            "pose": {
                "pose_enabled": True,
                "pose_provider": "yolo11_legacy",
            },
            "latest_result": {
                "pose_debug": {
                    "pose_model_path": "D:/Program/vision_service/yolo11n-pose.pt",
                }
            },
        }

        report = validate_live_status_payload(
            payload,
            url="http://127.0.0.1:8000/status?camera_id=camera_01",
            expected_pose_provider="yolo11_legacy",
            expected_pose_model="yolo11n-pose.pt",
        )

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["live_pose_model_path"], "D:/Program/vision_service/yolo11n-pose.pt")
        self.assertEqual(report["warnings"], [])

    def test_live_status_payload_warns_when_model_path_is_unobservable_and_uses_expected_config(self) -> None:
        payload = {
            "pose": {
                "pose_enabled": True,
                "pose_provider": "yolo11_legacy",
                "pose_model_path": None,
            }
        }

        report = validate_live_status_payload(
            payload,
            url="http://127.0.0.1:8000/status?camera_id=camera_01",
            expected_pose_provider="yolo11_legacy",
            expected_pose_model="yolo11n-pose.pt",
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["warnings"],
            ["live_status_pose_model_path_unobservable_using_expected_config"],
        )
        self.assertEqual(report["metrics"]["live_pose_model_path"], "yolo11n-pose.pt")
        self.assertEqual(report["metrics"]["live_pose_model_path_source"], "expected_config_fallback")

    def test_status_url_candidates_include_root_fallback_for_api_v1_base(self) -> None:
        self.assertEqual(
            status_url_candidates(base_url="http://example.test/api/v1/", camera_id="cam 1"),
            [
                "http://example.test/api/v1/status?camera_id=cam+1",
                "http://example.test/status?camera_id=cam+1",
            ],
        )

    def test_build_report_blocks_cpu_only_production_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            labels = root / "labels.jsonl"
            model = root / "model.onnx"
            schema = root / "features.json"
            threshold = root / "threshold.json"
            for path in (labels, model, schema, threshold):
                path.write_text("{}", encoding="utf-8")

            with patch("scripts.check_pose_production_preflight.importlib.util.find_spec", return_value=object()):
                with patch("scripts.check_pose_production_preflight.check_cuda_device") as cuda_check:
                    cuda_check.return_value = {
                        "passed": False,
                        "blockers": ["cuda_unavailable"],
                        "warnings": [],
                        "metrics": {"requested_device": "cuda:0"},
                    }
                    report = build_preflight_report(
                        base_url="http://127.0.0.1:8000/api/v1",
                        camera_id="camera_01",
                        device="cuda:0",
                        duration_seconds=120.0,
                        labels=labels,
                        temporal_output_dir=Path("data/temporal_sequences_pose_v1"),
                        lstm_eval_split="test",
                        baseline_lstm_model=model,
                        baseline_lstm_schema=schema,
                        baseline_lstm_threshold=threshold,
                        skip_live_status=True,
                    )

        self.assertFalse(report["summary"]["passed"])
        self.assertIn({"gate": "cuda_device", "blocker": "cuda_unavailable"}, report["summary"]["blockers"])
        self.assertIn("CUDA-capable host", report["summary"]["next_action"])

    def test_status_url_uses_camera_query(self) -> None:
        self.assertEqual(
            status_url(base_url="http://example.test/api/v1/", camera_id="cam 1"),
            "http://example.test/api/v1/status?camera_id=cam+1",
        )


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")


if __name__ == "__main__":
    unittest.main()
