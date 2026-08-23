from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


DEFAULT_RUNTIME_PROFILE = ROOT / "evaluations" / "pose_runtime_profile_B_20260705.json"
DEFAULT_POSE_MODEL_QUALITY = ROOT / "evaluations" / "pose_model_quality_20260705.json"
DEFAULT_PROVIDER_AB = ROOT / "evaluations" / "pose_provider_ab_20260705.json"
DEFAULT_TEMPORAL_CHECK = ROOT / "evaluations" / "pose_temporal_sequences_check_20260705.json"
DEFAULT_LSTM_MANIFEST = ROOT / "data" / "temporal_v6_training" / "lstm_v6_pose_training_manifest.json"
DEFAULT_LSTM_COMPARISON = ROOT / "evaluations" / "pose_lstm_comparison_20260705.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_optimization_readiness_20260705.json"
MIN_PRODUCTION_RUNTIME_SECONDS = 120.0
MIN_PRODUCTION_RUNTIME_OK_SAMPLES = 30
MIN_PROVIDER_SAMPLED_FRAMES = 120
MIN_PROVIDER_INFERENCE_ATTEMPTS = 30
MAX_PROVIDER_AVG_LATENCY_MS = 250.0
MIN_PROVIDER_AVG_SKELETON_CONFIDENCE = 0.50
MIN_PRODUCTION_TEMPORAL_ROWS = 1000
MIN_PRODUCTION_TEMPORAL_POSE_ROWS = 100
REQUIRED_PRODUCTION_TEMPORAL_DATASETS = ("ur_fall", "gmdcsa24")
REQUIRED_PRODUCTION_TEMPORAL_LABELS = ("fall", "non_fall")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check production readiness gates for the pose optimization plan.")
    parser.add_argument("--runtime-profile", default=str(DEFAULT_RUNTIME_PROFILE))
    parser.add_argument("--pose-model-quality", default=str(DEFAULT_POSE_MODEL_QUALITY))
    parser.add_argument("--provider-ab", default=str(DEFAULT_PROVIDER_AB))
    parser.add_argument("--temporal-check", default=str(DEFAULT_TEMPORAL_CHECK))
    parser.add_argument("--lstm-manifest", default=str(DEFAULT_LSTM_MANIFEST))
    parser.add_argument("--lstm-comparison", default=str(DEFAULT_LSTM_COMPARISON))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--allow-cpu-provider",
        action="store_true",
        help="Allow provider A/B files that appear to be CPU/dev smoke outputs. Production should not use this.",
    )
    parser.add_argument(
        "--allow-replay-runtime",
        action="store_true",
        help="Allow replay_pose_runtime_profiles.py output as a runtime gate. Production should not use this.",
    )
    args = parser.parse_args()

    report = build_readiness_report(
        runtime_profile=Path(args.runtime_profile),
        pose_model_quality=Path(args.pose_model_quality),
        provider_ab=Path(args.provider_ab),
        temporal_check=Path(args.temporal_check),
        lstm_manifest=Path(args.lstm_manifest),
        lstm_comparison=Path(args.lstm_comparison),
        allow_cpu_provider=args.allow_cpu_provider,
        allow_replay_runtime=args.allow_replay_runtime,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["overall_ready"] else 1


def build_readiness_report(
    *,
    runtime_profile: Path,
    provider_ab: Path,
    temporal_check: Path,
    lstm_manifest: Path,
    lstm_comparison: Path = DEFAULT_LSTM_COMPARISON,
    pose_model_quality: Path = DEFAULT_POSE_MODEL_QUALITY,
    allow_cpu_provider: bool = False,
    allow_replay_runtime: bool = False,
) -> dict[str, Any]:
    checks = {
        "runtime": check_runtime_profile(runtime_profile, allow_replay_runtime=allow_replay_runtime),
        "model_quality": check_pose_model_quality(pose_model_quality),
        "provider": check_provider_ab(provider_ab, allow_cpu_provider=allow_cpu_provider),
        "temporal_data": check_temporal_pose_data(temporal_check),
        "lstm_manifest": check_lstm_manifest(lstm_manifest),
        "lstm_comparison": check_lstm_comparison(lstm_comparison),
    }
    checks["evidence_consistency"] = check_evidence_consistency(checks)
    blocking = [
        {"gate": name, "blockers": check["blockers"]}
        for name, check in checks.items()
        if not check["passed"]
    ]
    non_production = [
        {"gate": name, "reasons": check.get("non_production_reasons", [])}
        for name, check in checks.items()
        if check.get("passed") and not check.get("production_evidence", True)
    ]
    overall_ready = not blocking
    production_ready = overall_ready and not non_production
    summary = {
        "overall_ready": overall_ready,
        "production_ready": production_ready,
        "evidence_scope": "production" if production_ready else "development",
        "passed_gates": [name for name, check in checks.items() if check["passed"]],
        "failed_gates": [name for name, check in checks.items() if not check["passed"]],
        "blocking_reasons": blocking,
        "non_production_reasons": non_production,
        "recommendation": recommendation(blocking, non_production),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "checks": checks,
    }


def check_runtime_profile(path: Path, *, allow_replay_runtime: bool = False) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(path, ["runtime_profile_missing"], "run probe_pose_runtime_status.py against the live B profile")
    if isinstance(payload.get("profiles"), list):
        return check_runtime_replay_profile(path, payload, allow_replay_runtime=allow_replay_runtime)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    gate = summary.get("gate") if isinstance(summary.get("gate"), dict) else {}
    blockers = list(gate.get("blockers") or [])
    if int(summary.get("ok_samples") or 0) <= 0:
        blockers.append("runtime_status_unreachable")
    if float(summary.get("runtime_pose_valid_rate") or 0.0) < 0.70:
        blockers.append("runtime_pose_valid_rate_below_0.70")
    if float(summary.get("latest_result_pose_available_ratio") or 0.0) < 0.60:
        blockers.append("latest_result_pose_available_ratio_below_0.60")
    blockers = dedupe(blockers)
    non_production_reasons = []
    if path_looks_dev(path):
        non_production_reasons.append("runtime_profile_looks_like_dev_or_local_evidence")
    if runtime_profile_looks_bcpu(path, summary):
        non_production_reasons.append("runtime_profile_is_bcpu_dev_profile")
    probe_config = payload.get("probe_config") if isinstance(payload.get("probe_config"), dict) else {}
    requested_duration = number_or_none(summary.get("requested_duration_seconds"))
    if requested_duration is None:
        requested_duration = number_or_none(probe_config.get("duration_seconds"))
    if requested_duration is None:
        non_production_reasons.append("runtime_probe_duration_metadata_missing")
    elif requested_duration < MIN_PRODUCTION_RUNTIME_SECONDS:
        non_production_reasons.append("runtime_probe_duration_below_120s")
    if int(summary.get("ok_samples") or 0) < MIN_PRODUCTION_RUNTIME_OK_SAMPLES:
        non_production_reasons.append("runtime_probe_ok_samples_below_30")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "production_evidence": not non_production_reasons,
        "non_production_reasons": non_production_reasons,
        "metrics": {
            "profile_name": summary.get("profile_name"),
            "ok_samples": summary.get("ok_samples"),
            "requested_duration_seconds": requested_duration,
            "runtime_pose_valid_rate": summary.get("runtime_pose_valid_rate"),
            "latest_result_pose_available_ratio": summary.get("latest_result_pose_available_ratio"),
            "runtime_inference_success_rate": summary.get("runtime_inference_success_rate"),
            "skip_reason_delta": summary.get("skip_reason_delta") or {},
            "pose_provider": summary.get("pose_provider"),
            "pose_model_path": summary.get("pose_model_path"),
        },
        "next_action": "fix live runtime gate before provider/model promotion" if blockers else "runtime gate passed",
    }


def check_runtime_replay_profile(
    path: Path,
    payload: dict[str, Any],
    *,
    allow_replay_runtime: bool,
) -> dict[str, Any]:
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
    preferred = None
    for item in profiles:
        if isinstance(item, dict) and item.get("profile_name") == "B":
            preferred = item
            break
    if preferred is None:
        preferred = next((item for item in profiles if isinstance(item, dict)), {})
    summary = preferred if isinstance(preferred, dict) else {}
    gate = summary.get("gate") if isinstance(summary.get("gate"), dict) else {}
    blockers = list(gate.get("blockers") or [])
    if not allow_replay_runtime:
        blockers.append("runtime_profile_is_replay_dev_evidence")
    if int(summary.get("published_frames") or 0) <= 0:
        blockers.append("runtime_replay_no_published_frames")
    if float(summary.get("pose_valid_rate") or 0.0) < 0.70:
        blockers.append("runtime_pose_valid_rate_below_0.70")
    if float(summary.get("published_pose_available_ratio") or 0.0) < 0.60:
        blockers.append("latest_result_pose_available_ratio_below_0.60")
    blockers = dedupe(blockers)
    non_production_reasons = ["runtime_profile_is_replay_dev_evidence"]
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "production_evidence": False,
        "non_production_reasons": non_production_reasons,
        "metrics": {
            "profile_name": summary.get("profile_name"),
            "evidence_source": "replay",
            "published_frames": summary.get("published_frames"),
            "runtime_pose_valid_rate": summary.get("pose_valid_rate"),
            "latest_result_pose_available_ratio": summary.get("published_pose_available_ratio"),
            "runtime_inference_success_rate": summary.get("inference_success_rate"),
            "skip_reason_delta": summary.get("skip_reasons") or {},
            "pose_provider": (summary.get("settings") or {}).get("pose_provider")
            if isinstance(summary.get("settings"), dict)
            else None,
            "pose_model_path": (summary.get("settings") or {}).get("pose_model_path")
            if isinstance(summary.get("settings"), dict)
            else None,
        },
        "next_action": (
            "replace replay evidence with live /status runtime probe before production promotion"
            if blockers
            else "dev replay runtime gate passed; still requires live /status before production"
        ),
    }


def check_provider_ab(path: Path, *, allow_cpu_provider: bool) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(path, ["provider_ab_missing"], "run CUDA provider A/B before selecting a production pose provider")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    run_config = payload.get("run_config") if isinstance(payload.get("run_config"), dict) else {}
    device = str(run_config.get("device") or "").strip().lower()
    provider_model_paths = run_config.get("provider_model_paths") if isinstance(run_config.get("provider_model_paths"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for provider, metrics in summary.items():
        if not isinstance(metrics, dict):
            continue
        skip_reasons = metrics.get("skip_reasons") if isinstance(metrics.get("skip_reasons"), dict) else {}
        errors = metrics.get("errors") if isinstance(metrics.get("errors"), dict) else {}
        provider_blockers = []
        sampled_frames = int(metrics.get("sampled_frames") or 0)
        inference_attempts = int(metrics.get("inference_attempt_count") or 0)
        avg_latency_ms = number_or_none(metrics.get("avg_latency_ms"))
        avg_skeleton_confidence = number_or_none(metrics.get("avg_skeleton_confidence"))
        if float(metrics.get("pose_valid_rate") or 0.0) < 0.70:
            provider_blockers.append("pose_valid_rate_below_0.70")
        if float(metrics.get("pose_frame_ratio") or 0.0) < 0.60:
            provider_blockers.append("pose_frame_ratio_below_0.60")
        if sampled_frames < MIN_PROVIDER_SAMPLED_FRAMES:
            provider_blockers.append("provider_sampled_frames_below_120")
        if inference_attempts < MIN_PROVIDER_INFERENCE_ATTEMPTS:
            provider_blockers.append("provider_inference_attempts_below_30")
        if avg_latency_ms is None or avg_latency_ms <= 0:
            provider_blockers.append("provider_avg_latency_missing")
        elif avg_latency_ms > MAX_PROVIDER_AVG_LATENCY_MS:
            provider_blockers.append("provider_avg_latency_above_250ms")
        if avg_skeleton_confidence is None or avg_skeleton_confidence <= 0:
            provider_blockers.append("provider_avg_skeleton_confidence_missing")
        elif avg_skeleton_confidence < MIN_PROVIDER_AVG_SKELETON_CONFIDENCE:
            provider_blockers.append("provider_avg_skeleton_confidence_below_0.50")
        if int(skip_reasons.get("pose_track_mismatch") or 0) > 0:
            provider_blockers.append("pose_track_mismatch_present")
        if errors:
            provider_blockers.append("provider_errors_present")
        candidates.append(
            {
                "provider": provider,
                "passed": not provider_blockers,
                "blockers": provider_blockers,
                "pose_model_path": provider_model_paths.get(provider),
                "pose_valid_rate": metrics.get("pose_valid_rate"),
                "pose_frame_ratio": metrics.get("pose_frame_ratio"),
                "sampled_frames": sampled_frames,
                "inference_attempt_count": inference_attempts,
                "avg_latency_ms": avg_latency_ms,
                "avg_skeleton_confidence": avg_skeleton_confidence,
                "skip_reasons": skip_reasons,
                "pose_quality_counts": metrics.get("pose_quality_counts") or {},
                "errors": errors,
            }
        )
    blockers = []
    non_production_reasons = []
    if not any(item["passed"] for item in candidates):
        blockers.append("no_provider_passed_quality_gate")
    if path_looks_cpu(path):
        non_production_reasons.append("provider_ab_is_cpu_dev_evidence")
        if not allow_cpu_provider:
            blockers.append("provider_ab_is_cpu_dev_evidence")
    if not device:
        non_production_reasons.append("provider_ab_device_metadata_missing")
    elif not device.startswith("cuda"):
        non_production_reasons.append("provider_ab_device_is_not_cuda")
        if not allow_cpu_provider:
            blockers.append("provider_ab_device_is_not_cuda")
    if path_looks_dev(path):
        non_production_reasons.append("provider_ab_looks_like_dev_or_local_evidence")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "production_evidence": not non_production_reasons,
        "non_production_reasons": dedupe(non_production_reasons),
        "metrics": {
            "device": run_config.get("device"),
            "provider_model_paths": provider_model_paths,
            "candidate_count": len(candidates),
            "passing_providers": [item["provider"] for item in candidates if item["passed"]],
            "candidates": candidates,
        },
        "next_action": "run CUDA provider A/B and select a provider with valid pose evidence" if blockers else "provider gate passed",
    }


def check_pose_model_quality(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(path, ["pose_model_quality_missing"], "run check_pose_model_quality.py for the configured pose model")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    blockers = list(summary.get("blockers") or [])
    warnings = list(summary.get("warnings") or [])
    if summary.get("passed") is not True:
        blockers.append("pose_model_quality_not_passed")
    non_production_reasons = []
    if path_looks_dev(path):
        non_production_reasons.append("pose_model_quality_looks_like_dev_or_smoke_evidence")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": dedupe([str(item) for item in blockers]),
        "warnings": dedupe([str(item) for item in warnings]),
        "production_evidence": not non_production_reasons,
        "non_production_reasons": non_production_reasons,
        "metrics": summary,
        "next_action": "fix pose model quality gate before runtime/provider promotion" if blockers else "pose model quality gate passed",
    }


def check_temporal_pose_data(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(path, ["temporal_pose_check_missing"], "export full pose-aware temporal data and run check_pose_temporal_sequences.py")
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
    blockers = [
        f"check_failed:{item.get('name')}"
        for item in checks
        if isinstance(item, dict) and item.get("passed") is not True
    ]
    if payload.get("passed") is not True:
        blockers.append("temporal_pose_check_failed")
    if int(summary.get("pose_available_true_rows") or 0) <= 0:
        blockers.append("pose_available_true_rows_zero")
    if float(summary.get("known_pose_quality_ratio") or 0.0) < 0.95:
        blockers.append("known_pose_quality_ratio_below_0.95")
    if int(summary.get("mismatch_available_rows") or 0) > 0:
        blockers.append("mismatch_available_rows_present")
    if int(summary.get("pose_available_missing_provider_rows") or 0) > 0:
        blockers.append("pose_available_missing_provider_metadata")
    if int(summary.get("pose_available_missing_model_rows") or 0) > 0:
        blockers.append("pose_available_missing_model_metadata")
    blockers = dedupe(blockers)
    non_production_reasons = []
    if path_looks_dev(path):
        non_production_reasons.append("temporal_check_looks_like_dev_or_smoke_evidence")
    rows = int(summary.get("rows") or 0)
    pose_rows = int(summary.get("pose_available_true_rows") or 0)
    dataset_counts = summary.get("dataset_counts") if isinstance(summary.get("dataset_counts"), dict) else {}
    label_counts = summary.get("label_counts") if isinstance(summary.get("label_counts"), dict) else {}
    missing_datasets = [name for name in REQUIRED_PRODUCTION_TEMPORAL_DATASETS if int(dataset_counts.get(name) or 0) <= 0]
    missing_labels = [name for name in REQUIRED_PRODUCTION_TEMPORAL_LABELS if int(label_counts.get(name) or 0) <= 0]
    if rows < MIN_PRODUCTION_TEMPORAL_ROWS:
        non_production_reasons.append("temporal_rows_below_1000")
    if pose_rows < MIN_PRODUCTION_TEMPORAL_POSE_ROWS:
        non_production_reasons.append("temporal_pose_available_rows_below_100")
    if "pose_available_missing_provider_rows" not in summary:
        non_production_reasons.append("temporal_pose_provider_metadata_check_missing")
    if "pose_available_missing_model_rows" not in summary:
        non_production_reasons.append("temporal_pose_model_metadata_check_missing")
    if missing_datasets:
        non_production_reasons.append("temporal_missing_required_datasets")
    if missing_labels:
        non_production_reasons.append("temporal_missing_required_labels")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "production_evidence": not non_production_reasons,
        "non_production_reasons": dedupe(non_production_reasons),
        "metrics": {
            **summary,
            "production_min_rows": MIN_PRODUCTION_TEMPORAL_ROWS,
            "production_min_pose_available_rows": MIN_PRODUCTION_TEMPORAL_POSE_ROWS,
            "required_datasets": list(REQUIRED_PRODUCTION_TEMPORAL_DATASETS),
            "required_labels": list(REQUIRED_PRODUCTION_TEMPORAL_LABELS),
            "missing_required_datasets": missing_datasets,
            "missing_required_labels": missing_labels,
        },
        "next_action": "fix/re-export pose-aware temporal sequences before pose LSTM training" if blockers else "temporal pose data gate passed",
    }


def check_lstm_manifest(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(path, ["pose_lstm_manifest_missing"], "build LSTM manifest with --require-pose after temporal gate passes")
    gate = payload.get("pose_training_gate") if isinstance(payload.get("pose_training_gate"), dict) else {}
    blockers = []
    if payload.get("require_pose") is not True:
        blockers.append("manifest_not_built_with_require_pose")
    if gate.get("passed") is not True:
        blockers.append("pose_training_gate_failed")
    if not payload.get("train_command"):
        blockers.append("train_command_missing")
    non_production_reasons = []
    if path_looks_dev(path):
        non_production_reasons.append("lstm_manifest_looks_like_dev_or_smoke_evidence")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "production_evidence": not non_production_reasons,
        "non_production_reasons": non_production_reasons,
        "metrics": {
            "require_pose": payload.get("require_pose"),
            "trainable_input_count": payload.get("trainable_input_count"),
            "label_counts": payload.get("label_counts") or {},
            "pose_training_gate": gate,
            "train_command": payload.get("train_command"),
        },
        "next_action": "build a valid --require-pose LSTM manifest before training" if blockers else "pose LSTM manifest gate passed",
    }


def check_lstm_comparison(path: Path) -> dict[str, Any]:
    payload, missing = read_json(path)
    if missing:
        return failed_gate(
            path,
            ["pose_lstm_comparison_missing"],
            "train/evaluate bbox+motion baseline and bbox+motion+pose LSTM, then write pose_lstm_comparison_20260705.json",
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else payload
    pose_metrics = _metric_group(summary, "pose_lstm", "pose")
    baseline_metrics = _metric_group(summary, "baseline_lstm", "baseline")
    ablation_metrics = _metric_group(summary, "pose_lstm_zero_pose_ablation")
    manifest_provenance = summary.get("lstm_manifest") if isinstance(summary.get("lstm_manifest"), dict) else {}
    comparison = summary.get("comparison") if isinstance(summary.get("comparison"), dict) else {}
    blockers = []
    if not pose_metrics:
        blockers.append("pose_lstm_metrics_missing")
    if not baseline_metrics:
        blockers.append("baseline_lstm_metrics_missing")
    if not ablation_metrics:
        blockers.append("pose_lstm_zero_pose_ablation_metrics_missing")
    pose_f1 = metric_number(pose_metrics, "f1", "fall_f1")
    baseline_f1 = metric_number(baseline_metrics, "f1", "fall_f1")
    ablation_f1 = metric_number(ablation_metrics, "f1", "fall_f1")
    if pose_f1 is None:
        blockers.append("pose_lstm_f1_missing")
    if baseline_f1 is None:
        blockers.append("baseline_lstm_f1_missing")
    if ablation_f1 is None:
        blockers.append("pose_lstm_zero_pose_ablation_f1_missing")
    if pose_f1 is not None and baseline_f1 is not None and pose_f1 <= baseline_f1:
        blockers.append("pose_lstm_not_better_than_baseline_f1")
    if pose_f1 is not None and ablation_f1 is not None and pose_f1 <= ablation_f1:
        blockers.append("pose_lstm_not_better_than_zero_pose_ablation")
    pose_fp = metric_number(pose_metrics, "false_positive_count", "confirmed_fp", "fp")
    baseline_fp = metric_number(baseline_metrics, "false_positive_count", "confirmed_fp", "fp")
    ablation_fp = metric_number(ablation_metrics, "false_positive_count", "confirmed_fp", "fp")
    if pose_fp is None:
        blockers.append("pose_lstm_false_positive_count_missing")
    if baseline_fp is None:
        blockers.append("baseline_lstm_false_positive_count_missing")
    if ablation_fp is None:
        blockers.append("pose_lstm_zero_pose_ablation_false_positive_count_missing")
    if pose_fp is not None and baseline_fp is not None and pose_fp > baseline_fp:
        blockers.append("pose_lstm_false_positives_worse_than_baseline")
    if pose_fp is not None and ablation_fp is not None and pose_fp > ablation_fp:
        blockers.append("pose_lstm_false_positives_worse_than_zero_pose_ablation")
    if not manifest_provenance:
        blockers.append("lstm_comparison_manifest_provenance_missing")
    else:
        if not manifest_provenance.get("sha256"):
            blockers.append("lstm_comparison_manifest_sha256_missing")
        if not manifest_provenance.get("schema_hashes"):
            blockers.append("lstm_comparison_manifest_schema_hashes_missing")
        if not manifest_provenance.get("pose_provider_counts"):
            blockers.append("lstm_comparison_manifest_pose_provider_counts_missing")
        if not manifest_provenance.get("pose_model_path_counts"):
            blockers.append("lstm_comparison_manifest_pose_model_path_counts_missing")
        if manifest_provenance.get("input_files_match_metrics") is not True:
            blockers.append("lstm_comparison_metrics_inputs_do_not_match_manifest")
        if manifest_provenance.get("metric_manifest_sha256s_match_manifest") is not True:
            blockers.append("lstm_comparison_metric_manifest_sha256s_do_not_match_manifest")
        if manifest_provenance.get("pose_train_config_manifest_sha256s_match_manifest") is not True:
            blockers.append("lstm_comparison_pose_train_config_manifest_sha256s_do_not_match_manifest")
    for blocker in comparison.get("blockers") or []:
        if isinstance(blocker, str):
            blockers.append(blocker)
    if comparison.get("passed") is False:
        blockers.append("lstm_comparison_report_failed")
    non_production_reasons = []
    if path_looks_dev(path):
        non_production_reasons.append("lstm_comparison_looks_like_dev_or_smoke_evidence")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "production_evidence": not non_production_reasons,
        "non_production_reasons": non_production_reasons,
        "metrics": {
            "pose_lstm": pose_metrics,
            "baseline_lstm": baseline_metrics,
            "pose_lstm_zero_pose_ablation": ablation_metrics,
            "lstm_manifest": manifest_provenance,
            "comparison": {
                **comparison,
                "f1_delta": round(pose_f1 - baseline_f1, 6)
                if pose_f1 is not None and baseline_f1 is not None
                else None,
                "zero_pose_ablation_f1_delta": round(pose_f1 - ablation_f1, 6)
                if pose_f1 is not None and ablation_f1 is not None
                else None,
            },
        },
        "next_action": (
            "prove bbox+motion+pose LSTM beats both bbox+motion baseline and zero-pose ablation before production promotion"
            if blockers
            else "pose LSTM comparison gate passed"
        ),
    }


def check_evidence_consistency(checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    runtime_metrics = as_dict(checks.get("runtime", {}).get("metrics"))
    provider_metrics = as_dict(checks.get("provider", {}).get("metrics"))
    model_metrics = as_dict(checks.get("model_quality", {}).get("metrics"))

    runtime_provider = str(runtime_metrics.get("pose_provider") or "").strip()
    runtime_model = str(runtime_metrics.get("pose_model_path") or "").strip()
    provider_device = str(provider_metrics.get("device") or "").strip()
    passing_providers = [str(item) for item in provider_metrics.get("passing_providers") or []]
    provider_model_paths = as_dict(provider_metrics.get("provider_model_paths"))
    provider_candidates = [
        str(item.get("provider"))
        for item in provider_metrics.get("candidates") or []
        if isinstance(item, dict) and item.get("provider")
    ]
    configured_model = str(model_metrics.get("configured_model") or "").strip()

    blockers: list[str] = []
    non_production_reasons: list[str] = []

    if runtime_provider:
        if provider_candidates and runtime_provider not in provider_candidates:
            blockers.append("runtime_pose_provider_missing_from_provider_ab")
        elif provider_candidates and runtime_provider not in passing_providers:
            blockers.append("runtime_pose_provider_did_not_pass_provider_ab")
    else:
        non_production_reasons.append("runtime_pose_provider_metadata_missing")

    if not provider_device:
        non_production_reasons.append("provider_device_metadata_missing_for_consistency")
    elif not provider_device.lower().startswith("cuda"):
        non_production_reasons.append("provider_device_is_not_cuda_for_consistency")

    if not configured_model:
        non_production_reasons.append("configured_pose_model_metadata_missing")
    if runtime_model and configured_model:
        if normalize_model_path(runtime_model) != normalize_model_path(configured_model):
            blockers.append("runtime_pose_model_does_not_match_model_quality")
    elif configured_model and not runtime_model:
        non_production_reasons.append("runtime_pose_model_metadata_missing")
    if runtime_provider and configured_model:
        provider_model = str(provider_model_paths.get(runtime_provider) or "").strip()
        if provider_model:
            if normalize_model_path(provider_model) != normalize_model_path(configured_model):
                blockers.append("provider_ab_pose_model_does_not_match_model_quality")
        else:
            non_production_reasons.append("provider_ab_pose_model_metadata_missing")

    return {
        "path": "derived:runtime+model_quality+provider",
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "production_evidence": not non_production_reasons,
        "non_production_reasons": dedupe(non_production_reasons),
        "metrics": {
            "runtime_pose_provider": runtime_provider or None,
            "runtime_pose_model": runtime_model or None,
            "provider_device": provider_device or None,
            "provider_candidates": provider_candidates,
            "passing_providers": passing_providers,
            "provider_model_paths": provider_model_paths,
            "configured_pose_model": configured_model or None,
        },
        "next_action": (
            "make runtime/provider/model evidence describe the same pose configuration before production promotion"
            if blockers
            else "pose evidence configuration is internally consistent"
        ),
    }


def read_json(path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {}, True
    try:
        return json.loads(path.read_text(encoding="utf-8")), False
    except json.JSONDecodeError as exc:
        return {"error": str(exc)}, False


def failed_gate(path: Path, blockers: list[str], next_action: str) -> dict[str, Any]:
    return {
        "path": str(path),
        "passed": False,
        "blockers": blockers,
        "production_evidence": False,
        "non_production_reasons": [],
        "metrics": {},
        "next_action": next_action,
    }


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


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_model_path(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\\", "/").strip()
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text.lower()


def _metric_group(summary: dict[str, Any], *names: str) -> dict[str, Any]:
    for name in names:
        value = summary.get(name)
        if isinstance(value, dict):
            return value
    return {}


def metric_number(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = number_or_none(metrics.get(name))
        if value is not None:
            return value
    return None


def path_looks_cpu(path: Path) -> bool:
    return "cpu" in path.name.lower()


def path_looks_dev(path: Path) -> bool:
    markers = ("dev", "smoke", "local", "mock", "replay")
    name = path.name.lower()
    return any(marker in name for marker in markers)


def runtime_profile_looks_bcpu(path: Path, summary: dict[str, Any]) -> bool:
    profile_name = str(summary.get("profile_name") or "").lower()
    path_name = path.name.lower()
    return "bcpu" in profile_name or "bcpu" in path_name


def recommendation(blocking: list[dict[str, Any]], non_production: list[dict[str, Any]] | None = None) -> str:
    if not blocking:
        if non_production:
            return "dev/local gates passed; production still requires live CUDA runtime, CUDA provider A/B, full pose-aware data, and production LSTM manifest"
        return "all pose optimization gates passed; proceed to controlled training/evaluation rollout"
    order = ["runtime", "model_quality", "provider", "evidence_consistency", "temporal_data", "lstm_manifest", "lstm_comparison"]
    failed = {str(item["gate"]): item for item in blocking}
    for name in order:
        if name in failed:
            return {
                "runtime": "start the live service and pass the B runtime probe before relying on pose downstream",
                "model_quality": "prove the configured pose model is not worse than the baseline before runtime/provider promotion",
                "provider": "run CUDA provider A/B before selecting or retraining a pose model",
                "evidence_consistency": "make runtime, provider, and model-quality evidence describe the same pose configuration",
                "temporal_data": "re-export full pose-aware temporal data and pass the pose sequence gate",
                "lstm_manifest": "build the pose LSTM manifest with --require-pose before training",
                "lstm_comparison": "train/evaluate pose LSTM against bbox+motion baseline and zero-pose ablation before production promotion",
            }[name]
    return "resolve failed pose optimization gates in order"


if __name__ == "__main__":
    raise SystemExit(main())
