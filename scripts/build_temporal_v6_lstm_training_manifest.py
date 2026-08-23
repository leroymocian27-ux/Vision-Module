from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_DIRS = [
    ROOT / "data" / "temporal_sequences_phase6d" / "gmdcsa24",
    ROOT / "data" / "temporal_sequences_phase6d" / "ur_fall",
    ROOT / "data" / "temporal_sequences_phase6d" / "ur_fall_cam1",
]
DEFAULT_RESIDUAL_DIR = ROOT / "data" / "temporal_v6_training" / "residual_reviewed"
DEFAULT_OUTPUT = ROOT / "data" / "temporal_v6_training" / "lstm_v6_training_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reproducible temporal v6 LSTM training input manifest.")
    parser.add_argument(
        "--base-dir",
        action="append",
        default=None,
        help="Directory containing base frame-level temporal JSONL files. Can be repeated.",
    )
    parser.add_argument(
        "--residual-dir",
        default=str(DEFAULT_RESIDUAL_DIR),
        help="Directory produced by build_temporal_v6_training_dataset.py.",
    )
    parser.add_argument(
        "--skip-residual",
        action="store_true",
        help="Use only base temporal sequence files. Intended for pose smoke checks or when residual data has not been regenerated.",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output manifest JSON path.")
    parser.add_argument("--model-version", default="v6", help="Model version suffix for command hints.")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--require-pose", action="store_true", help="Require pose-aware sequence rows for pose LSTM training.")
    parser.add_argument("--min-pose-available-ratio", type=float, default=0.05)
    parser.add_argument("--min-known-pose-quality-ratio", type=float, default=0.95)
    args = parser.parse_args()

    base_dirs = [Path(item) for item in args.base_dir] if args.base_dir else list(DEFAULT_BASE_DIRS)
    residual_dir = Path(args.residual_dir)
    output_path = Path(args.output)
    manifest = build_manifest(
        base_dirs=base_dirs,
        residual_dir=residual_dir,
        output_path=output_path,
        model_version=args.model_version,
        epochs=args.epochs,
        stride=args.stride,
        require_pose=args.require_pose,
        include_residual=not args.skip_residual,
        min_pose_available_ratio=args.min_pose_available_ratio,
        min_known_pose_quality_ratio=args.min_known_pose_quality_ratio,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if args.require_pose and not manifest["pose_training_gate"]["passed"]:
        return 1
    return 0


def build_manifest(
    *,
    base_dirs: list[Path],
    residual_dir: Path,
    output_path: Path,
    model_version: str,
    epochs: int,
    stride: int,
    require_pose: bool = False,
    include_residual: bool = True,
    min_pose_available_ratio: float = 0.05,
    min_known_pose_quality_ratio: float = 0.95,
) -> dict[str, Any]:
    base_inputs = collect_jsonl_files(base_dirs)
    residual_inputs = collect_residual_inputs(residual_dir) if include_residual else []
    all_inputs = dedupe_paths(base_inputs + residual_inputs)
    summaries = [summarize_sequence(path) for path in all_inputs]

    skipped_unusable = [item for item in summaries if item["usable_rows"] <= 0]
    trainable = [item for item in summaries if item["usable_rows"] > 0]
    schema_versions = sorted({str(item.get("schema_version") or "unknown") for item in trainable})
    schema_hashes = sorted({str(item.get("schema_hash") or "unknown") for item in trainable})
    label_counts: dict[str, int] = {}
    subtype_counts: dict[str, int] = {}
    for item in trainable:
        add_counts(label_counts, item["label_counts"])
        add_counts(subtype_counts, item["subtype_counts"])
    pose_training_gate = build_pose_training_gate(
        trainable,
        require_pose=require_pose,
        min_pose_available_ratio=min_pose_available_ratio,
        min_known_pose_quality_ratio=min_known_pose_quality_ratio,
    )

    relative_inputs = [relative_path(Path(item["path"]), ROOT) for item in trainable]
    command = train_command(
        output_path,
        has_inputs=bool(relative_inputs) and (not require_pose or pose_training_gate["passed"]),
        model_version=model_version,
        epochs=epochs,
        stride=stride,
    )
    residual_reviewed_count = sum(1 for item in trainable if item.get("review_source") == "temporal_v6_residual_review")

    return {
        "output": str(output_path.resolve()),
        "base_dirs": [str(path.resolve()) for path in base_dirs],
        "residual_dir": str(residual_dir.resolve()),
        "include_residual": include_residual,
        "base_input_count": len(base_inputs),
        "residual_input_count": len(residual_inputs),
        "trainable_input_count": len(trainable),
        "skipped_unusable_input_count": len(skipped_unusable),
        "residual_reviewed_input_count": residual_reviewed_count,
        "schema_versions": schema_versions,
        "schema_hashes": schema_hashes,
        "label_counts": label_counts,
        "subtype_counts": subtype_counts,
        "require_pose": require_pose,
        "pose_training_gate": pose_training_gate,
        "input_files": relative_inputs,
        "skipped_unusable_inputs": [relative_path(Path(item["path"]), ROOT) for item in skipped_unusable],
        "train_command": command,
        "acceptance_gates_after_training": {
            "slow_fall_review_recall_min": 0.80,
            "fp_regression_confirmed_fp_max": 0,
            "duplicate_alarm_videos_max": 0,
            "ur_mini_confirmed_fp_max": 0,
        },
        "notes": [
            "Regenerate residual reviewed data after professor/manual approval before training.",
            "Do not promote a new ONNX LSTM unless the v6 regression gates pass after export.",
            "For bbox+motion+pose LSTM training, build this manifest with --require-pose after pose temporal sequence validation passes.",
        ],
    }


def collect_jsonl_files(dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in dirs:
        if directory.exists():
            files.extend(sorted(path for path in directory.rglob("*.jsonl") if path.is_file()))
    return files


def collect_residual_inputs(residual_dir: Path) -> list[Path]:
    manifest_path = residual_dir / "train_inputs.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        inputs = []
        for item in payload.get("input_files") or []:
            path = residual_dir / str(item)
            if path.exists():
                inputs.append(path)
        return inputs
    return collect_jsonl_files([residual_dir])


def summarize_sequence(path: Path) -> dict[str, Any]:
    row_count = 0
    usable_rows = 0
    label_counts: dict[str, int] = {}
    subtype_counts: dict[str, int] = {}
    schema_version = None
    schema_hash = None
    review_source = None
    pose_available_true_rows = 0
    pose_quality_counts: dict[str, int] = {}
    pose_rejected_reason_counts: dict[str, int] = {}
    pose_provider_counts: dict[str, int] = {}
    pose_model_path_counts: dict[str, int] = {}
    pose_device_counts: dict[str, int] = {}
    pose_available_missing_provider_rows = 0
    pose_available_missing_model_rows = 0
    mismatch_available_rows = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            row_count += 1
            schema_version = schema_version or row.get("schema_version")
            schema_hash = schema_hash or row.get("schema_hash")
            review_source = review_source or row.get("review_source")
            if row.get("usable_for_training") is False:
                continue
            usable_rows += 1
            label = str(row.get("label") or "unknown")
            subtype = str(row.get("non_fall_subtype") or row.get("fall_subtype") or label)
            label_counts[label] = label_counts.get(label, 0) + 1
            subtype_counts[subtype] = subtype_counts.get(subtype, 0) + 1
            target_feature = row.get("target_feature") if isinstance(row.get("target_feature"), dict) else {}
            pose_available = bool(target_feature.get("pose_available") is True)
            quality = str(target_feature.get("pose_quality_level") or "unknown")
            rejected_reason = target_feature.get("pose_rejected_reason")
            if pose_available:
                pose_available_true_rows += 1
            pose_quality_counts[quality] = pose_quality_counts.get(quality, 0) + 1
            if rejected_reason:
                reason = str(rejected_reason)
                pose_rejected_reason_counts[reason] = pose_rejected_reason_counts.get(reason, 0) + 1
            if quality == "pose_track_mismatch" and pose_available:
                mismatch_available_rows += 1
            pose_runtime = row.get("pose_runtime") if isinstance(row.get("pose_runtime"), dict) else {}
            pose_provider = str(pose_runtime.get("pose_provider") or "").strip()
            pose_model_path = str(pose_runtime.get("pose_model_path") or "").strip()
            pose_device = str(pose_runtime.get("pose_device") or "").strip()
            if pose_provider:
                pose_provider_counts[pose_provider] = pose_provider_counts.get(pose_provider, 0) + 1
            if pose_model_path:
                pose_model_path_counts[pose_model_path] = pose_model_path_counts.get(pose_model_path, 0) + 1
            if pose_device:
                pose_device_counts[pose_device] = pose_device_counts.get(pose_device, 0) + 1
            if pose_available and not pose_provider:
                pose_available_missing_provider_rows += 1
            if pose_available and not pose_model_path:
                pose_available_missing_model_rows += 1
    return {
        "path": str(path.resolve()),
        "row_count": row_count,
        "usable_rows": usable_rows,
        "label_counts": label_counts,
        "subtype_counts": subtype_counts,
        "schema_version": schema_version,
        "schema_hash": schema_hash,
        "review_source": review_source,
        "pose_available_true_rows": pose_available_true_rows,
        "pose_quality_counts": pose_quality_counts,
        "pose_rejected_reason_counts": pose_rejected_reason_counts,
        "pose_provider_counts": pose_provider_counts,
        "pose_model_path_counts": pose_model_path_counts,
        "pose_device_counts": pose_device_counts,
        "pose_available_missing_provider_rows": pose_available_missing_provider_rows,
        "pose_available_missing_model_rows": pose_available_missing_model_rows,
        "mismatch_available_rows": mismatch_available_rows,
    }


def build_pose_training_gate(
    summaries: list[dict[str, Any]],
    *,
    require_pose: bool,
    min_pose_available_ratio: float,
    min_known_pose_quality_ratio: float,
) -> dict[str, Any]:
    usable_rows = sum(int(item.get("usable_rows") or 0) for item in summaries)
    pose_available_rows = sum(int(item.get("pose_available_true_rows") or 0) for item in summaries)
    quality_counts: dict[str, int] = {}
    rejected_reason_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    model_path_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    mismatch_available_rows = 0
    pose_available_missing_provider_rows = 0
    pose_available_missing_model_rows = 0
    for item in summaries:
        add_counts(quality_counts, item.get("pose_quality_counts") or {})
        add_counts(rejected_reason_counts, item.get("pose_rejected_reason_counts") or {})
        add_counts(provider_counts, item.get("pose_provider_counts") or {})
        add_counts(model_path_counts, item.get("pose_model_path_counts") or {})
        add_counts(device_counts, item.get("pose_device_counts") or {})
        mismatch_available_rows += int(item.get("mismatch_available_rows") or 0)
        pose_available_missing_provider_rows += int(item.get("pose_available_missing_provider_rows") or 0)
        pose_available_missing_model_rows += int(item.get("pose_available_missing_model_rows") or 0)
    unknown_quality_rows = int(quality_counts.get("unknown") or 0)
    known_quality_rows = max(0, usable_rows - unknown_quality_rows)
    pose_available_ratio = pose_available_rows / usable_rows if usable_rows else 0.0
    known_quality_ratio = known_quality_rows / usable_rows if usable_rows else 0.0
    checks = [
        {
            "name": "pose_required",
            "passed": not require_pose or usable_rows > 0,
            "actual": require_pose,
            "required": "usable rows exist when --require-pose is set",
        },
        {
            "name": "pose_available_ratio",
            "passed": (not require_pose) or pose_available_ratio >= min_pose_available_ratio,
            "actual": round(pose_available_ratio, 4),
            "required": f">= {min_pose_available_ratio:.4f}" if require_pose else "not required",
        },
        {
            "name": "known_pose_quality_ratio",
            "passed": (not require_pose) or known_quality_ratio >= min_known_pose_quality_ratio,
            "actual": round(known_quality_ratio, 4),
            "required": f">= {min_known_pose_quality_ratio:.4f}" if require_pose else "not required",
        },
        {
            "name": "no_pose_track_mismatch_as_available",
            "passed": mismatch_available_rows == 0,
            "actual": mismatch_available_rows,
            "required": "0",
        },
        {
            "name": "pose_available_rows_have_provider_metadata",
            "passed": (not require_pose) or pose_available_missing_provider_rows == 0,
            "actual": pose_available_missing_provider_rows,
            "required": "0" if require_pose else "not required",
        },
        {
            "name": "pose_available_rows_have_model_metadata",
            "passed": (not require_pose) or pose_available_missing_model_rows == 0,
            "actual": pose_available_missing_model_rows,
            "required": "0" if require_pose else "not required",
        },
    ]
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "usable_rows": usable_rows,
        "pose_available_true_rows": pose_available_rows,
        "pose_available_true_ratio": round(pose_available_ratio, 4) if usable_rows else 0.0,
        "known_pose_quality_ratio": round(known_quality_ratio, 4) if usable_rows else 0.0,
        "pose_quality_counts": quality_counts,
        "pose_rejected_reason_counts": rejected_reason_counts,
        "pose_provider_counts": provider_counts,
        "pose_model_path_counts": model_path_counts,
        "pose_device_counts": device_counts,
        "pose_available_missing_provider_rows": pose_available_missing_provider_rows,
        "pose_available_missing_model_rows": pose_available_missing_model_rows,
        "mismatch_available_rows": mismatch_available_rows,
    }


def train_command(manifest_path: Path, *, has_inputs: bool, model_version: str, epochs: int, stride: int) -> str | None:
    if not has_inputs:
        return None
    manifest = relative_path(manifest_path, ROOT)
    return (
        f"python scripts\\train_fall_lstm.py --input-manifest {manifest} "
        f"--output-dir models --model-version {model_version} --epochs {epochs} --stride {stride}"
    )


def dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def relative_path(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), start.resolve()).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
