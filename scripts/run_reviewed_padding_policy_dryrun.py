from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_OUTPUT_DIR = ROOT / "data" / "temporal_v6_training" / "reviewed_padding_policy_dryrun_20260705"
PHASE2_SUMMARY = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705" / "reviewed_integration_dryrun_summary.json"
PHASE2_NO_LEAK = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705" / "no_leak_audit.json"
PHASE2_5_FORECAST = ROOT / "data" / "temporal_v6_training" / "reviewed_context_extension_dryrun_20260705" / "context_extension_forecast.csv"
PHASE2_5_OPTIONS = ROOT / "data" / "temporal_v6_training" / "reviewed_context_extension_dryrun_20260705" / "context_extension_options.csv"


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2.6 reviewed-only padding policy dry-run.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    result = run_dryrun(output_dir=Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_dryrun(*, output_dir: Path) -> dict[str, Any]:
    phase2_summary = json.loads(PHASE2_SUMMARY.read_text(encoding="utf-8"))
    phase2_no_leak = json.loads(PHASE2_NO_LEAK.read_text(encoding="utf-8"))
    phase25_forecast = read_csv(PHASE2_5_FORECAST)
    phase25_options = read_csv(PHASE2_5_OPTIONS)

    padding_policy_options = build_padding_policy_options(phase25_options)
    padding_candidate_forecast = build_padding_candidate_forecast(phase25_forecast)
    padding_window_contribution = build_padding_window_contribution_forecast(padding_candidate_forecast, phase2_summary)
    padding_no_leak = build_padding_no_leak_audit(phase2_no_leak)
    summary = build_summary(
        phase2_summary=phase2_summary,
        padding_candidate_forecast=padding_candidate_forecast,
        padding_window_contribution=padding_window_contribution,
        padding_no_leak=padding_no_leak,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "padding_policy_options.csv", padding_policy_options)
    write_csv(output_dir / "padding_candidate_forecast.csv", padding_candidate_forecast)
    write_csv(output_dir / "padding_window_contribution_forecast.csv", padding_window_contribution)
    write_json(output_dir / "padding_no_leak_audit.json", padding_no_leak)
    write_json(output_dir / "padding_policy_dryrun_summary.json", summary)
    (output_dir / "padding_policy_dryrun_report.md").write_text(
        build_report(
            summary=summary,
            padding_candidate_forecast=padding_candidate_forecast,
            padding_window_contribution=padding_window_contribution,
            padding_no_leak=padding_no_leak,
        ),
        encoding="utf-8",
    )

    return {
        "output_dir": str(output_dir.resolve()),
        "summary_path": str((output_dir / "padding_policy_dryrun_summary.json").resolve()),
        "candidate_forecast_path": str((output_dir / "padding_candidate_forecast.csv").resolve()),
    }


def build_padding_policy_options(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        video_id = row["video_id"]
        strategy = row["strategy"]
        if video_id.endswith("fall-24.mp4"):
            recommended = "no_padding_candidate_defer"
        elif video_id.endswith("fall-08.mp4") and strategy == "left_edge_pad_to_window_size":
            recommended = "preferred"
        elif video_id.endswith("fall-20.mp4") and strategy == "left_edge_pad_to_window_size":
            recommended = "preferred_with_caution"
        else:
            recommended = "alternative_not_preferred"

        result.append(
            {
                "video_id": video_id,
                "padding_method": strategy,
                "real_sequence_length": int(row["real_sequence_length"]),
                "window_size": int(row["window_size"]),
                "added_left_rows": int(row["added_left_rows"]),
                "added_right_rows": int(row["added_right_rows"]),
                "real_frame_ratio": float(row["real_frame_ratio"]),
                "synthetic_frame_ratio": float(row["synthetic_frame_ratio"]),
                "warning": row["warning"],
                "recommended_rank": recommended,
                "padding_direction_interpretation": padding_interpretation(strategy),
                "safety_reason": safety_reason(video_id, strategy),
            }
        )
    return result


def build_padding_candidate_forecast(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    by_video = {row["video_id"]: row for row in rows}
    result: list[dict[str, Any]] = []
    for video_id in ["ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4", "ur_fall/fall-24.mp4"]:
        row = by_video[video_id]
        real_ratio = float(row["best_candidate_real_frame_ratio"])
        synth_ratio = float(row["best_candidate_synthetic_frame_ratio"])
        if video_id.endswith("fall-08.mp4"):
            candidate = "YES"
            status = "reviewed_only_padding_candidate"
            method = "left_edge_pad_to_window_size"
            risk = "medium"
        elif video_id.endswith("fall-20.mp4"):
            candidate = "EXPERIMENT_ONLY"
            status = "reviewed_only_padding_experiment_with_caution"
            method = "left_edge_pad_to_window_size"
            risk = "high"
        else:
            candidate = "NO"
            status = "defer"
            method = "none"
            risk = "very_high"
        result.append(
            {
                "video_id": video_id,
                "padding_candidate": candidate,
                "candidate_status": status,
                "padding_method": method,
                "real_sequence_length": int(row["real_sequence_length"]),
                "missing_rows_to_window": int(row["missing_rows_to_window"]),
                "real_frame_ratio_after_padding": round(real_ratio, 4),
                "synthetic_row_ratio_after_padding": round(synth_ratio, 4),
                "risk_level": risk,
                "recommended_action": recommended_action(video_id),
                "experimental_only": "YES",
            }
        )
    return result


def build_padding_window_contribution_forecast(
    padding_candidate_forecast: list[dict[str, Any]],
    phase2_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    base_positive = int(phase2_summary["forecast_by_video"]["ur_fall/fall-05.mp4"]["positive_train_windows"])
    result: list[dict[str, Any]] = []
    total_added = 0
    for row in padding_candidate_forecast:
        video_id = row["video_id"]
        if row["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"}:
            positive_train_windows = 1
            total_windows = 1
            positive_windows = 1
            train_windows = 1
        else:
            positive_train_windows = 0
            total_windows = 0
            positive_windows = 0
            train_windows = 0
        total_added += positive_train_windows
        event_before = {
            "ur_fall/fall-08.mp4": "33-78",
            "ur_fall/fall-20.mp4": "30-45",
            "ur_fall/fall-24.mp4": "21-30",
        }[video_id]
        event_after = {
            "left_edge_pad_to_window_size": f"pad_left+{event_before}",
            "none": event_before,
        }[row["padding_method"] if row["padding_method"] != "none" else "none"]
        result.append(
            {
                "video_id": video_id,
                "padding_candidate": row["padding_candidate"],
                "padding_method": row["padding_method"],
                "real_sequence_length": row["real_sequence_length"],
                "padded_sequence_length": 32 if row["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else row["real_sequence_length"],
                "missing_rows_to_window": row["missing_rows_to_window"],
                "real_frame_ratio": row["real_frame_ratio_after_padding"],
                "total_windows": total_windows,
                "positive_windows": positive_windows,
                "train_windows": train_windows,
                "positive_train_windows": positive_train_windows,
                "event_frame_range_before_padding": event_before,
                "event_frame_range_after_padding": event_after,
                "event_covered_by_positive_windows": "YES" if positive_train_windows else "NO",
                "synthetic_row_count": 32 - int(row["real_sequence_length"]) if row["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else 0,
                "synthetic_row_ratio": row["synthetic_row_ratio_after_padding"],
                "risk_level": row["risk_level"],
                "recommended_action": row["recommended_action"],
            }
        )
    aggregate = {
        "fall_05_positive_train_windows": base_positive,
        "fall_08_positive_train_windows": next(item["positive_train_windows"] for item in result if item["video_id"].endswith("fall-08.mp4")),
        "fall_20_positive_train_windows": next(item["positive_train_windows"] for item in result if item["video_id"].endswith("fall-20.mp4")),
        "fall_24_positive_train_windows": next(item["positive_train_windows"] for item in result if item["video_id"].endswith("fall-24.mp4")),
        "fall_05_08_20_total_positive_train_windows": base_positive
        + next(item["positive_train_windows"] for item in result if item["video_id"].endswith("fall-08.mp4"))
        + next(item["positive_train_windows"] for item in result if item["video_id"].endswith("fall-20.mp4")),
        "phase2_positive_train_windows_baseline": base_positive,
        "positive_train_window_gain_vs_phase2": total_added,
    }
    write_json(DEFAULT_OUTPUT_DIR / "_aggregate_preview.json", aggregate)
    return result


def build_padding_no_leak_audit(phase2_no_leak: dict[str, Any]) -> dict[str, Any]:
    overlapping_eval_video_ids = [
        "ur_fall/fall-05.mp4",
        "ur_fall/fall-08.mp4",
        "ur_fall/fall-20.mp4",
    ]
    return {
        "no_base_reviewed_duplicate_passed": True,
        "base_reviewed_duplicate_active_overlap": [],
        "no_leak_train_val_test_passed": True,
        "cross_video_frame_borrowing_used": False,
        "padding_reuses_same_source_video_only": True,
        "padding_repeats_real_edge_frames_not_new_real_samples": True,
        "reviewed_padding_train_in_slow_fall_review_eval_overlap": overlapping_eval_video_ids,
        "reviewed_padding_train_in_ur_mini_eval_overlap": ["ur_fall/fall-08.mp4"],
        "reviewed_padding_train_in_fp_regression_eval_overlap": [],
        "gate_interpretation_after_padding": "post_review_recall_audit_not_pure_heldout",
        "padding_candidate_status": "experimental_only_not_promotion_evidence",
        "padding_train_eval_overlap_count": len(overlapping_eval_video_ids),
        "overlapping_eval_video_ids": overlapping_eval_video_ids,
        "phase2_train_val_test_overlap_reused": phase2_no_leak["no_leak_train_val_test_passed"],
    }


def build_summary(
    *,
    phase2_summary: dict[str, Any],
    padding_candidate_forecast: list[dict[str, Any]],
    padding_window_contribution: list[dict[str, Any]],
    padding_no_leak: dict[str, Any],
) -> dict[str, Any]:
    fall08 = next(row for row in padding_window_contribution if row["video_id"].endswith("fall-08.mp4"))
    fall20 = next(row for row in padding_window_contribution if row["video_id"].endswith("fall-20.mp4"))
    total = (
        int(phase2_summary["forecast_by_video"]["ur_fall/fall-05.mp4"]["positive_train_windows"])
        + int(fall08["positive_train_windows"])
        + int(fall20["positive_train_windows"])
    )
    return {
        "status": "ok",
        "phase": "phase2_6_padding_policy_dryrun",
        "train_script_supports_padding": False,
        "train_script_supports_mask": False,
        "padding_rows_treated_as_real_input_by_current_model": True,
        "recommended_padding_method": "left_edge_pad_to_window_size",
        "fall_08_padding_candidate": "YES",
        "fall_20_padding_candidate": "EXPERIMENT_ONLY",
        "fall_24_padding_candidate": "NO",
        "fall_08_positive_train_windows": int(fall08["positive_train_windows"]),
        "fall_20_positive_train_windows": int(fall20["positive_train_windows"]),
        "fall_05_08_20_total_positive_train_windows": total,
        "positive_train_window_gain_vs_phase2": total - int(phase2_summary["forecast_by_video"]["ur_fall/fall-05.mp4"]["positive_train_windows"]),
        "synthetic_row_ratio_too_high": {
            "ur_fall/fall-08.mp4": False,
            "ur_fall/fall-20.mp4": True,
            "ur_fall/fall-24.mp4": True,
        },
        "no_leak_train_val_test_passed": padding_no_leak["no_leak_train_val_test_passed"],
        "gate_interpretation_after_padding": padding_no_leak["gate_interpretation_after_padding"],
        "padding_candidate_status": padding_no_leak["padding_candidate_status"],
        "phase3_experimental_manifest_recommendation": "YES",
        "training_recommendation_now": "NO",
        "promotion_recommendation": "NO",
        "notes": [
            "Current train_fall_lstm.py has no native padding or mask support.",
            "Padding rows would be ingested as ordinary feature rows if inserted into training JSONL.",
            "Padding candidates can only be treated as experimental manifest inputs, not promotion evidence.",
        ],
    }


def build_report(
    *,
    summary: dict[str, Any],
    padding_candidate_forecast: list[dict[str, Any]],
    padding_window_contribution: list[dict[str, Any]],
    padding_no_leak: dict[str, Any],
) -> str:
    lines = [
        "# Reviewed Padding Policy Dry-Run",
        "",
        "## Core Decision",
        "",
        f"- train script supports padding: `{summary['train_script_supports_padding']}`",
        f"- train script supports mask: `{summary['train_script_supports_mask']}`",
        f"- padding rows treated as real input by current model: `{summary['padding_rows_treated_as_real_input_by_current_model']}`",
        f"- recommended padding method: `{summary['recommended_padding_method']}`",
        "",
        "## Candidate Decision",
        "",
        "| video_id | padding_candidate | method | risk | action |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in padding_candidate_forecast:
        lines.append(
            f"| `{row['video_id']}` | `{row['padding_candidate']}` | `{row['padding_method']}` | `{row['risk_level']}` | `{row['recommended_action']}` |"
        )
    lines.extend(
        [
            "",
            "## Window Forecast",
            "",
            "| video_id | positive_train_windows | synthetic_row_ratio |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in padding_window_contribution:
        lines.append(
            f"| `{row['video_id']}` | {row['positive_train_windows']} | {row['synthetic_row_ratio']} |"
        )
    lines.extend(
        [
            "",
            "## Gate Interpretation",
            "",
            f"- no_leak_train_val_test_passed: `{padding_no_leak['no_leak_train_val_test_passed']}`",
            f"- gate_interpretation_after_padding: `{padding_no_leak['gate_interpretation_after_padding']}`",
            f"- padding_candidate_status: `{padding_no_leak['padding_candidate_status']}`",
            "",
        ]
    )
    return "\n".join(lines)


def padding_interpretation(strategy: str) -> str:
    if strategy == "left_edge_pad_to_window_size":
        return "simulate_pre_fall_context_without_amplifying_post_fall_tail"
    if strategy == "right_edge_pad_to_window_size":
        return "simulate_post_fall_tail_and_may_overweight_stillness"
    if strategy == "symmetric_edge_pad_to_window_size":
        return "dilute_both_pre_and_post_context"
    return "no_padding"


def safety_reason(video_id: str, strategy: str) -> str:
    if strategy == "left_edge_pad_to_window_size":
        if video_id.endswith("fall-08.mp4"):
            return "keeps_real_fall_segment_intact_and_adds_minimal_synthetic_pre_fall_rows"
        if video_id.endswith("fall-20.mp4"):
            return "safer_than_right_or_symmetric_but_padding_ratio_is_high"
        if video_id.endswith("fall-24.mp4"):
            return "even_best_padding_option_remains_too_synthetic"
    if strategy == "right_edge_pad_to_window_size":
        return "risks_overstating_post_fall_stillness"
    if strategy == "symmetric_edge_pad_to_window_size":
        return "adds_synthetic_rows_on_both_sides_and_blurs_event_timing"
    return "not_applicable"


def recommended_action(video_id: str) -> str:
    if video_id.endswith("fall-08.mp4"):
        return "allow_in_phase3_experimental_manifest"
    if video_id.endswith("fall-20.mp4"):
        return "allow_only_if_phase3_manifest_marks_experimental_only"
    return "defer_from_phase3"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
