from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VALID_QUALITY_LEVELS = {
    "pose_absent",
    "low_quality",
    "valid",
    "high_confidence",
    "pose_track_mismatch",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pose-aware temporal sequence JSONL exports.")
    parser.add_argument("--input-dir", default="data/temporal_sequences_pose_v1")
    parser.add_argument("--output", default="evaluations/pose_temporal_sequences_check_20260705.json")
    parser.add_argument("--min-pose-available-ratio", type=float, default=0.05)
    parser.add_argument("--min-known-quality-ratio", type=float, default=0.95)
    parser.add_argument("--expected-input-dim", type=int, default=15)
    args = parser.parse_args()

    result = check_pose_temporal_sequences(
        input_dir=ROOT / args.input_dir,
        min_pose_available_ratio=args.min_pose_available_ratio,
        min_known_quality_ratio=args.min_known_quality_ratio,
        expected_input_dim=args.expected_input_dim,
    )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


def check_pose_temporal_sequences(
    *,
    input_dir: Path,
    min_pose_available_ratio: float,
    min_known_quality_ratio: float,
    expected_input_dim: int,
) -> dict[str, Any]:
    files = sorted(path for path in input_dir.rglob("*.jsonl") if path.is_file()) if input_dir.exists() else []
    stats = SequenceStats()
    for path in files:
        scan_file(path, stats=stats, expected_input_dim=expected_input_dim)

    summary = stats.summary(input_dir=input_dir, files=len(files))
    checks = [
        {
            "name": "has_jsonl_files",
            "passed": len(files) > 0,
            "actual": len(files),
            "required": "> 0",
        },
        {
            "name": "has_rows",
            "passed": stats.rows > 0,
            "actual": stats.rows,
            "required": "> 0",
        },
        {
            "name": "pose_available_ratio",
            "passed": summary["pose_available_true_ratio"] >= min_pose_available_ratio,
            "actual": summary["pose_available_true_ratio"],
            "required": f">= {min_pose_available_ratio:.4f}",
        },
        {
            "name": "known_pose_quality_ratio",
            "passed": summary["known_pose_quality_ratio"] >= min_known_quality_ratio,
            "actual": summary["known_pose_quality_ratio"],
            "required": f">= {min_known_quality_ratio:.4f}",
        },
        {
            "name": "no_vector_dim_errors",
            "passed": stats.vector_dim_errors == 0,
            "actual": stats.vector_dim_errors,
            "required": "0",
        },
        {
            "name": "no_pose_track_mismatch_as_available",
            "passed": stats.mismatch_available_rows == 0,
            "actual": stats.mismatch_available_rows,
            "required": "0",
        },
        {
            "name": "pose_available_rows_have_provider_metadata",
            "passed": stats.pose_available_missing_provider_rows == 0,
            "actual": stats.pose_available_missing_provider_rows,
            "required": "0",
        },
        {
            "name": "pose_available_rows_have_model_metadata",
            "passed": stats.pose_available_missing_model_rows == 0,
            "actual": stats.pose_available_missing_model_rows,
            "required": "0",
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "summary": summary,
        "checks": checks,
    }


class SequenceStats:
    def __init__(self) -> None:
        self.rows = 0
        self.pose_available_true_rows = 0
        self.pose_confidence_nonzero_rows = 0
        self.quality_counts: Counter[str] = Counter()
        self.rejected_reason_counts: Counter[str] = Counter()
        self.label_counts: Counter[str] = Counter()
        self.dataset_counts: Counter[str] = Counter()
        self.vector_dim_errors = 0
        self.mismatch_available_rows = 0
        self.invalid_quality_rows = 0
        self.pose_available_missing_provider_rows = 0
        self.pose_available_missing_model_rows = 0
        self.pose_provider_counts: Counter[str] = Counter()
        self.pose_model_path_counts: Counter[str] = Counter()

    def summary(self, *, input_dir: Path, files: int) -> dict[str, Any]:
        known_quality_rows = self.rows - self.quality_counts.get("unknown", 0) - self.invalid_quality_rows
        return {
            "input_dir": str(input_dir),
            "jsonl_files": files,
            "rows": self.rows,
            "pose_available_true_rows": self.pose_available_true_rows,
            "pose_available_true_ratio": round(self.pose_available_true_rows / self.rows, 4) if self.rows else 0.0,
            "pose_confidence_nonzero_rows": self.pose_confidence_nonzero_rows,
            "pose_quality_counts": dict(self.quality_counts),
            "pose_rejected_reason_counts": dict(self.rejected_reason_counts),
            "known_pose_quality_ratio": round(known_quality_rows / self.rows, 4) if self.rows else 0.0,
            "invalid_quality_rows": self.invalid_quality_rows,
            "vector_dim_errors": self.vector_dim_errors,
            "mismatch_available_rows": self.mismatch_available_rows,
            "pose_available_missing_provider_rows": self.pose_available_missing_provider_rows,
            "pose_available_missing_model_rows": self.pose_available_missing_model_rows,
            "pose_provider_counts": dict(self.pose_provider_counts),
            "pose_model_path_counts": dict(self.pose_model_path_counts),
            "label_counts": dict(self.label_counts),
            "dataset_counts": dict(self.dataset_counts),
        }


def scan_file(path: Path, *, stats: SequenceStats, expected_input_dim: int) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        stats.rows += 1
        target_feature = row.get("target_feature") if isinstance(row.get("target_feature"), dict) else {}
        vector = row.get("vector") if isinstance(row.get("vector"), list) else []
        if len(vector) != expected_input_dim:
            stats.vector_dim_errors += 1
        pose_available = bool(target_feature.get("pose_available") is True)
        quality = str(target_feature.get("pose_quality_level") or "unknown")
        rejected_reason = target_feature.get("pose_rejected_reason")
        if pose_available:
            stats.pose_available_true_rows += 1
        try:
            if float(target_feature.get("pose_confidence") or 0.0) > 0:
                stats.pose_confidence_nonzero_rows += 1
        except (TypeError, ValueError):
            pass
        stats.quality_counts[quality] += 1
        if quality not in VALID_QUALITY_LEVELS and quality != "unknown":
            stats.invalid_quality_rows += 1
        if rejected_reason:
            stats.rejected_reason_counts[str(rejected_reason)] += 1
        if quality == "pose_track_mismatch" and pose_available:
            stats.mismatch_available_rows += 1
        pose_runtime = row.get("pose_runtime") if isinstance(row.get("pose_runtime"), dict) else {}
        pose_provider = str(pose_runtime.get("pose_provider") or "").strip()
        pose_model_path = str(pose_runtime.get("pose_model_path") or "").strip()
        if pose_provider:
            stats.pose_provider_counts[pose_provider] += 1
        if pose_model_path:
            stats.pose_model_path_counts[pose_model_path] += 1
        if pose_available and not pose_provider:
            stats.pose_available_missing_provider_rows += 1
        if pose_available and not pose_model_path:
            stats.pose_available_missing_model_rows += 1
        stats.label_counts[str(row.get("label") or "unknown")] += 1
        stats.dataset_counts[str(row.get("source_dataset") or "unknown")] += 1


if __name__ == "__main__":
    raise SystemExit(main())
