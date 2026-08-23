from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_temporal_v6_review_sheet import apply_review_sheet
from scripts.build_temporal_v6_lstm_training_manifest import build_manifest as build_lstm_manifest
from scripts.build_temporal_v6_training_dataset import build_dataset, read_jsonl as read_training_jsonl
from scripts.check_temporal_v6_acceptance import check_acceptance
from scripts.validate_temporal_v6_review_seed import validate_rows


DEFAULT_SHEET = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "residual_fn_review_sheet.csv"
DEFAULT_REVIEW = ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"
DEFAULT_SEQUENCE_ROOT = ROOT / "data" / "temporal_sequences_phase6d"
DEFAULT_RESIDUAL_OUTPUT = ROOT / "data" / "temporal_v6_training" / "residual_reviewed"
DEFAULT_LSTM_MANIFEST = ROOT / "data" / "temporal_v6_training" / "lstm_v6_training_manifest.json"
DEFAULT_PIPELINE_SUMMARY = ROOT / "data" / "temporal_v6_training" / "post_review_pipeline_summary.json"
DEFAULT_SLOW_FALL = ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_stride8" / "temporal_v6_regression_comparison.json"
DEFAULT_FP = ROOT / "evaluations" / "fall_temporal_v6" / "fp_regression_stride8" / "temporal_v6_regression_comparison.json"
DEFAULT_UR_MINI = ROOT / "evaluations" / "fall_temporal_v6" / "ur_mini_regression_stride4" / "temporal_v6_regression_comparison.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run temporal v6 post-review preparation pipeline.")
    parser.add_argument("--sheet", default=str(DEFAULT_SHEET), help="Professor review CSV sheet.")
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="Review JSONL source of truth.")
    parser.add_argument("--sequence-root", default=str(DEFAULT_SEQUENCE_ROOT), help="Frame-level temporal sequence root.")
    parser.add_argument("--residual-output-dir", default=str(DEFAULT_RESIDUAL_OUTPUT), help="Reviewed residual output dir.")
    parser.add_argument("--lstm-manifest", default=str(DEFAULT_LSTM_MANIFEST), help="LSTM v6 training manifest output.")
    parser.add_argument("--summary", default=str(DEFAULT_PIPELINE_SUMMARY), help="Pipeline summary output JSON.")
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument("--dry-run", action="store_true", help="Do not write review JSONL updates.")
    args = parser.parse_args()

    result = run_pipeline(
        sheet_path=Path(args.sheet),
        review_path=Path(args.review),
        sequence_root=Path(args.sequence_root),
        residual_output_dir=Path(args.residual_output_dir),
        lstm_manifest_path=Path(args.lstm_manifest),
        summary_path=Path(args.summary),
        fps=args.fps,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "error" else 0


def run_pipeline(
    *,
    sheet_path: Path,
    review_path: Path,
    sequence_root: Path,
    residual_output_dir: Path,
    lstm_manifest_path: Path,
    summary_path: Path,
    fps: float,
    dry_run: bool,
) -> dict[str, Any]:
    apply_result = apply_review_sheet(
        sheet_path=sheet_path,
        input_path=review_path,
        output_path=review_path,
        dry_run=dry_run,
    )
    if apply_result["validation"]["error_count"]:
        result = pipeline_result(
            status="error",
            ready_for_training=False,
            apply_result=apply_result,
            validation=apply_result["validation"],
            dataset=None,
            lstm_manifest=None,
            acceptance=None,
            summary_path=summary_path,
            dry_run=dry_run,
            reason="review_sheet_validation_failed",
        )
        write_summary(summary_path, result)
        return result

    review_rows = read_training_jsonl(review_path)
    validation = validate_rows(review_rows, source=review_path)
    dataset = build_dataset(
        review_rows=review_rows,
        sequence_root=sequence_root,
        output_dir=residual_output_dir,
        fps=fps,
        review_path=review_path,
    )
    write_summary(residual_output_dir / "dataset_summary.json", dataset)
    lstm_manifest = build_lstm_manifest(
        base_dirs=[
            sequence_root / "gmdcsa24",
            sequence_root / "ur_fall",
            sequence_root / "ur_fall_cam1",
        ],
        residual_dir=residual_output_dir,
        output_path=lstm_manifest_path,
        model_version="v6",
        epochs=20,
        stride=4,
    )
    write_summary(lstm_manifest_path, lstm_manifest)
    acceptance = check_acceptance(
        slow_fall_path=DEFAULT_SLOW_FALL,
        fp_path=DEFAULT_FP,
        ur_mini_path=DEFAULT_UR_MINI,
        min_slow_fall_recall=0.80,
        max_fp=0,
        max_duplicates=0,
        max_ur_mini_fp=0,
    )
    write_summary(ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_acceptance_gate.json", acceptance)

    ready_for_training = (
        validation["error_count"] == 0
        and dataset["trainable_review_rows"] > 0
        and dataset["written_sequences"] == dataset["trainable_review_rows"]
        and not dataset["missing_sequences"]
    )
    reason = "ready_for_lstm_training" if ready_for_training else "no_reviewed_residual_training_rows"
    result = pipeline_result(
        status="ok",
        ready_for_training=ready_for_training,
        apply_result=apply_result,
        validation=validation,
        dataset=dataset,
        lstm_manifest=lstm_manifest,
        acceptance=acceptance,
        summary_path=summary_path,
        dry_run=dry_run,
        reason=reason,
    )
    write_summary(summary_path, result)
    return result


def pipeline_result(
    *,
    status: str,
    ready_for_training: bool,
    apply_result: dict[str, Any],
    validation: dict[str, Any],
    dataset: dict[str, Any] | None,
    lstm_manifest: dict[str, Any] | None,
    acceptance: dict[str, Any] | None,
    summary_path: Path,
    dry_run: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "dry_run": dry_run,
        "ready_for_training": ready_for_training,
        "summary": str(summary_path.resolve()),
        "apply_review_sheet": summarize_apply(apply_result),
        "review_validation": summarize_validation(validation),
        "reviewed_training_dataset": summarize_dataset(dataset),
        "lstm_training_manifest": summarize_lstm_manifest(lstm_manifest),
        "acceptance_gate": summarize_acceptance(acceptance),
        "next_step": next_step(ready_for_training, acceptance),
    }


def summarize_apply(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "changed_count": result.get("changed_count"),
        "changed_videos": result.get("changed_videos") or [],
        "missing_in_sheet": result.get("missing_in_sheet") or [],
        "written": result.get("written"),
    }


def summarize_validation(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        "row_count": validation.get("row_count"),
        "usable_for_training_count": validation.get("usable_for_training_count"),
        "error_count": validation.get("error_count"),
        "warning_count": validation.get("warning_count"),
        "status_counts": validation.get("status_counts"),
        "review_decision_counts": validation.get("review_decision_counts"),
    }


def summarize_dataset(dataset: dict[str, Any] | None) -> dict[str, Any] | None:
    if dataset is None:
        return None
    return {
        "trainable_review_rows": dataset.get("trainable_review_rows"),
        "written_sequences": dataset.get("written_sequences"),
        "missing_sequences": dataset.get("missing_sequences") or [],
        "frame_rows": dataset.get("frame_rows"),
        "fall_frame_rows": dataset.get("fall_frame_rows"),
        "train_inputs_manifest": dataset.get("train_inputs_manifest"),
    }


def summarize_lstm_manifest(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if manifest is None:
        return None
    return {
        "trainable_input_count": manifest.get("trainable_input_count"),
        "residual_reviewed_input_count": manifest.get("residual_reviewed_input_count"),
        "label_counts": manifest.get("label_counts"),
        "train_command": manifest.get("train_command"),
    }


def summarize_acceptance(acceptance: dict[str, Any] | None) -> dict[str, Any] | None:
    if acceptance is None:
        return None
    return {
        "passed": acceptance.get("passed"),
        "slow_fall_recall": (acceptance.get("summary") or {}).get("slow_fall_recall"),
        "checks": acceptance.get("checks") or [],
    }


def next_step(ready_for_training: bool, acceptance: dict[str, Any] | None) -> str:
    if not ready_for_training:
        return "Complete professor/manual review and rerun this pipeline."
    if acceptance and acceptance.get("passed"):
        return "Acceptance already passes; confirm model/runtime provenance before promotion."
    return "Train fall_lstm_v6 from the manifest, rerun regression, then rerun acceptance gate."


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
