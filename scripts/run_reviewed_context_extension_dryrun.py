from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.temporal.feature_vectorizer import FeatureVectorizer


DEFAULT_OUTPUT_DIR = ROOT / "data" / "temporal_v6_training" / "reviewed_context_extension_dryrun_20260705"
REVIEWED_DIR = ROOT / "data" / "temporal_v6_training" / "residual_reviewed" / "ur_fall"
BASE_DIR = ROOT / "data" / "temporal_sequences_phase6d" / "ur_fall"
SHORT_VIDEOS = ["fall-08", "fall-20", "fall-24"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2.5 reviewed context-extension dry-run.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    result = run_dryrun(output_dir=Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_dryrun(*, output_dir: Path) -> dict[str, Any]:
    schema = FeatureVectorizer().schema().model_dump()
    window_size = int(schema["window_size"])
    rows: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []

    for stem in SHORT_VIDEOS:
        reviewed_path = REVIEWED_DIR / f"{stem}.jsonl"
        base_path = BASE_DIR / f"{stem}.jsonl"
        reviewed_rows = read_jsonl(reviewed_path)
        base_rows = read_jsonl(base_path)

        if len(reviewed_rows) != len(base_rows):
            real_context_extension_available = True
            max_real_extra_rows = max(0, len(base_rows) - len(reviewed_rows))
        else:
            real_context_extension_available = False
            max_real_extra_rows = 0

        real_len = len(reviewed_rows)
        deficit = max(0, window_size - real_len)
        fall_rows = [row for row in reviewed_rows if row.get("label") == "fall"]
        pre_event_rows = [row for row in reviewed_rows if row.get("label") != "fall"]
        first_fall_frame = int(fall_rows[0]["frame_seq"]) if fall_rows else None
        last_fall_frame = int(fall_rows[-1]["frame_seq"]) if fall_rows else None
        synthetic_ratio = deficit / window_size if window_size else 0.0

        none_strategy = build_strategy(
            video_id=f"ur_fall/{stem}.mp4",
            strategy="none",
            real_sequence_length=real_len,
            window_size=window_size,
            added_left_rows=0,
            added_right_rows=0,
            total_length_after_extension=real_len,
            total_windows=0 if real_len < window_size else max(0, ((real_len - window_size) // 4) + 1),
            positive_train_windows=0 if real_len < window_size else 1,
            real_frame_ratio=real_len / window_size if window_size else 0.0,
            synthetic_frame_ratio=0.0,
            event_coverage=real_len >= window_size,
            warning="too_short_for_current_window" if real_len < window_size else "",
            recommendation="not_enough_without_extension" if real_len < window_size else "usable_without_extension",
        )
        left_pad_strategy = build_strategy(
            video_id=f"ur_fall/{stem}.mp4",
            strategy="left_edge_pad_to_window_size",
            real_sequence_length=real_len,
            window_size=window_size,
            added_left_rows=deficit,
            added_right_rows=0,
            total_length_after_extension=window_size,
            total_windows=1,
            positive_train_windows=1,
            real_frame_ratio=real_len / window_size if window_size else 0.0,
            synthetic_frame_ratio=synthetic_ratio,
            event_coverage=True,
            warning=padding_warning(stem, synthetic_ratio),
            recommendation=padding_recommendation(stem, synthetic_ratio),
        )
        symmetric_strategy = build_strategy(
            video_id=f"ur_fall/{stem}.mp4",
            strategy="symmetric_edge_pad_to_window_size",
            real_sequence_length=real_len,
            window_size=window_size,
            added_left_rows=deficit // 2,
            added_right_rows=deficit - (deficit // 2),
            total_length_after_extension=window_size,
            total_windows=1,
            positive_train_windows=1,
            real_frame_ratio=real_len / window_size if window_size else 0.0,
            synthetic_frame_ratio=synthetic_ratio,
            event_coverage=True,
            warning=padding_warning(stem, synthetic_ratio),
            recommendation=padding_recommendation(stem, synthetic_ratio),
        )

        options.extend([none_strategy, left_pad_strategy, symmetric_strategy])
        rows.append(
            {
                "video_id": f"ur_fall/{stem}.mp4",
                "reviewed_jsonl_path": relative_to_root(reviewed_path),
                "base_jsonl_path": relative_to_root(base_path),
                "real_sequence_length": real_len,
                "window_size": window_size,
                "missing_rows_to_window": deficit,
                "real_context_extension_available": real_context_extension_available,
                "max_real_extra_rows_from_source_sequence": max_real_extra_rows,
                "pre_event_row_count": len(pre_event_rows),
                "fall_row_count": len(fall_rows),
                "first_frame_seq": int(reviewed_rows[0]["frame_seq"]) if reviewed_rows else None,
                "last_frame_seq": int(reviewed_rows[-1]["frame_seq"]) if reviewed_rows else None,
                "first_fall_frame_seq": first_fall_frame,
                "last_fall_frame_seq": last_fall_frame,
                "best_candidate_strategy": best_strategy_name(stem, synthetic_ratio),
                "best_candidate_positive_train_windows": 1 if deficit > 0 else none_strategy["positive_train_windows"],
                "best_candidate_real_frame_ratio": round(real_len / window_size, 4) if window_size else 0.0,
                "best_candidate_synthetic_frame_ratio": round(synthetic_ratio, 4),
                "recommended_next_action": recommended_next_action(stem, synthetic_ratio),
            }
        )

    summary = {
        "status": "ok",
        "phase": "phase2_5_context_extension_dryrun",
        "window_size": window_size,
        "reviewed_short_sequences": len(rows),
        "real_context_extension_available_count": sum(1 for row in rows if row["real_context_extension_available"]),
        "all_short_sequences_lack_real_context_extension": all(not row["real_context_extension_available"] for row in rows),
        "left_pad_candidates": [row["video_id"] for row in rows if row["best_candidate_strategy"] == "left_edge_pad_to_window_size"],
        "defer_candidates": [row["video_id"] for row in rows if row["recommended_next_action"] == "defer_until_longer_real_context_or_feature_branch"],
        "notes": [
            "This is a dry-run forecast only.",
            "No reviewed file was edited.",
            "No training manifest was generated.",
            "No training or evaluation was executed.",
            "Real context extension from current source sequence is unavailable for all three short reviewed samples.",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "context_extension_forecast.csv", rows)
    write_csv(output_dir / "context_extension_options.csv", options)
    write_json(output_dir / "context_extension_dryrun_summary.json", summary)
    (output_dir / "context_extension_dryrun_report.md").write_text(
        build_report(rows=rows, options=options, summary=summary),
        encoding="utf-8",
    )
    return {
        "output_dir": str(output_dir.resolve()),
        "summary_path": str((output_dir / "context_extension_dryrun_summary.json").resolve()),
        "forecast_path": str((output_dir / "context_extension_forecast.csv").resolve()),
    }


def build_strategy(
    *,
    video_id: str,
    strategy: str,
    real_sequence_length: int,
    window_size: int,
    added_left_rows: int,
    added_right_rows: int,
    total_length_after_extension: int,
    total_windows: int,
    positive_train_windows: int,
    real_frame_ratio: float,
    synthetic_frame_ratio: float,
    event_coverage: bool,
    warning: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "strategy": strategy,
        "real_sequence_length": real_sequence_length,
        "window_size": window_size,
        "added_left_rows": added_left_rows,
        "added_right_rows": added_right_rows,
        "total_length_after_extension": total_length_after_extension,
        "total_windows": total_windows,
        "positive_train_windows": positive_train_windows,
        "real_frame_ratio": round(real_frame_ratio, 4),
        "synthetic_frame_ratio": round(synthetic_frame_ratio, 4),
        "event_covered_by_positive_window": event_coverage,
        "warning": warning,
        "recommendation": recommendation,
    }


def padding_warning(stem: str, synthetic_ratio: float) -> str:
    if stem == "fall-24":
        return "heavy_padding_required"
    if synthetic_ratio >= 0.5:
        return "padding_ratio_high"
    return "padding_required"


def padding_recommendation(stem: str, synthetic_ratio: float) -> str:
    if stem == "fall-24":
        return "defer_until_longer_real_context_or_feature_branch"
    if synthetic_ratio >= 0.5:
        return "reviewed_only_padding_experiment_with_caution"
    return "reviewed_only_padding_candidate"


def best_strategy_name(stem: str, synthetic_ratio: float) -> str:
    if stem == "fall-24":
        return "left_edge_pad_to_window_size"
    return "left_edge_pad_to_window_size"


def recommended_next_action(stem: str, synthetic_ratio: float) -> str:
    if stem == "fall-24":
        return "defer_until_longer_real_context_or_feature_branch"
    if synthetic_ratio >= 0.5:
        return "allow_reviewed_only_padding_trial_before_phase3"
    return "allow_reviewed_only_padding_trial_before_phase3"


def build_report(*, rows: list[dict[str, Any]], options: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Reviewed Context Extension Dry-Run",
        "",
        "## Summary",
        "",
        f"- window_size: `{summary['window_size']}`",
        f"- reviewed short sequences: `{summary['reviewed_short_sequences']}`",
        f"- all_short_sequences_lack_real_context_extension: `{summary['all_short_sequences_lack_real_context_extension']}`",
        "",
        "## Forecast",
        "",
        "| video_id | real_sequence_length | missing_rows_to_window | best_candidate_strategy | recommended_next_action |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['video_id']}` | {row['real_sequence_length']} | {row['missing_rows_to_window']} | `{row['best_candidate_strategy']}` | `{row['recommended_next_action']}` |"
        )
    lines.extend(
        [
            "",
            "## Note",
            "",
            "- No real additional context exists in the current source sequence files for these reviewed samples.",
            "- Any immediate extension path would be synthetic padding, not true neighboring frames.",
            "",
        ]
    )
    return "\n".join(lines)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


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


def relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
