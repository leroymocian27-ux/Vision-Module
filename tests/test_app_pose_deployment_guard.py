from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.core.config import Settings
from app.main import _enforce_pose_deployment_guard, _should_run_app_pose_deployment_guard


def test_app_pose_deployment_guard_runs_for_pose_plus_main_alerts(tmp_path: Path) -> None:
    settings = replace(
        Settings(),
        enable_pose=True,
        main_system_alert_enabled=True,
        pose_deployment_guard_enabled=True,
        pose_evidence_package=str(tmp_path / "evidence.json"),
        pose_deployment_guard_output=str(tmp_path / "guard.json"),
    )

    assert _should_run_app_pose_deployment_guard(settings)


def test_app_pose_deployment_guard_blocks_unready_handoff(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({"summary": {"handoff_ready": False, "blockers": [{"gate": "preflight", "blockers": ["x"]}]}}),
        encoding="utf-8",
    )
    output = tmp_path / "guard.json"
    settings = replace(
        Settings(),
        enable_pose=True,
        main_system_alert_enabled=True,
        pose_deployment_guard_enabled=True,
        pose_provider="yolo11_legacy",
        yolo11_pose_model_path="yolo11n-pose.pt",
        yolo11_pose_device="cuda:0",
        pose_evidence_package=str(evidence),
        pose_deployment_guard_output=str(output),
    )

    with pytest.raises(RuntimeError, match="pose deployment guard rejected app startup"):
        _enforce_pose_deployment_guard(settings)

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["summary"]["deployment_allowed"] is False
    assert written["checks"]["evidence_package"]["blockers"] == ["pose_enabled_without_handoff_ready_evidence"]


def test_app_pose_deployment_guard_allows_matching_handoff(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps(handoff_ready_evidence("yolo11_legacy", "yolo11n-pose.pt")), encoding="utf-8")
    output = tmp_path / "guard.json"
    settings = replace(
        Settings(),
        enable_pose=True,
        main_system_alert_enabled=True,
        pose_deployment_guard_enabled=True,
        pose_provider="yolo11_legacy",
        yolo11_pose_model_path="yolo11n-pose.pt",
        yolo11_pose_device="cuda:0",
        pose_worker_fps=3.0,
        pose_fps=3.0,
        pose_result_ttl_ms=800,
        pose_max_frame_age_ms=800,
        pose_max_tracking_frame_delta=2,
        pose_inference_lock_wait_ms=160,
        pose_evidence_package=str(evidence),
        pose_deployment_guard_output=str(output),
    )

    report = _enforce_pose_deployment_guard(settings)

    assert report is not None
    assert report["summary"]["deployment_allowed"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["deployment_allowed"] is True


def handoff_ready_evidence(provider: str, model_path: str) -> dict:
    return {
        "summary": {"handoff_ready": True, "blockers": []},
        "checks": {
            "model_quality": {"metrics": {"configured_model": model_path}},
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
