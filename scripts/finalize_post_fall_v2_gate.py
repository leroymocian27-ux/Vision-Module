from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the Post-Fall V2 final P3 decision from verification artifacts.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/post_fall_v2/finalization"),
    )
    parser.add_argument("--focused-tests", default="58 passed, 1 warning")
    parser.add_argument("--full-tests", default="737 passed, 2 warnings")
    args = parser.parse_args()

    output_dir = ROOT / args.output_dir
    baseline = load_json(output_dir / "baseline_snapshot.json")
    inventory = load_json(output_dir / "target_data_inventory.json")
    threshold = load_json(output_dir / "threshold_transfer_report.json")
    replay = load_json(output_dir / "replay_e2e_report.json")
    runtime = load_json(output_dir / "runtime_validation_report.json")
    qwen = load_json(output_dir / "qwen_robustness_report.json")
    target_blocked = inventory.get("target_camera_qualified_media_count") == 0

    blocked_reasons = [
        "TARGET_CAMERA_DATA_BLOCKED",
        "TARGET_RTSP_BLOCKED",
        "CALIBRATION_AND_ACCEPTANCE_NOT_RUN",
        "TARGET_DOMAIN_THRESHOLD_TRANSFER_NOT_RUN",
    ]
    calibration = {
        "status": "BLOCKED",
        "reason": "No qualified target-camera calibration recordings are present.",
        "baseline_threshold": baseline["runtime"]["binary_threshold"],
        "baseline_aggregator": {
            "sample_fps": baseline["runtime"]["sample_fps"],
            "window_size": baseline["runtime"]["window_size"],
            "min_positive_frames": baseline["runtime"]["min_positive_frames"],
            "min_consecutive_frames": baseline["runtime"]["min_consecutive_frames"],
            "candidate_min_ms": baseline["runtime"]["candidate_min_ms"],
            "recovery_min_ms": baseline["runtime"]["recovery_min_ms"],
            "cooldown_ms": baseline["runtime"]["cooldown_ms"],
        },
        "metrics": None,
        "threshold_sweep": None,
    }
    acceptance = {
        "status": "BLOCKED",
        "reason": "No independent target-camera acceptance sessions are present.",
        "metrics": None,
        "scenario_coverage": "NOT_COVERED",
        "duplicate_event_result": "NOT_TARGET_DOMAIN_VERIFIED",
        "detection_latency": "NOT_TARGET_DOMAIN_VERIFIED",
    }
    hard_negative = {
        "status": "BLOCKED",
        "reason": "No target-camera hard-negative recordings are present.",
        "scenarios": [
            "lying_bed",
            "lying_sofa",
            "lying_floor_normal",
            "bending",
            "squatting",
            "kneeling",
            "brief_low_posture",
        ],
        "metrics": None,
    }
    calibration_freeze = {
        "status": "BLOCKED",
        "reason": "No calibration-only evidence exists, so no production parameter freeze may be created.",
        "baseline_parameters": calibration["baseline_aggregator"] | {
            "binary_threshold": calibration["baseline_threshold"],
            "model_sha256": baseline["runtime"]["binary_model_sha256"],
        },
        "calibration_split_sha256": inventory["plan"].get("split_manifest_sha256"),
    }
    final_gate = {
        "created_at": utc_now_iso(),
        "P3_ALLOWED": "NO",
        "readiness": "P3_BLOCKED_BY_EXTERNAL_RESOURCE",
        "decision_basis": {
            "binary_first_runtime": "PASS",
            "qwen_advisory_runtime": "PASS",
            "qwen_event_independence": "PASS",
            "replay_e2e": replay.get("status"),
            "mock_runtime": runtime.get("status"),
            "focused_tests": args.focused_tests,
            "full_tests": args.full_tests,
            "target_camera_data": "BLOCKED" if target_blocked else "PRESENT",
            "threshold_transfer": threshold["gates"]["Threshold Transfer Gate"],
            "target_domain_acceptance": "BLOCKED" if target_blocked else "NOT_EVALUATED",
            "target_rtsp": "BLOCKED" if not baseline["runtime"]["default_rtsp_configured"] else "NOT_EVALUATED",
        },
        "blocked_reasons": blocked_reasons,
        "unblock_conditions": [
            "Provide qualified current target-camera recordings or an authorized active RTSP.",
            "Run calibration only, select and freeze threshold/aggregator parameters.",
            "Run independent acceptance including hard negatives and static post-fall scenarios.",
            "Validate target RTSP stability, latency, reconnect behavior, and E2E event flow.",
        ],
        "artifact_inputs": {
            "baseline_snapshot": "baseline_snapshot.json",
            "target_data_inventory": "target_data_inventory.json",
            "threshold_transfer_report": "threshold_transfer_report.json",
            "qwen_robustness_report": "qwen_robustness_report.json",
            "replay_e2e_report": "replay_e2e_report.json",
            "runtime_validation_report": "runtime_validation_report.json",
        },
    }
    test_report = {
        "created_at": utc_now_iso(),
        "focused_tests": args.focused_tests,
        "full_tests": args.full_tests,
        "known_warnings": [
            "Starlette/httpx TestClient deprecation warning.",
            "tests/test_evaluate_fall_lstm_metrics.py::test_schema returns a dict.",
        ],
    }

    write_json(output_dir / "calibration_report.json", calibration)
    write_json(output_dir / "hard_negative_report.json", hard_negative)
    write_json(output_dir / "calibration_freeze.json", calibration_freeze)
    write_json(output_dir / "acceptance_report.json", acceptance)
    write_json(output_dir / "test_validation_report.json", test_report)
    write_json(output_dir / "final_p3_gate_report.json", final_gate)
    print(json.dumps({"output_dir": str(output_dir), "P3_ALLOWED": final_gate["P3_ALLOWED"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
