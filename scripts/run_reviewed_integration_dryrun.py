from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.temporal.feature_vectorizer import FeatureVectorizer


DEFAULT_OUTPUT_DIR = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705"
DEFAULT_MANIFEST = ROOT / "data" / "temporal_v6_training" / "lstm_v6_training_manifest.json"
DEFAULT_REVIEWED_INPUTS = ROOT / "data" / "temporal_v6_training" / "residual_reviewed" / "train_inputs.json"
DEFAULT_REVIEWED_SUMMARY = ROOT / "data" / "temporal_v6_training" / "residual_reviewed" / "dataset_summary.json"
EVAL_MANIFESTS = {
    "slow_fall_review": ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_manifest.json",
    "fp_regression": ROOT / "evaluations" / "fall_temporal_v6" / "fp_regression_manifest.json",
    "ur_mini": ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_ur_mini_manifest.json",
}
REVIEWED_VIDEO_IDS = {
    "ur_fall/fall-05.mp4",
    "ur_fall/fall-08.mp4",
    "ur_fall/fall-20.mp4",
    "ur_fall/fall-24.mp4",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run reviewed replacement integration and leakage audit.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--reviewed-inputs", default=str(DEFAULT_REVIEWED_INPUTS))
    parser.add_argument("--reviewed-summary", default=str(DEFAULT_REVIEWED_SUMMARY))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--stride", type=int, default=4)
    args = parser.parse_args()

    result = run_dryrun(
        manifest_path=Path(args.manifest),
        reviewed_inputs_path=Path(args.reviewed_inputs),
        reviewed_summary_path=Path(args.reviewed_summary),
        output_dir=Path(args.output_dir),
        seed=args.seed,
        stride=args.stride,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_dryrun(
    *,
    manifest_path: Path,
    reviewed_inputs_path: Path,
    reviewed_summary_path: Path,
    output_dir: Path,
    seed: int,
    stride: int,
) -> dict[str, Any]:
    schema = FeatureVectorizer().schema().model_dump()
    window_size = int(schema["window_size"])

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewed_inputs_payload = json.loads(reviewed_inputs_path.read_text(encoding="utf-8"))
    reviewed_summary = json.loads(reviewed_summary_path.read_text(encoding="utf-8"))

    manifest_input_paths = [resolve_path(ROOT, item) for item in manifest["input_files"]]
    reviewed_input_paths = [resolve_path(reviewed_inputs_path.parent, item) for item in reviewed_inputs_payload["input_files"]]

    reviewed_info_by_video = reviewed_summary_by_video(reviewed_summary)
    reviewed_video_to_input = {
        infer_video_id_from_training_path(path): path for path in reviewed_input_paths
    }

    replacement_rows, replacement_metadata = build_replacement_mapping(
        manifest_input_paths=manifest_input_paths,
        reviewed_input_paths=reviewed_input_paths,
        reviewed_info_by_video=reviewed_info_by_video,
        window_size=window_size,
        stride=stride,
    )

    excluded_base_paths = {item["base_jsonl_path_abs"] for item in replacement_metadata.values()}
    candidate_input_paths = [path for path in manifest_input_paths if str(path) not in excluded_base_paths]

    candidate_sequence_rows, active_sequence_summary = load_candidate_sequences(
        input_paths=candidate_input_paths,
        reviewed_metadata=replacement_metadata,
    )
    assign_candidate_splits(candidate_sequence_rows, seed=seed)
    window_rows, window_summary = build_window_summary(
        candidate_sequence_rows=candidate_sequence_rows,
        reviewed_metadata=replacement_metadata,
        window_size=window_size,
        stride=stride,
    )
    split_rows, split_summary = build_split_forecast(
        candidate_sequence_rows=candidate_sequence_rows,
        reviewed_metadata=replacement_metadata,
    )
    no_leak = build_no_leak_audit(
        candidate_sequence_rows=candidate_sequence_rows,
        reviewed_metadata=replacement_metadata,
        eval_manifests=EVAL_MANIFESTS,
    )

    summary = {
        "status": "ok",
        "phase": "phase2_dryrun",
        "recommended_plan": "hybrid",
        "replacement_mode": "reviewed_replacement_primary",
        "window_size": window_size,
        "stride": stride,
        "base_input_count_before": sum(
            1 for path in manifest_input_paths if "residual_reviewed" not in str(path)
        ),
        "base_input_count_after_replacement": sum(
            1 for path in candidate_input_paths if "residual_reviewed" not in str(path)
        ),
        "reviewed_replacement_count": len(replacement_metadata),
        "excluded_base_sequence_count": sum(len(meta["base_sequence_keys"]) for meta in replacement_metadata.values()),
        "excluded_base_input_count": len(excluded_base_paths),
        "candidate_trainable_input_count": len(candidate_input_paths),
        "confirmed_fall_train_count": len(replacement_metadata),
        "confirmed_fall_but_detection_issue_excluded_count": 5,
        "reviewed_replacement_mapping_completed": all(not row["mapping_warning_requires_manual_confirmation"] for row in replacement_rows),
        "mapping_requires_manual_confirmation": any(row["mapping_warning_requires_manual_confirmation"] for row in replacement_rows),
        "sequence_key_collision_resolved_in_candidate": no_leak["no_base_reviewed_duplicate_passed"],
        "forecast_by_video": {
            row["video_id"]: {
                "train_windows": row["train_windows"],
                "positive_train_windows": row["positive_train_windows"],
                "warning": row["warning"],
            }
            for row in window_rows
        },
        "fall_24_still_too_short": next(
            (row["too_short_for_window"] for row in window_rows if row["video_id"] == "ur_fall/fall-24.mp4"),
            None,
        ),
        "no_leak_train_val_test_passed": no_leak["no_leak_train_val_test_passed"],
        "train_eval_overlap_count": no_leak["train_eval_overlap_count"],
        "gate_interpretation_after_repair": no_leak["gate_interpretation_after_repair"],
        "phase3_recommendation": (
            "ready_for_phase3_candidate_manifest_dry_build"
            if no_leak["no_base_reviewed_duplicate_passed"]
            else "phase3_blocked_by_duplicate_or_mapping_issue"
        ),
        "notes": [
            "No formal training manifest was generated or overwritten.",
            "No model training or candidate evaluation was executed.",
            "Current slow-fall review set overlaps with reviewed-train videos after repair and should be interpreted as post_review_recall_audit.",
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "reviewed_replacement_mapping.csv", replacement_rows)
    write_csv(output_dir / "window_contribution_forecast.csv", window_rows)
    write_csv(output_dir / "split_forecast.csv", split_rows)
    write_json(output_dir / "split_summary.json", split_summary)
    write_json(output_dir / "no_leak_audit.json", no_leak)
    write_json(output_dir / "reviewed_integration_dryrun_summary.json", summary)
    report_text = build_report(
        summary=summary,
        replacement_rows=replacement_rows,
        window_rows=window_rows,
        no_leak=no_leak,
        manifest_path=manifest_path,
        reviewed_inputs_path=reviewed_inputs_path,
        reviewed_summary_path=reviewed_summary_path,
    )
    (output_dir / "reviewed_integration_dryrun_report.md").write_text(report_text, encoding="utf-8")

    return {
        "output_dir": str(output_dir.resolve()),
        "summary_path": str((output_dir / "reviewed_integration_dryrun_summary.json").resolve()),
        "report_path": str((output_dir / "reviewed_integration_dryrun_report.md").resolve()),
        "replacement_rows": len(replacement_rows),
        "window_rows": len(window_rows),
        "no_leak_train_val_test_passed": no_leak["no_leak_train_val_test_passed"],
        "sequence_key_collision_resolved_in_candidate": no_leak["no_base_reviewed_duplicate_passed"],
    }


def reviewed_summary_by_video(reviewed_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    info: dict[str, dict[str, Any]] = {}
    for item in reviewed_summary.get("outputs", []):
        video_id = str(item.get("video_id") or "")
        if video_id:
            info[video_id] = item
    return info


def build_replacement_mapping(
    *,
    manifest_input_paths: list[Path],
    reviewed_input_paths: list[Path],
    reviewed_info_by_video: dict[str, dict[str, Any]],
    window_size: int,
    stride: int,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    reviewed_paths_by_video = {
        infer_video_id_from_training_path(path): path for path in reviewed_input_paths
    }
    base_paths_by_video = {
        infer_video_id_from_training_path(path): path
        for path in manifest_input_paths
        if "residual_reviewed" not in str(path)
    }

    replacement_rows: list[dict[str, Any]] = []
    replacement_metadata: dict[str, dict[str, Any]] = {}

    for video_id in sorted(REVIEWED_VIDEO_IDS):
        reviewed_path = reviewed_paths_by_video.get(video_id)
        base_path = base_paths_by_video.get(video_id)
        if reviewed_path is None or base_path is None:
            raise SystemExit(f"missing reviewed/base path mapping for {video_id}")

        reviewed_rows = read_jsonl_rows(reviewed_path)
        base_rows = read_jsonl_rows(base_path)
        reviewed_by_key = rows_by_sequence_key(reviewed_rows)
        base_by_key = rows_by_sequence_key(base_rows)
        reviewed_keys = sorted(reviewed_by_key)
        base_keys = sorted(base_by_key)

        if reviewed_keys != base_keys:
            raise SystemExit(f"sequence key mismatch for {video_id}: reviewed={reviewed_keys}, base={base_keys}")

        info = reviewed_info_by_video.get(video_id, {})
        multi_track_warning = "multi_track_video_replacement_all_matching_sequence_keys" if len(reviewed_keys) > 1 else ""
        replacement_group = f"reviewed_residual::{video_id.replace('/', '::')}"
        replacement_metadata[video_id] = {
            "video_id": video_id,
            "reviewed_jsonl_path": str(reviewed_path),
            "base_jsonl_path": str(base_path),
            "base_jsonl_path_abs": str(base_path.resolve()),
            "reviewed_sequence_keys": reviewed_keys,
            "base_sequence_keys": base_keys,
            "source_type": "residual_reviewed_replacement",
            "force_split": "train",
            "replacement_group": replacement_group,
            "replacement_reason": "professor_review_confirmed_fall_train",
            "event_frames": info.get("event_frames") or {},
            "event_time_range_ms": {
                "fall_start_ms": safe_nested(info, ["event_frames", "fall_start_frame"]),
                "ground_contact_start_ms": None,
                "low_posture_start_ms": None,
                "motion_end_ms": None,
            },
        }

        for sequence_key in reviewed_keys:
            reviewed_count = len(reviewed_by_key[sequence_key])
            base_count = len(base_by_key[sequence_key])
            replacement_rows.append(
                {
                    "video_id": video_id,
                    "reviewed_jsonl_path": relative_to_root(reviewed_path),
                    "reviewed_sequence_key": sequence_key,
                    "base_jsonl_path": relative_to_root(base_path),
                    "base_sequence_key": sequence_key,
                    "base_rows": base_count,
                    "reviewed_rows": reviewed_count,
                    "replacement_action": "exclude_base_include_reviewed",
                    "replacement_reason": "professor_review_confirmed_fall_train",
                    "source_type": "residual_reviewed_replacement",
                    "force_split": "train",
                    "replacement_group": replacement_group,
                    "mapping_confidence": "high",
                    "mapping_warning": multi_track_warning,
                    "mapping_warning_requires_manual_confirmation": False,
                    "window_size": window_size,
                    "stride": stride,
                }
            )

    return replacement_rows, replacement_metadata


def load_candidate_sequences(
    *,
    input_paths: list[Path],
    reviewed_metadata: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    summary_rows: list[dict[str, Any]] = []
    for path in input_paths:
        rows = read_jsonl_rows(path)
        video_id = infer_video_id_from_training_path(path)
        metadata = reviewed_metadata.get(video_id)
        for row in rows:
            if row.get("usable_for_training") is False:
                continue
            enriched = dict(row)
            enriched["_input_path"] = str(path.resolve())
            enriched["_source_video_id"] = video_id
            if metadata is not None:
                enriched["source_type"] = metadata["source_type"]
                enriched["source_video_id"] = video_id
                enriched["source_sequence_key"] = row.get("sequence_key")
                enriched["replaced_base_sequence_key"] = row.get("sequence_key")
                enriched["reviewed_source_sequence_key"] = row.get("sequence_key")
                enriched["replacement_reason"] = metadata["replacement_reason"]
                enriched["replacement_group"] = metadata["replacement_group"]
                enriched["reviewed_train_priority"] = True
                enriched["force_split"] = metadata["force_split"]
                enriched["split"] = metadata["force_split"]
            else:
                enriched["source_type"] = "base"
                enriched["source_video_id"] = video_id
                enriched["reviewed_train_priority"] = False
            by_key[str(enriched["sequence_key"])].append(enriched)
        summary_rows.append(
            {
                "input_path": relative_to_root(path),
                "video_id": video_id,
                "source_type": metadata["source_type"] if metadata else "base",
            }
        )
    return by_key, summary_rows


def assign_candidate_splits(candidate_sequence_rows: dict[str, list[dict[str, Any]]], seed: int) -> None:
    grouped: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for key, rows in candidate_sequence_rows.items():
        group = rows[0].get("replacement_group") or rows[0].get("split_group") or key
        grouped[str(group)].append(rows)

    groups = sorted(grouped)
    random.Random(seed).shuffle(groups)
    train_cut = max(1, math.ceil(len(groups) * 0.7))
    val_cut = max(train_cut, math.ceil(len(groups) * 0.85))
    split_by_group: dict[str, str] = {}
    for index, group in enumerate(groups):
        if index < train_cut:
            split = "train"
        elif index < val_cut:
            split = "val"
        else:
            split = "test"
        split_by_group[group] = split

    for group, row_sets in grouped.items():
        for rows in row_sets:
            for row in rows:
                force_split = row.get("force_split")
                if force_split:
                    row["split"] = force_split
                elif row.get("split") in {None, "", "unassigned"}:
                    row["split"] = split_by_group[group]


def build_window_summary(
    *,
    candidate_sequence_rows: dict[str, list[dict[str, Any]]],
    reviewed_metadata: dict[str, dict[str, Any]],
    window_size: int,
    stride: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    totals = Counter()
    for video_id in sorted(reviewed_metadata):
        relevant_keys = reviewed_metadata[video_id]["reviewed_sequence_keys"]
        all_rows: list[dict[str, Any]] = []
        per_sequence = []
        for key in relevant_keys:
            seq_rows = sorted(candidate_sequence_rows[key], key=lambda item: int(item["frame_seq"]))
            seq_len = len(seq_rows)
            total_windows = 0
            positive_windows = 0
            train_windows = 0
            val_windows = 0
            test_windows = 0
            positive_train_windows = 0
            event_cover = False
            if seq_len >= window_size:
                for start in range(0, seq_len - window_size + 1, stride):
                    window = seq_rows[start : start + window_size]
                    label = 1 if any(item.get("label") == "fall" for item in window) else 0
                    split = str(window[0].get("split") or "train")
                    total_windows += 1
                    positive_windows += label
                    train_windows += 1 if split == "train" else 0
                    val_windows += 1 if split == "val" else 0
                    test_windows += 1 if split == "test" else 0
                    positive_train_windows += 1 if split == "train" and label else 0
                    if label:
                        event_cover = True
            per_sequence.append(
                {
                    "sequence_key": key,
                    "sequence_length": seq_len,
                    "total_windows": total_windows,
                    "positive_windows": positive_windows,
                    "train_windows": train_windows,
                    "val_windows": val_windows,
                    "test_windows": test_windows,
                    "positive_train_windows": positive_train_windows,
                    "too_short_for_window": seq_len < window_size,
                    "event_covered_by_positive_windows": event_cover,
                }
            )
            all_rows.extend(seq_rows)

        all_rows.sort(key=lambda item: (item["sequence_key"], int(item["frame_seq"])))
        total_windows = sum(item["total_windows"] for item in per_sequence)
        positive_windows = sum(item["positive_windows"] for item in per_sequence)
        train_windows = sum(item["train_windows"] for item in per_sequence)
        val_windows = sum(item["val_windows"] for item in per_sequence)
        test_windows = sum(item["test_windows"] for item in per_sequence)
        positive_train_windows = sum(item["positive_train_windows"] for item in per_sequence)
        too_short = all(item["too_short_for_window"] for item in per_sequence)
        warning = ""
        if video_id == "ur_fall/fall-05.mp4":
            warning = "multi_track_reviewed_replacement_but_all_active_rows_forced_to_train"
        if total_windows == 0 and too_short:
            short_warning = "sequence_length_below_window_size; recommend_context_extension_before_training"
            warning = f"{warning}|{short_warning}".strip("|")
        rows.append(
            {
                "video_id": video_id,
                "sequence_key": "|".join(relevant_keys),
                "source_sequence_key": "|".join(relevant_keys),
                "sequence_length": sum(item["sequence_length"] for item in per_sequence),
                "window_size": window_size,
                "stride": stride,
                "total_windows": total_windows,
                "positive_windows": positive_windows,
                "train_windows": train_windows,
                "val_windows": val_windows,
                "test_windows": test_windows,
                "positive_train_windows": positive_train_windows,
                "too_short_for_window": too_short,
                "event_frame_range": event_frame_range_text(all_rows),
                "event_time_range_ms": event_time_range_text(all_rows),
                "event_covered_by_positive_windows": any(item["event_covered_by_positive_windows"] for item in per_sequence),
                "expected_effective_train_contribution": positive_train_windows,
                "warning": warning,
            }
        )
        totals["total_windows"] += total_windows
        totals["positive_windows"] += positive_windows
        totals["positive_train_windows"] += positive_train_windows

    return rows, dict(totals)


def build_split_forecast(
    *,
    candidate_sequence_rows: dict[str, list[dict[str, Any]]],
    reviewed_metadata: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    split_counts = Counter()
    video_to_splits: dict[str, set[str]] = defaultdict(set)
    sequence_to_splits: dict[str, set[str]] = defaultdict(set)

    for key, seq_rows in sorted(candidate_sequence_rows.items()):
        ordered = sorted(seq_rows, key=lambda item: int(item["frame_seq"]))
        first = ordered[0]
        split = str(first.get("split") or "train")
        video_id = str(first.get("source_video_id") or "")
        rows.append(
            {
                "sequence_key": key,
                "source_video_id": video_id,
                "split": split,
                "source_type": first.get("source_type"),
                "force_split": first.get("force_split") or "",
                "replacement_group": first.get("replacement_group") or first.get("split_group") or key,
                "reviewed_train_priority": bool(first.get("reviewed_train_priority")),
                "input_path": relative_to_root(Path(first["_input_path"])),
            }
        )
        split_counts[split] += 1
        video_to_splits[video_id].add(split)
        sequence_to_splits[key].add(split)

    summary = {
        "split_counts": dict(split_counts),
        "source_video_ids_in_multiple_splits": {k: sorted(v) for k, v in video_to_splits.items() if len(v) > 1},
        "sequence_keys_in_multiple_splits": {k: sorted(v) for k, v in sequence_to_splits.items() if len(v) > 1},
        "reviewed_force_split_train_passed": all(
            row["split"] == "train"
            for row in rows
            if row["source_type"] == "residual_reviewed_replacement"
        ),
    }
    return rows, summary


def build_no_leak_audit(
    *,
    candidate_sequence_rows: dict[str, list[dict[str, Any]]],
    reviewed_metadata: dict[str, dict[str, Any]],
    eval_manifests: dict[str, Path],
) -> dict[str, Any]:
    split_to_video_ids: dict[str, set[str]] = defaultdict(set)
    split_to_sequence_keys: dict[str, set[str]] = defaultdict(set)
    base_reviewed_duplicates = []

    for key, seq_rows in candidate_sequence_rows.items():
        first = seq_rows[0]
        split = str(first.get("split") or "train")
        video_id = str(first.get("source_video_id") or "")
        split_to_video_ids[split].add(video_id)
        split_to_sequence_keys[split].add(key)

    train_val_overlap = sorted(split_to_video_ids["train"] & split_to_video_ids["val"])
    train_test_overlap = sorted(split_to_video_ids["train"] & split_to_video_ids["test"])
    val_test_overlap = sorted(split_to_video_ids["val"] & split_to_video_ids["test"])
    sequence_train_val_overlap = sorted(split_to_sequence_keys["train"] & split_to_sequence_keys["val"])
    sequence_train_test_overlap = sorted(split_to_sequence_keys["train"] & split_to_sequence_keys["test"])
    sequence_val_test_overlap = sorted(split_to_sequence_keys["val"] & split_to_sequence_keys["test"])

    reviewed_train_video_ids = {
        str(rows[0].get("source_video_id") or "")
        for rows in candidate_sequence_rows.values()
        if rows and str(rows[0].get("source_type") or "") == "residual_reviewed_replacement" and str(rows[0].get("split") or "train") == "train"
    }
    train_video_ids = split_to_video_ids["train"]
    eval_overlap: dict[str, list[str]] = {}
    reviewed_total_overlap = set()
    for name, path in eval_manifests.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        eval_video_ids = {str(item.get("video_id") or "") for item in payload.get("videos", [])}
        overlap = sorted(reviewed_train_video_ids & eval_video_ids)
        eval_overlap[name] = overlap
        reviewed_total_overlap.update(overlap)

    for key, rows in candidate_sequence_rows.items():
        source_types = {str(row.get("source_type") or "") for row in rows}
        if "base" in source_types and "residual_reviewed_replacement" in source_types:
            base_reviewed_duplicates.append(key)

    return {
        "no_leak_train_val_test_passed": not (
            train_val_overlap or train_test_overlap or val_test_overlap or sequence_train_val_overlap or sequence_train_test_overlap or sequence_val_test_overlap
        ),
        "train_val_overlap_video_ids": train_val_overlap,
        "train_test_overlap_video_ids": train_test_overlap,
        "val_test_overlap_video_ids": val_test_overlap,
        "train_val_overlap_sequence_keys": sequence_train_val_overlap,
        "train_test_overlap_sequence_keys": sequence_train_test_overlap,
        "val_test_overlap_sequence_keys": sequence_val_test_overlap,
        "no_base_reviewed_duplicate_passed": not base_reviewed_duplicates,
        "base_reviewed_duplicate_active_overlap": base_reviewed_duplicates,
        "reviewed_train_in_slow_fall_review_eval_overlap": eval_overlap["slow_fall_review"],
        "reviewed_train_in_fp_regression_eval_overlap": eval_overlap["fp_regression"],
        "reviewed_train_in_ur_mini_eval_overlap": eval_overlap["ur_mini"],
        "train_eval_overlap_count": len(reviewed_total_overlap),
        "overlapping_eval_video_ids": sorted(reviewed_total_overlap),
        "gate_interpretation_after_repair": (
            "post_review_recall_audit_not_pure_heldout" if eval_overlap["slow_fall_review"] else "heldout_candidate_eval"
        ),
    }


def build_report(
    *,
    summary: dict[str, Any],
    replacement_rows: list[dict[str, Any]],
    window_rows: list[dict[str, Any]],
    no_leak: dict[str, Any],
    manifest_path: Path,
    reviewed_inputs_path: Path,
    reviewed_summary_path: Path,
) -> str:
    lines = [
        "# Reviewed Integration Dry-Run Report",
        "",
        "## Inputs",
        "",
        f"- manifest: `{relative_to_root(manifest_path)}`",
        f"- reviewed inputs: `{relative_to_root(reviewed_inputs_path)}`",
        f"- reviewed summary: `{relative_to_root(reviewed_summary_path)}`",
        "",
        "## Candidate Summary",
        "",
        f"- reviewed replacement mapping completed: `{summary['reviewed_replacement_mapping_completed']}`",
        f"- sequence_key collision resolved in dry-run candidate: `{summary['sequence_key_collision_resolved_in_candidate']}`",
        f"- candidate trainable input count: `{summary['candidate_trainable_input_count']}`",
        f"- excluded base input count: `{summary['excluded_base_input_count']}`",
        f"- gate interpretation after repair: `{summary['gate_interpretation_after_repair']}`",
        "",
        "## Reviewed Replacement Forecast",
        "",
        "| video_id | train_windows | positive_train_windows | warning |",
        "| --- | ---: | ---: | --- |",
    ]
    for row in window_rows:
        lines.append(
            f"| `{row['video_id']}` | {row['train_windows']} | {row['positive_train_windows']} | {row['warning'] or ''} |"
        )
    lines.extend(
        [
            "",
            "## No-Leak Audit",
            "",
            f"- no_leak_train_val_test_passed: `{no_leak['no_leak_train_val_test_passed']}`",
            f"- no_base_reviewed_duplicate_passed: `{no_leak['no_base_reviewed_duplicate_passed']}`",
            f"- train_eval_overlap_count: `{no_leak['train_eval_overlap_count']}`",
            f"- overlapping_eval_video_ids: `{', '.join(no_leak['overlapping_eval_video_ids'])}`",
            "",
            "## Notes",
            "",
            "- This is a dry-run only.",
            "- No formal manifest was generated.",
            "- No training, evaluation, threshold, or runtime changes were performed.",
            "",
        ]
    )
    return "\n".join(lines)


def read_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def rows_by_sequence_key(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row["sequence_key"])].append(row)
    return result


def resolve_path(base_dir: Path, item: str) -> Path:
    path = Path(str(item))
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def infer_video_id_from_training_path(path: Path) -> str:
    rel = path.resolve().relative_to(ROOT.resolve())
    parts = list(rel.parts)
    filename = Path(parts[-1]).stem + ".mp4"
    if "ur_fall" in parts:
        return f"ur_fall/{filename}"
    if "ur_fall_cam1" in parts:
        return f"ur_fall_cam1/{filename}"
    if "gmdcsa24" in parts:
        return f"gmdcsa24/{filename}"
    return filename


def relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


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


def event_frame_range_text(rows: list[dict[str, Any]]) -> str:
    starts = []
    ends = []
    for row in rows:
        frames = row.get("review_event_frames")
        if isinstance(frames, dict):
            start = frames.get("fall_start_frame")
            end = frames.get("motion_end_frame")
            if isinstance(start, int):
                starts.append(start)
            if isinstance(end, int):
                ends.append(end)
    if not starts:
        return ""
    return f"{min(starts)}-{max(ends) if ends else max(starts)}"


def event_time_range_text(rows: list[dict[str, Any]]) -> str:
    starts = []
    ends = []
    for row in rows:
        times = row.get("review_event_times_ms")
        if isinstance(times, dict):
            start = times.get("fall_start_ms")
            end = times.get("motion_end_ms")
            if isinstance(start, (int, float)):
                starts.append(int(start))
            if isinstance(end, (int, float)):
                ends.append(int(end))
    if not starts:
        return ""
    return f"{min(starts)}-{max(ends) if ends else max(starts)}"


def safe_nested(payload: dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


if __name__ == "__main__":
    raise SystemExit(main())
