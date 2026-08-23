from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = ROOT / "models" / "pose_yolo_batch001_003_yolo11s_metrics.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_model_quality_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether the configured pose model beats the baseline quality gate.")
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS))
    parser.add_argument("--configured-model", default="yolo11n-pose.pt")
    parser.add_argument("--min-pose-map50-95-delta", type=float, default=0.0)
    parser.add_argument("--max-pose-recall-drop", type=float, default=0.02)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    report = build_pose_model_quality_report(
        metrics_path=Path(args.metrics),
        configured_model=args.configured_model,
        min_pose_map50_95_delta=args.min_pose_map50_95_delta,
        max_pose_recall_drop=args.max_pose_recall_drop,
    )
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["passed"] else 1


def build_pose_model_quality_report(
    *,
    metrics_path: Path,
    configured_model: str,
    min_pose_map50_95_delta: float = 0.0,
    max_pose_recall_drop: float = 0.02,
) -> dict[str, Any]:
    payload, missing = read_json(metrics_path)
    blockers: list[str] = []
    warnings: list[str] = []
    if missing:
        blockers.append("pose_model_metrics_missing")
        payload = {}

    baseline = payload.get("baseline") if isinstance(payload.get("baseline"), dict) else {}
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    delta = payload.get("delta") if isinstance(payload.get("delta"), dict) else {}
    baseline_model = payload.get("baseline_model")
    candidate_model = payload.get("candidate_model")

    configured_path = normalize_model_path(configured_model)
    baseline_path = normalize_model_path(str(baseline_model or ""))
    candidate_path = normalize_model_path(str(candidate_model or ""))
    uses_baseline_model = bool(configured_path and baseline_path and configured_path == baseline_path)
    if not configured_path:
        blockers.append("configured_pose_model_missing")
    elif not uses_baseline_model and candidate_path and configured_path != candidate_path:
        blockers.append("configured_pose_model_does_not_match_metrics_candidate")

    if configured_path:
        asset = resolve_path(Path(configured_path))
        if not asset.exists():
            blockers.append("configured_pose_model_file_missing")

    baseline_pose_map = number_or_none(baseline.get("pose_map50_95"))
    candidate_pose_map = number_or_none(candidate.get("pose_map50_95"))
    delta_pose_map = number_or_none(delta.get("pose_map50_95"))
    if delta_pose_map is None and baseline_pose_map is not None and candidate_pose_map is not None:
        delta_pose_map = candidate_pose_map - baseline_pose_map

    baseline_recall = number_or_none(baseline.get("pose_recall"))
    candidate_recall = number_or_none(candidate.get("pose_recall"))
    recall_delta = (
        candidate_recall - baseline_recall
        if candidate_recall is not None and baseline_recall is not None
        else None
    )

    if baseline_pose_map is None:
        blockers.append("baseline_pose_map50_95_missing")
    if not uses_baseline_model:
        if candidate_pose_map is None:
            blockers.append("candidate_pose_map50_95_missing")
        if delta_pose_map is None:
            blockers.append("delta_pose_map50_95_missing")
        elif delta_pose_map < min_pose_map50_95_delta:
            blockers.append("candidate_pose_map50_95_below_baseline")

    if baseline_recall is None:
        warnings.append("baseline_pose_recall_missing")
    if not uses_baseline_model and candidate_recall is None:
        warnings.append("candidate_pose_recall_missing")
    if not uses_baseline_model and recall_delta is not None and recall_delta < -abs(max_pose_recall_drop):
        blockers.append("candidate_pose_recall_drop_too_large")

    metrics_device = str(payload.get("device") or "").strip()
    if not metrics_device:
        warnings.append("pose_model_metrics_device_missing")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "metrics": str(metrics_path),
            "configured_model": configured_model,
            "min_pose_map50_95_delta": min_pose_map50_95_delta,
            "max_pose_recall_drop": max_pose_recall_drop,
        },
        "summary": {
            "passed": not blockers,
            "blockers": dedupe(blockers),
            "warnings": dedupe(warnings),
            "baseline_model": baseline_model,
            "candidate_model": candidate_model,
            "configured_model": configured_model,
            "uses_baseline_model": uses_baseline_model,
            "baseline_pose_map50_95": baseline_pose_map,
            "candidate_pose_map50_95": candidate_pose_map,
            "delta_pose_map50_95": round(delta_pose_map, 6) if delta_pose_map is not None else None,
            "baseline_pose_recall": baseline_recall,
            "candidate_pose_recall": candidate_recall,
            "delta_pose_recall": round(recall_delta, 6) if recall_delta is not None else None,
            "next_action": next_action(blockers),
        },
    }


def next_action(blockers: list[str]) -> str:
    if not blockers:
        return "pose model quality gate passed; continue runtime/provider production validation"
    if "candidate_pose_map50_95_below_baseline" in blockers:
        return "do not promote this pose model; switch back to baseline or produce a candidate that beats baseline pose mAP50-95"
    if "configured_pose_model_does_not_match_metrics_candidate" in blockers:
        return "regenerate model metrics for the exact configured pose model before production validation"
    return "fix pose model quality evidence before runtime/provider/LSTM promotion"


def read_json(path: Path) -> tuple[dict[str, Any], bool]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}, True
    return json.loads(resolved.read_text(encoding="utf-8")), False


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def normalize_model_path(value: str) -> str:
    text = value.replace("\\", "/").strip()
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text


def number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
