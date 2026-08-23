from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_evidence_package_check_20260705.json"
DEFAULT_TEMPORAL_CHECK = ROOT / "evaluations" / "pose_temporal_sequences_check_20260705.json"
DEFAULT_LSTM_MANIFEST = ROOT / "data" / "temporal_v6_training" / "lstm_v6_pose_training_manifest.json"

REQUIRED_PRODUCTION_STAGES = (
    "pose_model_quality",
    "production_preflight",
    "runtime_probe",
    "provider_ab",
    "temporal_export_ur_fall",
    "temporal_export_gmdcsa24",
    "temporal_pose_check",
    "lstm_pose_manifest",
    "pose_lstm_train",
    "baseline_lstm_eval",
    "pose_lstm_eval",
    "pose_lstm_zero_pose_eval",
    "lstm_pose_comparison",
    "readiness",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether pose optimization evidence is complete enough for production handoff.")
    parser.add_argument("--preflight", default="evaluations/pose_production_preflight_20260705.json")
    parser.add_argument("--model-quality", default="evaluations/pose_model_quality_20260705.json")
    parser.add_argument("--pipeline", default="evaluations/pose_optimization_pipeline_20260705.json")
    parser.add_argument("--temporal-check", default=str(DEFAULT_TEMPORAL_CHECK))
    parser.add_argument("--lstm-manifest", default=str(DEFAULT_LSTM_MANIFEST))
    parser.add_argument("--readiness", default="evaluations/pose_optimization_readiness_20260705.json")
    parser.add_argument("--comparison", default="evaluations/pose_lstm_comparison_20260705.json")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    report = build_evidence_package_report(
        preflight_path=Path(args.preflight),
        model_quality_path=Path(args.model_quality),
        pipeline_path=Path(args.pipeline),
        temporal_check_path=Path(args.temporal_check),
        lstm_manifest_path=Path(args.lstm_manifest),
        readiness_path=Path(args.readiness),
        comparison_path=Path(args.comparison),
    )
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["handoff_ready"] else 1


def build_evidence_package_report(
    *,
    preflight_path: Path,
    pipeline_path: Path,
    readiness_path: Path,
    comparison_path: Path,
    model_quality_path: Path = Path("evaluations/pose_model_quality_20260705.json"),
    temporal_check_path: Path | None = None,
    lstm_manifest_path: Path | None = None,
) -> dict[str, Any]:
    evidence_paths = {
        "production_preflight": preflight_path,
        "pose_model_quality": model_quality_path,
        "lstm_pose_comparison": comparison_path,
        "readiness": readiness_path,
    }
    if temporal_check_path is not None:
        evidence_paths["temporal_pose_check"] = temporal_check_path
    if lstm_manifest_path is not None:
        evidence_paths["lstm_pose_manifest"] = lstm_manifest_path
    checks = {
        "preflight": check_preflight(preflight_path),
        "model_quality": check_model_quality(model_quality_path),
        "pipeline": check_pipeline(pipeline_path),
        "pipeline_evidence_links": check_pipeline_evidence_links(
            path=pipeline_path,
            evidence_paths=evidence_paths,
        ),
        "readiness": check_readiness(readiness_path),
        "lstm_comparison": check_lstm_comparison(comparison_path),
    }
    blockers = [
        {"gate": name, "blockers": check["blockers"]}
        for name, check in checks.items()
        if check["blockers"]
    ]
    warnings = [
        {"gate": name, "warnings": check["warnings"]}
        for name, check in checks.items()
        if check["warnings"]
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "handoff_ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "next_action": next_action(blockers),
        },
        "checks": checks,
    }


def check_preflight(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["preflight_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    blockers = []
    warnings = []
    if summary.get("passed") is not True:
        blockers.append("preflight_not_passed")
    blockers.extend(f"preflight:{item.get('gate')}:{item.get('blocker')}" for item in list_of_dicts(summary.get("blockers")))
    warnings.extend(f"preflight:{item.get('gate')}:{item.get('warning')}" for item in list_of_dicts(summary.get("warnings")))
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "passed": summary.get("passed"),
            "blocker_count": len(summary.get("blockers") or []),
            "next_action": summary.get("next_action"),
        },
    )


def check_model_quality(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["pose_model_quality_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    blockers = []
    warnings = []
    if summary.get("passed") is not True:
        blockers.append("pose_model_quality_not_passed")
    blockers.extend(str(item) for item in summary.get("blockers") or [])
    warnings.extend(str(item) for item in summary.get("warnings") or [])
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "passed": summary.get("passed"),
            "baseline_model": summary.get("baseline_model"),
            "candidate_model": summary.get("candidate_model"),
            "configured_model": summary.get("configured_model"),
            "baseline_pose_map50_95": summary.get("baseline_pose_map50_95"),
            "candidate_pose_map50_95": summary.get("candidate_pose_map50_95"),
            "delta_pose_map50_95": summary.get("delta_pose_map50_95"),
            "next_action": summary.get("next_action"),
        },
    )


def check_pipeline(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["pipeline_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    stages = [item for item in payload.get("stages", []) if isinstance(item, dict)]
    stage_names = [str(item.get("name")) for item in stages]
    blockers = []
    warnings = []
    if summary.get("mode") != "production":
        blockers.append("pipeline_mode_is_not_production")
    if summary.get("status") != "ok":
        blockers.append("pipeline_status_not_ok")
    if summary.get("production_ready") is not True:
        blockers.append("pipeline_production_ready_false")
    missing_stages = [name for name in REQUIRED_PRODUCTION_STAGES if name not in stage_names]
    if missing_stages:
        blockers.append("pipeline_missing_required_stages")
    failed_stages = [str(item.get("name")) for item in stages if item.get("status") == "failed"]
    if failed_stages:
        blockers.append("pipeline_has_failed_stages")
    skipped_stages = [str(item.get("name")) for item in stages if item.get("status") == "skipped"]
    if skipped_stages:
        blockers.append("pipeline_has_skipped_stages")
    missing_outputs = missing_stage_outputs(stages)
    if missing_outputs:
        blockers.append("pipeline_stage_outputs_missing")
    missing_timestamps = missing_stage_timestamps(stages)
    if missing_timestamps:
        blockers.append("pipeline_stage_timestamps_missing")
    stale_outputs = stale_stage_outputs(stages)
    if stale_outputs:
        blockers.append("pipeline_stage_outputs_stale")
    if any(text_looks_dev(str(item.get("output", ""))) for item in stages):
        warnings.append("pipeline_contains_dev_like_output_path")
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "mode": summary.get("mode"),
            "status": summary.get("status"),
            "production_ready": summary.get("production_ready"),
            "stage_count": summary.get("stage_count"),
            "completed_stage_count": summary.get("completed_stage_count"),
            "executed_stage_count": summary.get("executed_stage_count"),
            "skipped_stage_count": summary.get("skipped_stage_count"),
            "failed_stage": summary.get("failed_stage"),
            "missing_required_stages": missing_stages,
            "failed_stages": failed_stages,
            "skipped_stages": skipped_stages,
            "missing_stage_outputs": missing_outputs,
            "missing_stage_timestamps": missing_timestamps,
            "stale_stage_outputs": stale_outputs,
        },
    )


def check_pipeline_evidence_links(path: Path, evidence_paths: dict[str, Path]) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["pipeline_missing"], [], {})
    stages = [item for item in payload.get("stages", []) if isinstance(item, dict)]
    by_name = {str(item.get("name")): item for item in stages}
    blockers: list[str] = []
    linked: list[dict[str, Any]] = []
    for stage_name, evidence_path in evidence_paths.items():
        stage = by_name.get(stage_name)
        if stage is None:
            blockers.append(f"pipeline_evidence_stage_missing:{stage_name}")
            linked.append(
                {
                    "stage": stage_name,
                    "expected_evidence_path": normalize_path_for_compare(evidence_path),
                    "stage_output": None,
                    "stage_status": None,
                    "linked": False,
                }
            )
            continue
        stage_status = str(stage.get("status") or "")
        stage_output = stage.get("output")
        expected = normalize_path_for_compare(evidence_path)
        actual = normalize_path_for_compare(Path(str(stage_output))) if stage_output else ""
        is_linked = stage_status == "ok" and actual == expected
        if stage_status != "ok":
            blockers.append(f"pipeline_evidence_stage_not_ok:{stage_name}:{stage_status or 'unknown'}")
        elif actual != expected:
            blockers.append(f"pipeline_evidence_output_mismatch:{stage_name}")
        linked.append(
            {
                "stage": stage_name,
                "expected_evidence_path": expected,
                "stage_output": actual or None,
                "stage_status": stage_status or None,
                "linked": is_linked,
            }
        )
    return check_result(
        path,
        dedupe(blockers),
        [],
        {
            "linked_evidence": linked,
        },
    )


def check_readiness(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["readiness_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    checks = as_dict(payload.get("checks"))
    evidence_consistency = as_dict(checks.get("evidence_consistency"))
    evidence_consistency_metrics = as_dict(evidence_consistency.get("metrics"))
    blockers = []
    warnings = []
    if summary.get("overall_ready") is not True:
        blockers.append("readiness_overall_ready_false")
    if summary.get("production_ready") is not True:
        blockers.append("readiness_production_ready_false")
    if summary.get("evidence_scope") != "production":
        blockers.append("readiness_evidence_scope_is_not_production")
    for item in list_of_dicts(summary.get("blocking_reasons")):
        for blocker in item.get("blockers") or []:
            blockers.append(f"readiness:{item.get('gate')}:{blocker}")
    for item in list_of_dicts(summary.get("non_production_reasons")):
        for reason in item.get("reasons") or []:
            blockers.append(f"readiness_non_production:{item.get('gate')}:{reason}")
    blockers.extend(readiness_evidence_consistency_blockers(evidence_consistency_metrics))
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "overall_ready": summary.get("overall_ready"),
            "production_ready": summary.get("production_ready"),
            "evidence_scope": summary.get("evidence_scope"),
            "failed_gates": summary.get("failed_gates") or [],
            "recommendation": summary.get("recommendation"),
            "evidence_consistency": {
                "runtime_pose_provider": evidence_consistency_metrics.get("runtime_pose_provider"),
                "runtime_pose_model": evidence_consistency_metrics.get("runtime_pose_model"),
                "provider_device": evidence_consistency_metrics.get("provider_device"),
                "provider_candidates": evidence_consistency_metrics.get("provider_candidates") or [],
                "passing_providers": evidence_consistency_metrics.get("passing_providers") or [],
                "provider_model_paths": evidence_consistency_metrics.get("provider_model_paths") or {},
                "configured_pose_model": evidence_consistency_metrics.get("configured_pose_model"),
            },
        },
    )


def readiness_evidence_consistency_blockers(metrics: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    runtime_provider = str(metrics.get("runtime_pose_provider") or "").strip()
    runtime_model = str(metrics.get("runtime_pose_model") or "").strip()
    provider_device = str(metrics.get("provider_device") or "").strip()
    configured_model = str(metrics.get("configured_pose_model") or "").strip()
    provider_candidates = [str(item).strip() for item in metrics.get("provider_candidates") or [] if str(item).strip()]
    passing_providers = [str(item).strip() for item in metrics.get("passing_providers") or [] if str(item).strip()]
    provider_model_paths = as_dict(metrics.get("provider_model_paths"))

    if not runtime_provider:
        blockers.append("readiness_evidence_consistency_runtime_pose_provider_missing")
    if not runtime_model:
        blockers.append("readiness_evidence_consistency_runtime_pose_model_missing")
    if not provider_device:
        blockers.append("readiness_evidence_consistency_provider_device_missing")
    elif not provider_device.lower().startswith("cuda"):
        blockers.append("readiness_evidence_consistency_provider_device_is_not_cuda")
    if not configured_model:
        blockers.append("readiness_evidence_consistency_configured_pose_model_missing")
    if not provider_candidates:
        blockers.append("readiness_evidence_consistency_provider_candidates_missing")
    if not passing_providers:
        blockers.append("readiness_evidence_consistency_passing_providers_missing")

    if runtime_provider:
        if provider_candidates and runtime_provider not in provider_candidates:
            blockers.append("readiness_evidence_consistency_runtime_provider_not_in_provider_candidates")
        if passing_providers and runtime_provider not in passing_providers:
            blockers.append("readiness_evidence_consistency_runtime_provider_not_in_passing_providers")

    if runtime_model and configured_model and normalize_model_path(runtime_model) != normalize_model_path(configured_model):
        blockers.append("readiness_evidence_consistency_runtime_model_does_not_match_configured_model")

    if runtime_provider and configured_model:
        provider_model = str(provider_model_paths.get(runtime_provider) or "").strip()
        if not provider_model:
            blockers.append("readiness_evidence_consistency_provider_model_path_missing_for_runtime_provider")
        elif normalize_model_path(provider_model) != normalize_model_path(configured_model):
            blockers.append("readiness_evidence_consistency_provider_model_does_not_match_configured_model")

    return blockers


def check_lstm_comparison(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return check_result(path, ["lstm_comparison_missing"], [], {})
    summary = as_dict(payload.get("summary"))
    comparison = as_dict(summary.get("comparison"))
    blockers = []
    warnings = []
    if path_looks_dev(path):
        blockers.append("lstm_comparison_path_looks_like_dev_evidence")
    if comparison.get("passed") is not True:
        blockers.append("lstm_comparison_not_passed")
    blockers.extend(str(item) for item in comparison.get("blockers") or [])
    baseline = as_dict(summary.get("baseline_lstm"))
    pose = as_dict(summary.get("pose_lstm"))
    ablation = as_dict(summary.get("pose_lstm_zero_pose_ablation"))
    pose_f1 = number_or_none(pose.get("f1"))
    baseline_f1 = number_or_none(baseline.get("f1"))
    ablation_f1 = number_or_none(ablation.get("f1"))
    if pose_f1 is None or baseline_f1 is None:
        blockers.append("lstm_comparison_missing_baseline_or_pose_f1")
    elif pose_f1 <= baseline_f1:
        blockers.append("pose_lstm_not_better_than_baseline_f1")
    if ablation_f1 is None:
        blockers.append("lstm_comparison_missing_zero_pose_ablation_f1")
    elif pose_f1 is not None and pose_f1 <= ablation_f1:
        blockers.append("pose_lstm_not_better_than_zero_pose_ablation")
    return check_result(
        path,
        dedupe(blockers),
        dedupe(warnings),
        {
            "comparison_passed": comparison.get("passed"),
            "baseline_f1": baseline_f1,
            "pose_f1": pose_f1,
            "zero_pose_ablation_f1": ablation_f1,
            "false_positive_delta": comparison.get("false_positive_delta"),
            "zero_pose_ablation_false_positive_delta": comparison.get("zero_pose_ablation_false_positive_delta"),
        },
    )


def check_result(path: Path, blockers: list[str], warnings: list[str], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": metrics,
    }


def next_action(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "evidence package is complete enough for production handoff review"
    gates = [item.get("gate") for item in blockers]
    if "preflight" in gates:
        return "fix production preflight first; no downstream evidence package is credible until this passes"
    if "model_quality" in gates:
        return "fix pose model quality first; a faster but less accurate pose model is not production evidence"
    if "pipeline" in gates:
        return "rerun the full production pipeline until all required stages complete successfully"
    if "pipeline_evidence_links" in gates:
        return "rerun the production pipeline and use its exact stage output files; do not mix in stale external JSON"
    if "readiness" in gates:
        return "inspect production readiness blockers and remove any dev/local evidence from the package"
    if "lstm_comparison" in gates:
        return "rerun LSTM baseline/pose/zero-pose comparison; pose must beat both controls before handoff"
    return "resolve evidence package blockers before production handoff"


def read_json(path: Path) -> tuple[dict[str, Any], bool]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}, True
    return json.loads(resolved.read_text(encoding="utf-8")), False


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def normalize_path_for_compare(path: Path) -> str:
    return str(resolve_path(path).resolve()).replace("\\", "/").lower()


def normalize_model_path(value: str | None) -> str:
    text = str(value or "").replace("\\", "/").strip()
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text.lower()


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def path_looks_dev(path: Path) -> bool:
    return text_looks_dev(path.name)


def text_looks_dev(text: str) -> bool:
    markers = ("dev", "smoke", "local", "mock", "replay")
    normalized = str(text).replace("\\", "/").lower()
    return any(marker in normalized for marker in markers)


def missing_stage_outputs(stages: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for item in stages:
        if item.get("status") != "ok":
            continue
        output = item.get("output")
        if not output:
            missing.append({"stage": str(item.get("name")), "output": ""})
            continue
        output_path = resolve_path(Path(str(output)))
        if not output_path.exists():
            missing.append({"stage": str(item.get("name")), "output": str(output)})
    return missing


def missing_stage_timestamps(stages: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for item in stages:
        if item.get("status") != "ok":
            continue
        if parse_datetime(item.get("started_at")) is None:
            missing.append({"stage": str(item.get("name")), "field": "started_at"})
    return missing


def stale_stage_outputs(stages: list[dict[str, Any]]) -> list[dict[str, str]]:
    stale: list[dict[str, str]] = []
    for item in stages:
        if item.get("status") != "ok":
            continue
        started_at = parse_datetime(item.get("started_at"))
        output = item.get("output")
        if started_at is None or not output:
            continue
        output_path = resolve_path(Path(str(output)))
        if not output_path.exists():
            continue
        output_mtime = datetime.fromtimestamp(output_path.stat().st_mtime, tz=timezone.utc)
        if output_mtime < started_at:
            stale.append(
                {
                    "stage": str(item.get("name")),
                    "output": str(output),
                    "started_at": started_at.isoformat(),
                    "output_modified_at": output_mtime.isoformat(),
                }
            )
    return stale


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
