from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SLOW_FALL = ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_stride8" / "temporal_v6_regression_comparison.json"
DEFAULT_FP = ROOT / "evaluations" / "fall_temporal_v6" / "fp_regression_stride8" / "temporal_v6_regression_comparison.json"
DEFAULT_UR_MINI = ROOT / "evaluations" / "fall_temporal_v6" / "ur_mini_regression_stride4" / "temporal_v6_regression_comparison.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_acceptance_gate.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check temporal v6 post-training acceptance gates.")
    parser.add_argument("--slow-fall", default=str(DEFAULT_SLOW_FALL), help="Slow-fall review comparison JSON.")
    parser.add_argument("--fp-regression", default=str(DEFAULT_FP), help="Hard-negative comparison JSON.")
    parser.add_argument("--ur-mini", default=str(DEFAULT_UR_MINI), help="UR mini comparison JSON.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Acceptance gate output JSON.")
    parser.add_argument("--min-slow-fall-recall", type=float, default=0.80)
    parser.add_argument("--max-fp", type=int, default=0)
    parser.add_argument("--max-duplicates", type=int, default=0)
    parser.add_argument("--max-ur-mini-fp", type=int, default=0)
    args = parser.parse_args()

    result = check_acceptance(
        slow_fall_path=Path(args.slow_fall),
        fp_path=Path(args.fp_regression),
        ur_mini_path=Path(args.ur_mini),
        min_slow_fall_recall=args.min_slow_fall_recall,
        max_fp=args.max_fp,
        max_duplicates=args.max_duplicates,
        max_ur_mini_fp=args.max_ur_mini_fp,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def check_acceptance(
    *,
    slow_fall_path: Path,
    fp_path: Path,
    ur_mini_path: Path,
    min_slow_fall_recall: float,
    max_fp: int,
    max_duplicates: int,
    max_ur_mini_fp: int,
) -> dict[str, Any]:
    slow = load_json(slow_fall_path)
    fp = load_json(fp_path)
    ur = load_json(ur_mini_path)
    checks = [
        slow_fall_recall_check(slow, threshold=min_slow_fall_recall),
        fp_check(fp, max_fp=max_fp),
        duplicate_check(slow, label="slow_fall_review", max_duplicates=max_duplicates),
        duplicate_check(fp, label="fp_regression", max_duplicates=max_duplicates),
        duplicate_check(ur, label="ur_mini", max_duplicates=max_duplicates),
        ur_mini_fp_check(ur, max_fp=max_ur_mini_fp),
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "inputs": {
            "slow_fall": str(slow_fall_path.resolve()),
            "fp_regression": str(fp_path.resolve()),
            "ur_mini": str(ur_mini_path.resolve()),
        },
        "summary": {
            "slow_fall_recall": metric(slow, "fall_event_recall"),
            "slow_fall_confusion": confusion(slow),
            "fp_regression_confusion": confusion(fp),
            "ur_mini_confusion": confusion(ur),
            "slow_fall_duplicate_alarm_videos": slow.get("duplicate_alarm_videos") or [],
            "fp_duplicate_alarm_videos": fp.get("duplicate_alarm_videos") or [],
            "ur_mini_duplicate_alarm_videos": ur.get("duplicate_alarm_videos") or [],
        },
    }


def slow_fall_recall_check(comparison: dict[str, Any], *, threshold: float) -> dict[str, Any]:
    value = metric(comparison, "fall_event_recall")
    passed = value is not None and value >= threshold
    return {
        "name": "slow_fall_review_recall",
        "passed": passed,
        "actual": value,
        "required": f">= {threshold:.2f}",
        "details": confusion(comparison),
    }


def fp_check(comparison: dict[str, Any], *, max_fp: int) -> dict[str, Any]:
    fp_count = int(confusion(comparison).get("false_positive") or 0)
    return {
        "name": "fp_regression_confirmed_false_positive",
        "passed": fp_count <= max_fp,
        "actual": fp_count,
        "required": f"<= {max_fp}",
        "details": confusion(comparison),
    }


def ur_mini_fp_check(comparison: dict[str, Any], *, max_fp: int) -> dict[str, Any]:
    fp_count = int(confusion(comparison).get("false_positive") or 0)
    return {
        "name": "ur_mini_confirmed_false_positive",
        "passed": fp_count <= max_fp,
        "actual": fp_count,
        "required": f"<= {max_fp}",
        "details": confusion(comparison),
    }


def duplicate_check(comparison: dict[str, Any], *, label: str, max_duplicates: int) -> dict[str, Any]:
    duplicates = comparison.get("duplicate_alarm_videos") or []
    return {
        "name": f"{label}_duplicate_alarm_videos",
        "passed": len(duplicates) <= max_duplicates,
        "actual": len(duplicates),
        "required": f"<= {max_duplicates}",
        "details": duplicates,
    }


def metric(comparison: dict[str, Any], key: str) -> float | None:
    metrics = comparison.get("v6_event_metrics") or {}
    value = metrics.get(key)
    return None if value is None else float(value)


def confusion(comparison: dict[str, Any]) -> dict[str, int]:
    metrics = comparison.get("v6_event_metrics") or {}
    raw = metrics.get("confusion") or {}
    return {
        "true_positive": int(raw.get("true_positive") or 0),
        "false_negative": int(raw.get("false_negative") or 0),
        "false_positive": int(raw.get("false_positive") or 0),
        "true_negative": int(raw.get("true_negative") or 0),
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"missing comparison JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
