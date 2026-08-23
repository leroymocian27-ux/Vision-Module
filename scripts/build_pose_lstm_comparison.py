from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("evaluations") / "pose_lstm_comparison_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the bbox+motion baseline vs bbox+motion+pose LSTM comparison report."
    )
    parser.add_argument("--baseline-metrics", required=True, help="Baseline bbox+motion LSTM evaluation JSON.")
    parser.add_argument("--pose-metrics", required=True, help="Pose-aware bbox+motion+pose LSTM evaluation JSON.")
    parser.add_argument(
        "--pose-ablation-metrics",
        default=None,
        help="Optional metrics for the pose LSTM evaluated with pose feature columns zeroed.",
    )
    parser.add_argument(
        "--lstm-manifest",
        default=None,
        help="Optional pose LSTM training/evaluation manifest used by all compared metrics.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output comparison JSON.")
    parser.add_argument(
        "--min-f1-delta",
        type=float,
        default=0.0,
        help="Required pose_f1 - baseline_f1 improvement. Default requires a strict improvement.",
    )
    parser.add_argument(
        "--max-fp-delta",
        type=int,
        default=0,
        help="Allowed pose false-positive increase over baseline. Production should keep this at 0.",
    )
    args = parser.parse_args()

    report = build_comparison_report(
        baseline_path=Path(args.baseline_metrics),
        pose_path=Path(args.pose_metrics),
        pose_ablation_path=Path(args.pose_ablation_metrics) if args.pose_ablation_metrics else None,
        lstm_manifest_path=Path(args.lstm_manifest) if args.lstm_manifest else None,
        min_f1_delta=args.min_f1_delta,
        max_fp_delta=args.max_fp_delta,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["comparison"]["passed"] else 1


def build_comparison_report(
    *,
    baseline_path: Path,
    pose_path: Path,
    pose_ablation_path: Path | None = None,
    lstm_manifest_path: Path | None = None,
    min_f1_delta: float = 0.0,
    max_fp_delta: int = 0,
) -> dict[str, Any]:
    baseline_payload = load_json(baseline_path)
    pose_payload = load_json(pose_path)
    pose_ablation_payload = load_json(pose_ablation_path) if pose_ablation_path else None
    manifest_payload = load_json(lstm_manifest_path) if lstm_manifest_path else None
    baseline = extract_metrics(baseline_payload)
    pose = extract_metrics(pose_payload)
    pose_ablation = extract_metrics(pose_ablation_payload) if pose_ablation_payload else None
    manifest_provenance = (
        build_manifest_provenance(
            manifest_path=lstm_manifest_path,
            manifest_payload=manifest_payload,
            metric_payloads={
                "baseline_lstm": baseline_payload,
                "pose_lstm": pose_payload,
                "pose_lstm_zero_pose_ablation": pose_ablation_payload,
            },
        )
        if lstm_manifest_path and manifest_payload is not None
        else None
    )
    blockers = comparison_blockers(
        baseline=baseline,
        pose=pose,
        pose_ablation=pose_ablation,
        manifest_provenance=manifest_provenance,
        min_f1_delta=min_f1_delta,
        max_fp_delta=max_fp_delta,
    )
    f1_delta = metric_delta(pose.get("f1"), baseline.get("f1"))
    fp_delta = metric_delta(pose.get("false_positive_count"), baseline.get("false_positive_count"))
    ablation_f1_delta = (
        metric_delta(pose.get("f1"), pose_ablation.get("f1")) if pose_ablation is not None else None
    )
    ablation_fp_delta = (
        metric_delta(pose.get("false_positive_count"), pose_ablation.get("false_positive_count"))
        if pose_ablation is not None
        else None
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "baseline_lstm": str(baseline_path),
            "pose_lstm": str(pose_path),
            "pose_lstm_zero_pose_ablation": str(pose_ablation_path) if pose_ablation_path else None,
            "lstm_manifest": str(lstm_manifest_path) if lstm_manifest_path else None,
        },
        "summary": {
            "baseline_lstm": baseline,
            "pose_lstm": pose,
            "pose_lstm_zero_pose_ablation": pose_ablation,
            "lstm_manifest": manifest_provenance,
            "comparison": {
                "passed": not blockers,
                "blockers": blockers,
                "f1_delta": round(f1_delta, 6) if f1_delta is not None else None,
                "false_positive_delta": int(fp_delta) if fp_delta is not None else None,
                "zero_pose_ablation_f1_delta": (
                    round(ablation_f1_delta, 6) if ablation_f1_delta is not None else None
                ),
                "zero_pose_ablation_false_positive_delta": (
                    int(ablation_fp_delta) if ablation_fp_delta is not None else None
                ),
                "min_f1_delta": min_f1_delta,
                "max_fp_delta": max_fp_delta,
            },
        },
    }


def comparison_blockers(
    *,
    baseline: dict[str, Any],
    pose: dict[str, Any],
    pose_ablation: dict[str, Any] | None,
    manifest_provenance: dict[str, Any] | None,
    min_f1_delta: float,
    max_fp_delta: int,
) -> list[str]:
    blockers: list[str] = []
    baseline_f1 = number_or_none(baseline.get("f1"))
    pose_f1 = number_or_none(pose.get("f1"))
    baseline_fp = number_or_none(baseline.get("false_positive_count"))
    pose_fp = number_or_none(pose.get("false_positive_count"))
    if baseline_f1 is None:
        blockers.append("baseline_lstm_f1_missing")
    if pose_f1 is None:
        blockers.append("pose_lstm_f1_missing")
    if baseline_f1 is not None and pose_f1 is not None and (pose_f1 - baseline_f1) <= min_f1_delta:
        blockers.append("pose_lstm_not_better_than_baseline_f1")
    if baseline_fp is None:
        blockers.append("baseline_lstm_false_positive_count_missing")
    if pose_fp is None:
        blockers.append("pose_lstm_false_positive_count_missing")
    if baseline_fp is not None and pose_fp is not None and (pose_fp - baseline_fp) > max_fp_delta:
        blockers.append("pose_lstm_false_positives_worse_than_baseline")
    if pose_ablation is not None:
        ablation_f1 = number_or_none(pose_ablation.get("f1"))
        ablation_fp = number_or_none(pose_ablation.get("false_positive_count"))
        if ablation_f1 is None:
            blockers.append("pose_lstm_zero_pose_ablation_f1_missing")
        if ablation_fp is None:
            blockers.append("pose_lstm_zero_pose_ablation_false_positive_count_missing")
        if pose_f1 is not None and ablation_f1 is not None and (pose_f1 - ablation_f1) <= min_f1_delta:
            blockers.append("pose_lstm_not_better_than_zero_pose_ablation")
        if pose_fp is not None and ablation_fp is not None and (pose_fp - ablation_fp) > max_fp_delta:
            blockers.append("pose_lstm_false_positives_worse_than_zero_pose_ablation")
    if manifest_provenance is not None:
        if not manifest_provenance.get("require_pose"):
            blockers.append("lstm_manifest_not_pose_required")
        if manifest_provenance.get("pose_training_gate_passed") is not True:
            blockers.append("lstm_manifest_pose_training_gate_not_passed")
        if manifest_provenance.get("input_files_match_metrics") is not True:
            blockers.append("lstm_metrics_input_files_do_not_match_manifest")
        if manifest_provenance.get("metric_manifest_sha256s_match_manifest") is not True:
            blockers.append("lstm_metrics_manifest_sha256s_do_not_match_manifest")
        if manifest_provenance.get("pose_train_config_manifest_sha256s_match_manifest") is not True:
            blockers.append("pose_lstm_train_config_manifest_sha256s_do_not_match_manifest")
        if int(manifest_provenance.get("pose_available_missing_provider_rows") or 0) > 0:
            blockers.append("lstm_manifest_pose_provider_metadata_missing")
        if int(manifest_provenance.get("pose_available_missing_model_rows") or 0) > 0:
            blockers.append("lstm_manifest_pose_model_metadata_missing")
    return blockers


def build_manifest_provenance(
    *,
    manifest_path: Path,
    manifest_payload: dict[str, Any],
    metric_payloads: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    pose_gate = manifest_payload.get("pose_training_gate") if isinstance(manifest_payload.get("pose_training_gate"), dict) else {}
    manifest_inputs = normalized_path_set(manifest_payload.get("input_files") or [])
    metric_inputs: set[str] = set()
    metric_manifest_sha256s: list[str] = []
    pose_train_config_manifest_sha256s: list[str] = []
    metrics_missing_input_files = 0
    metrics_missing_input_manifest_sha256 = 0
    pose_metrics_missing_train_config_manifest_sha256 = 0
    manifest_sha256 = sha256_file(resolve_path(manifest_path))
    for role, payload in metric_payloads.items():
        if not payload:
            continue
        raw_inputs = payload.get("input_files")
        if isinstance(raw_inputs, list) and raw_inputs:
            metric_inputs.update(normalized_path_set(raw_inputs))
        else:
            metrics_missing_input_files += 1
        input_manifest = payload.get("input_manifest") if isinstance(payload.get("input_manifest"), dict) else {}
        metric_manifest_sha256 = str(input_manifest.get("sha256") or "").strip()
        if metric_manifest_sha256:
            metric_manifest_sha256s.append(metric_manifest_sha256)
        else:
            metrics_missing_input_manifest_sha256 += 1
        train_config = payload.get("train_config") if isinstance(payload.get("train_config"), dict) else {}
        train_manifest_sha256 = str(train_config.get("input_manifest_sha256") or "").strip()
        if role in {"pose_lstm", "pose_lstm_zero_pose_ablation"}:
            if train_manifest_sha256:
                pose_train_config_manifest_sha256s.append(train_manifest_sha256)
            else:
                pose_metrics_missing_train_config_manifest_sha256 += 1
    return {
        "path": str(manifest_path),
        "sha256": manifest_sha256,
        "require_pose": bool(manifest_payload.get("require_pose")),
        "trainable_input_count": manifest_payload.get("trainable_input_count"),
        "schema_versions": manifest_payload.get("schema_versions") or [],
        "schema_hashes": manifest_payload.get("schema_hashes") or [],
        "pose_training_gate_passed": pose_gate.get("passed"),
        "usable_rows": pose_gate.get("usable_rows"),
        "pose_available_true_rows": pose_gate.get("pose_available_true_rows"),
        "pose_available_true_ratio": pose_gate.get("pose_available_true_ratio"),
        "known_pose_quality_ratio": pose_gate.get("known_pose_quality_ratio"),
        "pose_provider_counts": pose_gate.get("pose_provider_counts") or {},
        "pose_model_path_counts": pose_gate.get("pose_model_path_counts") or {},
        "pose_device_counts": pose_gate.get("pose_device_counts") or {},
        "pose_available_missing_provider_rows": pose_gate.get("pose_available_missing_provider_rows") or 0,
        "pose_available_missing_model_rows": pose_gate.get("pose_available_missing_model_rows") or 0,
        "input_file_count": len(manifest_inputs),
        "metric_input_file_count": len(metric_inputs),
        "metrics_missing_input_files": metrics_missing_input_files,
        "input_files_match_metrics": bool(manifest_inputs) and metrics_missing_input_files == 0 and metric_inputs == manifest_inputs,
        "metric_manifest_sha256s": metric_manifest_sha256s,
        "metrics_missing_input_manifest_sha256": metrics_missing_input_manifest_sha256,
        "metric_manifest_sha256s_match_manifest": (
            metrics_missing_input_manifest_sha256 == 0
            and bool(metric_manifest_sha256s)
            and all(item == manifest_sha256 for item in metric_manifest_sha256s)
        ),
        "pose_train_config_manifest_sha256s": pose_train_config_manifest_sha256s,
        "pose_metrics_missing_train_config_manifest_sha256": pose_metrics_missing_train_config_manifest_sha256,
        "pose_train_config_manifest_sha256s_match_manifest": (
            pose_metrics_missing_train_config_manifest_sha256 == 0
            and bool(pose_train_config_manifest_sha256s)
            and all(item == manifest_sha256 for item in pose_train_config_manifest_sha256s)
        ),
    }


def extract_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    metrics = metric_source(payload)
    confusion = extract_confusion(metrics)
    precision = first_number(metrics, "precision", "fall_precision", "fall_event_precision")
    recall = first_number(metrics, "recall", "fall_recall", "fall_event_recall")
    f1 = first_number(metrics, "f1", "fall_f1", "fall_event_f1")
    if precision is None and confusion:
        precision = safe_div(confusion["true_positive"], confusion["true_positive"] + confusion["false_positive"])
    if recall is None and confusion:
        recall = safe_div(confusion["true_positive"], confusion["true_positive"] + confusion["false_negative"])
    if f1 is None and precision is not None and recall is not None:
        f1 = safe_div(2 * precision * recall, precision + recall)
    false_positive = first_number(metrics, "false_positive_count", "confirmed_fp", "fp")
    if false_positive is None and confusion:
        false_positive = float(confusion["false_positive"])
    result = {
        "precision": round(precision, 6) if precision is not None else None,
        "recall": round(recall, 6) if recall is not None else None,
        "f1": round(f1, 6) if f1 is not None else None,
        "false_positive_count": int(false_positive) if false_positive is not None else None,
        "confusion": confusion,
    }
    sample_count = first_number(metrics, "sample_count", "samples", "video_count", "all_window_count")
    if sample_count is not None:
        result["sample_count"] = int(sample_count)
    return result


def metric_source(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        payload.get("event_metrics"),
        payload.get("v6_event_metrics"),
        payload.get("metrics"),
        payload.get("summary"),
        payload,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}


def extract_confusion(metrics: dict[str, Any]) -> dict[str, int]:
    raw = metrics.get("confusion") if isinstance(metrics.get("confusion"), dict) else {}
    aliases = {
        "true_positive": ("true_positive", "tp"),
        "false_positive": ("false_positive", "fp"),
        "false_negative": ("false_negative", "fn"),
        "true_negative": ("true_negative", "tn"),
    }
    confusion = {}
    for canonical, names in aliases.items():
        value = first_number(raw, *names)
        confusion[canonical] = int(value) if value is not None else 0
    return confusion if any(confusion.values()) else {}


def first_number(payload: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = number_or_none(payload.get(name))
        if value is not None:
            return value
    return None


def number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def metric_delta(after: Any, before: Any) -> float | None:
    after_number = number_or_none(after)
    before_number = number_or_none(before)
    if after_number is None or before_number is None:
        return None
    return after_number - before_number


def load_json(path: Path) -> dict[str, Any]:
    resolved = resolve_path(path)
    if not resolved.exists():
        raise SystemExit(f"missing LSTM metrics JSON: {path}")
    return json.loads(resolved.read_text(encoding="utf-8"))


def normalized_path_set(paths: list[Any]) -> set[str]:
    return {str(resolve_path(Path(str(item))).resolve()).lower() for item in paths}


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
