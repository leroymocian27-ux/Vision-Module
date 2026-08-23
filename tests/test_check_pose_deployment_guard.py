from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_pose_deployment_guard import build_deployment_guard_report


class CheckPoseDeploymentGuardTest(unittest.TestCase):
    def test_blocks_pose_enabled_without_handoff_ready_evidence_and_brittle_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_DEVICE=cpu",
                        "POSE_WORKER_FPS=2",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=500",
                        "POSE_MAX_FRAME_AGE_MS=500",
                        "POSE_MAX_TRACKING_FRAME_DELTA=3",
                        "POSE_INFERENCE_LOCK_WAIT_MS=40",
                    ]
                ),
            )
            evidence = write_json(
                root / "evidence.json",
                {
                    "summary": {
                        "handoff_ready": False,
                        "blockers": [{"gate": "preflight", "blockers": ["cuda_unavailable"]}],
                    }
                },
            )

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["deployment_allowed"])
        self.assertIn("active_pose_device_is_not_cuda", blockers)
        self.assertIn("pose_result_ttl_ms_below_700", blockers)
        self.assertIn("pose_max_frame_age_ms_below_700", blockers)
        self.assertIn("pose_inference_lock_wait_ms_below_80", blockers)
        self.assertIn("pose_tracking_delta_above_2_requires_risk_signoff", blockers)
        self.assertIn("pose_enabled_without_handoff_ready_evidence", blockers)

    def test_allows_cuda_pose_when_evidence_is_handoff_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_DEVICE=cuda:0",
                        "YOLO11_POSE_MODEL_PATH=models/pose_candidate.pt",
                        "POSE_WORKER_FPS=3",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=800",
                        "POSE_MAX_FRAME_AGE_MS=800",
                        "POSE_MAX_TRACKING_FRAME_DELTA=2",
                        "POSE_INFERENCE_LOCK_WAIT_MS=160",
                    ]
                ),
            )
            evidence = write_json(root / "evidence.json", handoff_ready_evidence("models/pose_candidate.pt"))

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        self.assertTrue(report["summary"]["deployment_allowed"])
        self.assertEqual(report["summary"]["blockers"], [])
        self.assertEqual(report["checks"]["pose_runtime_config"]["metrics"]["active_pose_device"], "cuda:0")
        self.assertEqual(report["checks"]["evidence_package"]["metrics"]["active_pose_model"], "models/pose_candidate.pt")

    def test_blocks_when_pose_model_differs_from_handoff_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_DEVICE=cuda:0",
                        "YOLO11_POSE_MODEL_PATH=models/other_pose.pt",
                        "POSE_WORKER_FPS=3",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=800",
                        "POSE_MAX_FRAME_AGE_MS=800",
                        "POSE_MAX_TRACKING_FRAME_DELTA=2",
                        "POSE_INFERENCE_LOCK_WAIT_MS=160",
                    ]
                ),
            )
            evidence = write_json(root / "evidence.json", handoff_ready_evidence("models/pose_candidate.pt"))

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["deployment_allowed"])
        self.assertIn("pose_model_does_not_match_handoff_evidence", blockers)
        metrics = report["checks"]["evidence_package"]["metrics"]
        self.assertEqual(metrics["active_pose_model"], "models/other_pose.pt")
        self.assertEqual(metrics["evidence_pose_model"], "models/pose_candidate.pt")

    def test_blocks_when_pose_provider_differs_from_handoff_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo",
                        "YOLO_POSE_DEVICE=cuda:0",
                        "YOLO_POSE_MODEL_PATH=models/pose_candidate.pt",
                        "POSE_WORKER_FPS=3",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=800",
                        "POSE_MAX_FRAME_AGE_MS=800",
                        "POSE_MAX_TRACKING_FRAME_DELTA=2",
                        "POSE_INFERENCE_LOCK_WAIT_MS=160",
                    ]
                ),
            )
            evidence = write_json(root / "evidence.json", handoff_ready_evidence("models/pose_candidate.pt", provider="yolo11_legacy"))

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["deployment_allowed"])
        self.assertIn("pose_provider_does_not_match_handoff_evidence", blockers)
        metrics = report["checks"]["evidence_package"]["metrics"]
        self.assertEqual(metrics["active_pose_provider"], "yolo")
        self.assertEqual(metrics["evidence_pose_provider"], "yolo11_legacy")

    def test_blocks_handoff_ready_evidence_without_pose_provider_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_DEVICE=cuda:0",
                        "YOLO11_POSE_MODEL_PATH=models/pose_candidate.pt",
                        "POSE_WORKER_FPS=3",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=800",
                        "POSE_MAX_FRAME_AGE_MS=800",
                        "POSE_MAX_TRACKING_FRAME_DELTA=2",
                        "POSE_INFERENCE_LOCK_WAIT_MS=160",
                    ]
                ),
            )
            evidence = write_json(
                root / "evidence.json",
                {
                    "summary": {"handoff_ready": True, "blockers": []},
                    "checks": {
                        "model_quality": {
                            "metrics": {
                                "configured_model": "models/pose_candidate.pt",
                            }
                        }
                    },
                },
            )

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["deployment_allowed"])
        self.assertIn("pose_provider_handoff_evidence_missing", blockers)

    def test_warns_when_unready_evidence_model_differs_from_active_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=true",
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_DEVICE=cuda:0",
                        "YOLO11_POSE_MODEL_PATH=models/other_pose.pt",
                        "POSE_WORKER_FPS=3",
                        "POSE_FPS=3",
                        "POSE_RESULT_TTL_MS=800",
                        "POSE_MAX_FRAME_AGE_MS=800",
                        "POSE_MAX_TRACKING_FRAME_DELTA=2",
                        "POSE_INFERENCE_LOCK_WAIT_MS=160",
                    ]
                ),
            )
            evidence = write_json(
                root / "evidence.json",
                {
                    **handoff_ready_evidence("models/pose_candidate.pt"),
                    "summary": {
                        "handoff_ready": False,
                        "blockers": [{"gate": "preflight", "blockers": ["preflight_not_passed"]}],
                    },
                },
            )

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=evidence,
                mode="production",
            )

        warnings = flatten_warnings(report)
        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["deployment_allowed"])
        self.assertIn("pose_enabled_without_handoff_ready_evidence", blockers)
        self.assertIn("pose_model_differs_from_current_evidence", warnings)

    def test_disabled_pose_does_not_require_handoff_ready_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = write_text(
                root / ".env",
                "\n".join(
                    [
                        "ENABLE_POSE=false",
                        "POSE_PROVIDER=disabled_placeholder",
                        "POSE_RESULT_TTL_MS=500",
                        "POSE_MAX_FRAME_AGE_MS=500",
                    ]
                ),
            )

            report = build_deployment_guard_report(
                env_file=env_file,
                evidence_package_path=root / "missing_evidence.json",
                mode="production",
            )

        self.assertTrue(report["summary"]["deployment_allowed"])


def write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def handoff_ready_evidence(model_path: str, *, provider: str = "yolo11_legacy") -> dict:
    return {
        "summary": {"handoff_ready": True, "blockers": []},
        "checks": {
            "model_quality": {
                "metrics": {
                    "configured_model": model_path,
                    "candidate_model": model_path,
                }
            },
            "readiness": {
                "metrics": {
                    "evidence_consistency": {
                        "runtime_pose_provider": provider,
                        "runtime_pose_model": model_path,
                        "provider_device": "cuda:0",
                        "provider_candidates": [provider],
                        "passing_providers": [provider],
                        "provider_model_paths": {provider: model_path},
                        "configured_pose_model": model_path,
                    }
                }
            },
        },
    }


def flatten_blockers(report: dict) -> list[str]:
    result: list[str] = []
    for item in report["summary"]["blockers"]:
        result.extend(item["blockers"])
    return result


def flatten_warnings(report: dict) -> list[str]:
    result: list[str] = []
    for item in report["summary"]["warnings"]:
        result.extend(item["warnings"])
    return result


if __name__ == "__main__":
    unittest.main()
