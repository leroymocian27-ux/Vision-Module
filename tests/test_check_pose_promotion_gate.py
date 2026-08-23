from __future__ import annotations

import json
from pathlib import Path

from scripts.check_pose_promotion_gate import build_promotion_gate_report


def test_promotion_gate_passes_when_all_required_gates_pass(tmp_path: Path) -> None:
    evidence = write_json(tmp_path / "evidence.json", {"summary": {"handoff_ready": True, "blockers": [], "warnings": []}})
    deployment = write_json(
        tmp_path / "deployment.json",
        {"summary": {"deployment_allowed": True, "blockers": [], "warnings": []}},
    )
    launch = write_json(
        tmp_path / "launch.json",
        {
            "summary": {
                "launch_safety_passed": True,
                "blockers": [],
                "warnings": [
                    {
                        "script": "scripts/debug_restart_matrix.py",
                        "warnings": ["debug_pose_launch_not_production_evidence"],
                    }
                ],
            }
        },
    )

    report = build_promotion_gate_report(
        evidence_package_path=evidence,
        deployment_guard_path=deployment,
        launch_safety_path=launch,
    )

    assert report["summary"]["promotion_allowed"] is True
    assert report["summary"]["blockers"] == []
    assert report["checks"]["launch_safety"]["warnings"] == [
        "scripts/debug_restart_matrix.py:debug_pose_launch_not_production_evidence"
    ]


def test_promotion_gate_blocks_current_style_unready_evidence(tmp_path: Path) -> None:
    evidence = write_json(
        tmp_path / "evidence.json",
        {
            "summary": {
                "handoff_ready": False,
                "blockers": [
                    {"gate": "preflight", "blockers": ["preflight_not_passed", "cuda_unavailable"]},
                    {"gate": "lstm_comparison", "blockers": ["lstm_comparison_missing"]},
                ],
            }
        },
    )
    deployment = write_json(
        tmp_path / "deployment.json",
        {
            "summary": {
                "deployment_allowed": False,
                "blockers": [
                    {"gate": "evidence_package", "blockers": ["pose_enabled_without_handoff_ready_evidence"]},
                ],
            }
        },
    )
    launch = write_json(
        tmp_path / "launch.json",
        {"summary": {"launch_safety_passed": True, "blockers": [], "warnings": []}},
    )

    report = build_promotion_gate_report(
        evidence_package_path=evidence,
        deployment_guard_path=deployment,
        launch_safety_path=launch,
    )

    blockers = flatten_blockers(report)
    assert report["summary"]["promotion_allowed"] is False
    assert "evidence_package_handoff_ready_false" in blockers
    assert "preflight:preflight_not_passed" in blockers
    assert "lstm_comparison:lstm_comparison_missing" in blockers
    assert "deployment_guard_deployment_allowed_false" in blockers
    assert "evidence_package:pose_enabled_without_handoff_ready_evidence" in blockers
    assert report["checks"]["launch_safety"]["passed"] is True


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def flatten_blockers(report: dict) -> list[str]:
    result: list[str] = []
    for item in report["summary"]["blockers"]:
        result.extend(item["blockers"])
    return result
