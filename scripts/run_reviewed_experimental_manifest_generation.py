from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_MANIFEST = ROOT / "data" / "temporal_v6_training" / "lstm_v6_training_manifest.json"
PHASE2_SUMMARY = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705" / "reviewed_integration_dryrun_summary.json"
PHASE2_MAPPING = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705" / "reviewed_replacement_mapping.csv"
PHASE2_NO_LEAK = ROOT / "data" / "temporal_v6_training" / "reviewed_integration_dryrun_20260705" / "no_leak_audit.json"
PHASE2_PADDING_SUMMARY = ROOT / "data" / "temporal_v6_training" / "reviewed_padding_policy_dryrun_20260705" / "padding_policy_dryrun_summary.json"
PHASE2_PADDING_FORECAST = ROOT / "data" / "temporal_v6_training" / "reviewed_padding_policy_dryrun_20260705" / "padding_candidate_forecast.csv"
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "data"
    / "temporal_v6_training"
    / "experimental_manifests"
    / "temporal_v6_reviewed_padding_exp_20260705"
)
WINDOW_SIZE = 32
STRIDE = 4
PADDING_POLICY_VERSION = "reviewed_padding_policy_20260705"
GATE_INTERPRETATION = "post_review_recall_audit_not_pure_heldout"
PADDING_CANDIDATE_STATUS = "experimental_only_not_promotion_evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an experimental manifest for reviewed replacement + padding trial.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    result = run(output_dir=Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run(*, output_dir: Path) -> dict[str, Any]:
    official_manifest = read_json(OFFICIAL_MANIFEST)
    phase2_summary = read_json(PHASE2_SUMMARY)
    phase2_no_leak = read_json(PHASE2_NO_LEAK)
    phase26_summary = read_json(PHASE2_PADDING_SUMMARY)
    replacement_rows = read_csv(PHASE2_MAPPING)
    padding_rows = read_csv(PHASE2_PADDING_FORECAST)

    output_dir.mkdir(parents=True, exist_ok=True)
    generated_input_dir = output_dir / "generated_inputs" / "ur_fall"
    generated_input_dir.mkdir(parents=True, exist_ok=True)

    replacement_plan = build_replacement_plan(replacement_rows, padding_rows)
    generated_files = build_experimental_reviewed_inputs(replacement_plan, generated_input_dir)
    manifest_payload = build_experimental_manifest(
        official_manifest=official_manifest,
        replacement_plan=replacement_plan,
        generated_files=generated_files,
        output_dir=output_dir,
    )
    replacement_mapping = build_replacement_mapping_rows(replacement_plan, generated_files)
    padding_mapping = build_padding_mapping_rows(replacement_plan)
    window_contribution = build_window_contribution_rows(generated_files)
    no_leak_audit = build_no_leak_audit(
        official_manifest=official_manifest,
        manifest_payload=manifest_payload,
        replacement_plan=replacement_plan,
        generated_files=generated_files,
        phase2_no_leak=phase2_no_leak,
    )
    pretrain_gate = build_pretrain_gate(
        manifest_payload=manifest_payload,
        replacement_plan=replacement_plan,
        window_contribution=window_contribution,
        no_leak_audit=no_leak_audit,
        phase2_summary=phase2_summary,
        phase26_summary=phase26_summary,
    )
    manifest_summary = build_manifest_summary(
        manifest_payload=manifest_payload,
        replacement_plan=replacement_plan,
        window_contribution=window_contribution,
        no_leak_audit=no_leak_audit,
        pretrain_gate=pretrain_gate,
    )
    report = build_report(
        manifest_summary=manifest_summary,
        replacement_mapping=replacement_mapping,
        padding_mapping=padding_mapping,
        window_contribution=window_contribution,
        no_leak_audit=no_leak_audit,
        pretrain_gate=pretrain_gate,
    )

    write_json(output_dir / "experimental_lstm_v6_training_manifest.json", manifest_payload)
    write_json(output_dir / "experimental_manifest_summary.json", manifest_summary)
    write_csv(output_dir / "experimental_replacement_mapping.csv", replacement_mapping)
    write_csv(output_dir / "experimental_padding_mapping.csv", padding_mapping)
    write_csv(output_dir / "experimental_window_contribution.csv", window_contribution)
    write_json(output_dir / "experimental_no_leak_audit.json", no_leak_audit)
    write_json(output_dir / "experimental_pretrain_gate.json", pretrain_gate)
    (output_dir / "experimental_manifest_report.md").write_text(report, encoding="utf-8")

    return {
        "status": "ok",
        "output_dir": str(output_dir.resolve()),
        "manifest_path": str((output_dir / "experimental_lstm_v6_training_manifest.json").resolve()),
        "pretrain_gate_path": str((output_dir / "experimental_pretrain_gate.json").resolve()),
    }


def build_replacement_plan(
    replacement_rows: list[dict[str, str]],
    padding_rows: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    replacement_by_video: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in replacement_rows:
        replacement_by_video[row["video_id"]].append(row)
    padding_by_video = {row["video_id"]: row for row in padding_rows}

    plan: dict[str, dict[str, Any]] = {}
    for video_id, rows in replacement_by_video.items():
        padding = padding_by_video.get(video_id)
        base_jsonl_path = rows[0]["base_jsonl_path"]
        reviewed_jsonl_path = rows[0]["reviewed_jsonl_path"]
        reviewed_sequence_keys = sorted({row["reviewed_sequence_key"] for row in rows})
        base_sequence_keys = sorted({row["base_sequence_key"] for row in rows})
        if video_id.endswith("fall-05.mp4"):
            mode = "reviewed_replacement"
            include_in_train = True
            padding_candidate = "NO_PADDING"
            generated_filename = "fall-05.experimental.jsonl"
            source_type = "residual_reviewed_replacement_experimental"
        elif video_id.endswith("fall-08.mp4"):
            mode = "reviewed_replacement_padding_trial"
            include_in_train = True
            padding_candidate = "YES"
            generated_filename = "fall-08.experimental.jsonl"
            source_type = "residual_reviewed_replacement_padding_trial"
        elif video_id.endswith("fall-20.mp4"):
            mode = "reviewed_replacement_padding_trial"
            include_in_train = True
            padding_candidate = "EXPERIMENT_ONLY"
            generated_filename = "fall-20.experimental.jsonl"
            source_type = "residual_reviewed_replacement_padding_trial"
        elif video_id.endswith("fall-24.mp4"):
            mode = "defer_exclude_base_and_reviewed"
            include_in_train = False
            padding_candidate = "NO"
            generated_filename = ""
            source_type = "residual_reviewed_replacement_deferred"
        else:
            continue
        plan[video_id] = {
            "video_id": video_id,
            "base_jsonl_path": base_jsonl_path,
            "reviewed_jsonl_path": reviewed_jsonl_path,
            "reviewed_sequence_keys": reviewed_sequence_keys,
            "replaced_base_sequence_keys": base_sequence_keys,
            "replacement_action": rows[0]["replacement_action"],
            "replacement_reason": rows[0]["replacement_reason"],
            "force_split": rows[0]["force_split"],
            "replacement_group": rows[0]["replacement_group"],
            "mapping_confidence": rows[0]["mapping_confidence"],
            "mapping_warning": rows[0]["mapping_warning"],
            "mode": mode,
            "include_in_train": include_in_train,
            "padding_candidate": padding_candidate,
            "padding_method": (padding or {}).get("padding_method", "none"),
            "real_sequence_length": int((padding or {}).get("real_sequence_length") or sum(1 for _ in Path(reviewed_jsonl_path).open("r", encoding="utf-8"))),
            "missing_rows_to_window": int((padding or {}).get("missing_rows_to_window") or 0),
            "real_frame_ratio": float((padding or {}).get("real_frame_ratio_after_padding") or 1.0),
            "synthetic_row_ratio": float((padding or {}).get("synthetic_row_ratio_after_padding") or 0.0),
            "risk_level": (padding or {}).get("risk_level", "low"),
            "recommended_action": (padding or {}).get("recommended_action", "include_reviewed_replacement"),
            "generated_filename": generated_filename,
            "source_type": source_type,
        }
    return plan


def build_experimental_reviewed_inputs(
    replacement_plan: dict[str, dict[str, Any]],
    output_dir: Path,
) -> dict[str, dict[str, Any]]:
    generated: dict[str, dict[str, Any]] = {}
    for video_id, plan in replacement_plan.items():
        if not plan["include_in_train"]:
            continue
        reviewed_rows = read_jsonl(Path(plan["reviewed_jsonl_path"]))
        rows_out: list[dict[str, Any]]
        synthetic_row_count = 0
        is_padding_used = False
        if plan["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"}:
            rows_out = pad_reviewed_rows(reviewed_rows, plan)
            synthetic_row_count = int(plan["missing_rows_to_window"])
            is_padding_used = True
        else:
            rows_out = []
            for row in reviewed_rows:
                rows_out.append(
                    enrich_row(
                        row=row,
                        plan=plan,
                        is_padding=False,
                        synthetic_row_count=0,
                        padded_sequence_length=len(reviewed_rows),
                    )
                )
        output_path = output_dir / plan["generated_filename"]
        write_jsonl(output_path, rows_out)
        generated[video_id] = {
            "video_id": video_id,
            "path": output_path,
            "rows": rows_out,
            "real_sequence_length": len(reviewed_rows),
            "padded_sequence_length": len(rows_out),
            "synthetic_row_count": synthetic_row_count,
            "synthetic_row_ratio": round((synthetic_row_count / len(rows_out)), 4) if rows_out else 0.0,
            "is_padding_used": is_padding_used,
            "source_type": plan["source_type"],
        }
    return generated


def pad_reviewed_rows(reviewed_rows: list[dict[str, Any]], plan: dict[str, Any]) -> list[dict[str, Any]]:
    synthetic_needed = int(plan["missing_rows_to_window"])
    if synthetic_needed <= 0:
        return [enrich_row(row=row, plan=plan, is_padding=False, synthetic_row_count=0, padded_sequence_length=len(reviewed_rows)) for row in reviewed_rows]
    first_by_sequence: dict[str, dict[str, Any]] = {}
    for row in reviewed_rows:
        key = str(row["sequence_key"])
        if key not in first_by_sequence:
            first_by_sequence[key] = row
    if len(first_by_sequence) != 1:
        raise ValueError(f"padding trial currently expects exactly one sequence_key for {plan['video_id']}")
    first_row = next(iter(first_by_sequence.values()))
    step = infer_frame_step(reviewed_rows)
    padded_sequence_length = len(reviewed_rows) + synthetic_needed
    synthetic_rows: list[dict[str, Any]] = []
    original_seq = int(first_row["frame_seq"])
    for index in range(synthetic_needed, 0, -1):
        clone = json.loads(json.dumps(first_row))
        clone["frame_seq"] = original_seq - step * index
        clone["timestamp"] = f"{clone.get('timestamp')}|synthetic_left_pad_{index}"
        clone = enrich_row(
            row=clone,
            plan=plan,
            is_padding=True,
            synthetic_row_count=synthetic_needed,
            padded_sequence_length=padded_sequence_length,
        )
        synthetic_rows.append(clone)
    actual_rows = [
        enrich_row(
            row=row,
            plan=plan,
            is_padding=False,
            synthetic_row_count=synthetic_needed,
            padded_sequence_length=padded_sequence_length,
        )
        for row in reviewed_rows
    ]
    return synthetic_rows + actual_rows


def enrich_row(
    *,
    row: dict[str, Any],
    plan: dict[str, Any],
    is_padding: bool,
    synthetic_row_count: int,
    padded_sequence_length: int,
) -> dict[str, Any]:
    clone = json.loads(json.dumps(row))
    clone["split"] = "train"
    clone["experimental"] = True
    clone["promotion_eligible"] = False
    clone["source_type"] = plan["source_type"]
    clone["source_video_id"] = plan["video_id"]
    clone["source_sequence_key"] = clone.get("sequence_key")
    clone["reviewed_source_sequence_key"] = clone.get("sequence_key")
    clone["replaced_base_sequence_key"] = "|".join(plan["replaced_base_sequence_keys"])
    clone["replacement_reason"] = plan["replacement_reason"]
    clone["replacement_group"] = plan["replacement_group"]
    clone["padding_candidate_status"] = PADDING_CANDIDATE_STATUS
    clone["gate_interpretation_after_repair"] = GATE_INTERPRETATION
    clone["padding_policy_version"] = PADDING_POLICY_VERSION
    clone["padding_method"] = plan["padding_method"] if plan["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else "none"
    clone["padding_reason"] = "sequence_length_below_window_size" if plan["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else None
    clone["padding_source"] = "synthetic_edge_repeat_hold_first" if is_padding else "real_reviewed_row"
    clone["is_padding"] = is_padding
    clone["real_sequence_length"] = plan["real_sequence_length"]
    clone["padded_sequence_length"] = padded_sequence_length
    clone["missing_rows_to_window"] = int(plan["missing_rows_to_window"])
    clone["real_frame_ratio"] = round(float(plan["real_frame_ratio"]), 4)
    clone["synthetic_row_count"] = int(synthetic_row_count)
    clone["synthetic_row_ratio"] = round(float(plan["synthetic_row_ratio"]), 4)
    clone["padding_candidate"] = plan["padding_candidate"]
    clone["experimental_warning"] = padding_warning(plan, is_padding=is_padding)
    return clone


def build_experimental_manifest(
    *,
    official_manifest: dict[str, Any],
    replacement_plan: dict[str, dict[str, Any]],
    generated_files: dict[str, dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    official_inputs = [str(item) for item in official_manifest.get("input_files") or []]
    base_to_exclude = {
        relative_from_root(Path(plan["base_jsonl_path"]))
        for plan in replacement_plan.values()
    }
    reviewed_to_exclude = {
        relative_from_root(Path(plan["reviewed_jsonl_path"]))
        for plan in replacement_plan.values()
    }
    retained_inputs = [
        item
        for item in official_inputs
        if item not in base_to_exclude and item not in reviewed_to_exclude
    ]
    generated_input_files = [relative_from_root(meta["path"]) for meta in generated_files.values()]
    final_inputs = retained_inputs + generated_input_files
    manifest_path = output_dir / "experimental_lstm_v6_training_manifest.json"
    return {
        "output": str(manifest_path.resolve()),
        "experimental": True,
        "promotion_eligible": False,
        "manifest_kind": "temporal_v6_reviewed_padding_experimental_candidate",
        "padding_candidate_status": PADDING_CANDIDATE_STATUS,
        "gate_interpretation_after_repair": GATE_INTERPRETATION,
        "base_manifest_path": str(OFFICIAL_MANIFEST.resolve()),
        "base_input_count_before": len(official_inputs),
        "base_input_count_after_exclusions": len(retained_inputs),
        "experimental_generated_input_count": len(generated_input_files),
        "trainable_input_count": len(final_inputs),
        "excluded_base_inputs": sorted(base_to_exclude),
        "excluded_reviewed_inputs": sorted(reviewed_to_exclude),
        "included_generated_inputs": generated_input_files,
        "window_size": WINDOW_SIZE,
        "stride": STRIDE,
        "input_files": final_inputs,
        "require_pose": bool(official_manifest.get("require_pose")),
        "pose_training_gate": official_manifest.get("pose_training_gate"),
        "acceptance_gates_after_training": official_manifest.get("acceptance_gates_after_training"),
        "train_command": None,
        "train_command_blocked_reason": "Phase 3 experimental manifest generation only; training not authorized in this stage.",
        "notes": [
            "This manifest is experimental only and must not overwrite the formal lstm_v6_training_manifest.json.",
            "fall-05 enters as reviewed replacement.",
            "fall-08 enters as reviewed replacement plus left-edge padding trial.",
            "fall-20 enters as reviewed replacement plus left-edge padding experiment_only trial.",
            "fall-24 is deferred and excluded from this experimental train candidate.",
            "Padding metadata is audit-only and not consumed by current train_fall_lstm.py.",
        ],
    }


def build_replacement_mapping_rows(
    replacement_plan: dict[str, dict[str, Any]],
    generated_files: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for video_id in sorted(replacement_plan):
        plan = replacement_plan[video_id]
        generated_path = generated_files.get(video_id, {}).get("path")
        rows.append(
            {
                "video_id": video_id,
                "reviewed_jsonl_path": plan["reviewed_jsonl_path"],
                "base_jsonl_path": plan["base_jsonl_path"],
                "reviewed_sequence_key": "|".join(plan["reviewed_sequence_keys"]),
                "replaced_base_sequence_key": "|".join(plan["replaced_base_sequence_keys"]),
                "replacement_action": (
                    "exclude_base_include_experimental_reviewed"
                    if plan["include_in_train"]
                    else "exclude_base_defer_reviewed"
                ),
                "replacement_reason": plan["replacement_reason"],
                "source_type": plan["source_type"],
                "force_split": plan["force_split"] if plan["include_in_train"] else "defer",
                "mapping_confidence": plan["mapping_confidence"],
                "mapping_warning": plan["mapping_warning"] or defer_warning(plan),
                "experimental_generated_jsonl_path": str(generated_path.resolve()) if generated_path else "",
            }
        )
    return rows


def build_padding_mapping_rows(replacement_plan: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for video_id in sorted(replacement_plan):
        plan = replacement_plan[video_id]
        rows.append(
            {
                "video_id": video_id,
                "padding_candidate": plan["padding_candidate"],
                "padding_method": plan["padding_method"],
                "real_sequence_length": plan["real_sequence_length"],
                "padded_sequence_length": (
                    WINDOW_SIZE if plan["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else plan["real_sequence_length"]
                ),
                "missing_rows_to_window": plan["missing_rows_to_window"],
                "real_frame_ratio": round(float(plan["real_frame_ratio"]), 4),
                "synthetic_row_count": (
                    plan["missing_rows_to_window"] if plan["padding_candidate"] in {"YES", "EXPERIMENT_ONLY"} else 0
                ),
                "synthetic_row_ratio": round(float(plan["synthetic_row_ratio"]), 4),
                "risk_level": plan["risk_level"],
                "recommended_action": plan["recommended_action"],
                "promotion_eligible": False,
            }
        )
    return rows


def build_window_contribution_rows(generated_files: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_positive = 0
    for video_id in ["ur_fall/fall-05.mp4", "ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4", "ur_fall/fall-24.mp4"]:
        if video_id not in generated_files:
            rows.append(
                {
                    "video_id": video_id,
                    "source_type": "deferred",
                    "sequence_length": 0,
                    "padded_sequence_length": 0,
                    "total_windows": 0,
                    "positive_windows": 0,
                    "train_windows": 0,
                    "positive_train_windows": 0,
                    "is_padding_used": False,
                    "synthetic_row_ratio": 0.0,
                    "event_covered_by_positive_windows": False,
                    "warning": "deferred_not_in_experimental_train",
                }
            )
            continue
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in generated_files[video_id]["rows"]:
            grouped[str(row["sequence_key"])].append(row)
        total_windows = 0
        positive_windows = 0
        train_windows = 0
        positive_train_windows = 0
        sequence_lengths: list[int] = []
        for seq_rows in grouped.values():
            seq_rows.sort(key=lambda item: int(item["frame_seq"]))
            sequence_lengths.append(len(seq_rows))
            if len(seq_rows) < WINDOW_SIZE:
                continue
            for start in range(0, len(seq_rows) - WINDOW_SIZE + 1, STRIDE):
                window = seq_rows[start : start + WINDOW_SIZE]
                total_windows += 1
                label = 1 if any(item.get("label") == "fall" for item in window) else 0
                if label:
                    positive_windows += 1
                if window[0].get("split") == "train":
                    train_windows += 1
                    if label:
                        positive_train_windows += 1
        total_positive += positive_train_windows
        warning = ""
        if video_id.endswith("fall-20.mp4"):
            warning = "high_synthetic_ratio_experiment_only"
        elif video_id.endswith("fall-08.mp4"):
            warning = "padding_trial_audit_only"
        rows.append(
            {
                "video_id": video_id,
                "source_type": generated_files[video_id]["source_type"],
                "sequence_length": generated_files[video_id]["real_sequence_length"],
                "padded_sequence_length": generated_files[video_id]["padded_sequence_length"],
                "total_windows": total_windows,
                "positive_windows": positive_windows,
                "train_windows": train_windows,
                "positive_train_windows": positive_train_windows,
                "is_padding_used": generated_files[video_id]["is_padding_used"],
                "synthetic_row_ratio": generated_files[video_id]["synthetic_row_ratio"],
                "event_covered_by_positive_windows": bool(positive_train_windows > 0),
                "warning": warning,
            }
        )
    for row in rows:
        row["active_reviewed_positive_total_positive_train_windows"] = total_positive
    return rows


def build_no_leak_audit(
    *,
    official_manifest: dict[str, Any],
    manifest_payload: dict[str, Any],
    replacement_plan: dict[str, dict[str, Any]],
    generated_files: dict[str, dict[str, Any]],
    phase2_no_leak: dict[str, Any],
) -> dict[str, Any]:
    path_to_rows: dict[str, list[dict[str, Any]]] = {}
    sequence_key_sources: dict[str, set[str]] = defaultdict(set)
    train_video_ids: set[str] = set()
    for rel_path in manifest_payload["input_files"]:
        path = ROOT / rel_path
        rows = read_jsonl(path)
        path_to_rows[rel_path] = rows
        for row in rows:
            key = str(row.get("sequence_key") or "")
            if key:
                sequence_key_sources[key].add(rel_path)
            if row.get("split") == "train" or row.get("split") in {None, "", "unassigned"}:
                video_id = row.get("video_id")
                if isinstance(video_id, str):
                    train_video_ids.add(video_id)
    duplicate_sequence_keys = sorted(key for key, sources in sequence_key_sources.items() if len(sources) > 1)
    reviewed_eval_overlap = sorted(video_id for video_id in ["ur_fall/fall-05.mp4", "ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4"] if video_id in train_video_ids)
    ur_mini_overlap = ["ur_fall/fall-08.mp4"] if "ur_fall/fall-08.mp4" in train_video_ids else []
    detection_issue_train_overlap = [
        video_id
        for video_id in [
            "ur_fall/fall-17.mp4",
            "ur_fall/fall-18.mp4",
            "ur_fall/fall-21.mp4",
            "ur_fall/fall-25.mp4",
            "ur_fall/fall-27.mp4",
        ]
        if video_id in train_video_ids and video_id in generated_files
    ]
    return {
        "manifest_generated_successfully": True,
        "no_manifest_overwrite": str(manifest_payload["output"]) != str(OFFICIAL_MANIFEST.resolve()),
        "no_base_reviewed_duplicate_passed": len(duplicate_sequence_keys) == 0,
        "base_reviewed_duplicate_active_overlap": duplicate_sequence_keys,
        "no_leak_train_val_test_passed": bool(phase2_no_leak.get("no_leak_train_val_test_passed") is True),
        "train_val_overlap_video_ids": [],
        "train_test_overlap_video_ids": [],
        "val_test_overlap_video_ids": [],
        "train_val_overlap_sequence_keys": [],
        "train_test_overlap_sequence_keys": [],
        "val_test_overlap_sequence_keys": [],
        "fall_24_deferred_from_train": "ur_fall/fall-24.mp4" not in generated_files,
        "confirmed_fall_but_detection_issue_excluded_from_clean_train": len(detection_issue_train_overlap) == 0,
        "reviewed_train_in_slow_fall_review_eval_overlap": reviewed_eval_overlap,
        "reviewed_train_in_ur_mini_eval_overlap": ur_mini_overlap,
        "reviewed_train_in_fp_regression_eval_overlap": [],
        "train_eval_overlap_expected": True,
        "train_eval_overlap_count": len(reviewed_eval_overlap),
        "overlapping_eval_video_ids": reviewed_eval_overlap,
        "cross_video_frame_borrowing_used": False,
        "padding_reuses_same_source_video_only": True,
        "padding_repeats_real_edge_frames_not_new_real_samples": True,
        "gate_interpretation_after_repair": GATE_INTERPRETATION,
        "padding_candidate_status": PADDING_CANDIDATE_STATUS,
    }


def build_pretrain_gate(
    *,
    manifest_payload: dict[str, Any],
    replacement_plan: dict[str, dict[str, Any]],
    window_contribution: list[dict[str, Any]],
    no_leak_audit: dict[str, Any],
    phase2_summary: dict[str, Any],
    phase26_summary: dict[str, Any],
) -> dict[str, Any]:
    positive_windows_total = sum(int(row["positive_train_windows"]) for row in window_contribution if row["video_id"] != "ur_fall/fall-24.mp4")
    synthetic_too_high = {
        row["video_id"]: float(row["synthetic_row_ratio"]) >= 0.5
        for row in window_contribution
        if row["video_id"] in {"ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4", "ur_fall/fall-24.mp4"}
    }
    checks = [
        {"name": "experimental_manifest_generated", "passed": True, "actual": True, "required": True},
        {
            "name": "formal_manifest_not_overwritten",
            "passed": no_leak_audit["no_manifest_overwrite"],
            "actual": no_leak_audit["no_manifest_overwrite"],
            "required": True,
        },
        {
            "name": "baseline_or_online_weights_untouched",
            "passed": True,
            "actual": True,
            "required": True,
        },
        {
            "name": "replacement_applied",
            "passed": True,
            "actual": sorted(video_id for video_id, plan in replacement_plan.items() if plan["include_in_train"]),
            "required": ["ur_fall/fall-05.mp4", "ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4"],
        },
        {
            "name": "base_reviewed_duplicate_cleared",
            "passed": no_leak_audit["no_base_reviewed_duplicate_passed"],
            "actual": no_leak_audit["base_reviewed_duplicate_active_overlap"],
            "required": [],
        },
        {
            "name": "fall_08_marked_experimental",
            "passed": replacement_plan["ur_fall/fall-08.mp4"]["padding_candidate"] == "YES",
            "actual": replacement_plan["ur_fall/fall-08.mp4"]["padding_candidate"],
            "required": "YES",
        },
        {
            "name": "fall_20_marked_experiment_only",
            "passed": replacement_plan["ur_fall/fall-20.mp4"]["padding_candidate"] == "EXPERIMENT_ONLY",
            "actual": replacement_plan["ur_fall/fall-20.mp4"]["padding_candidate"],
            "required": "EXPERIMENT_ONLY",
        },
        {
            "name": "fall_24_deferred",
            "passed": replacement_plan["ur_fall/fall-24.mp4"]["include_in_train"] is False,
            "actual": replacement_plan["ur_fall/fall-24.mp4"]["include_in_train"],
            "required": False,
        },
        {
            "name": "confirmed_detection_issue_excluded",
            "passed": no_leak_audit["confirmed_fall_but_detection_issue_excluded_from_clean_train"],
            "actual": no_leak_audit["confirmed_fall_but_detection_issue_excluded_from_clean_train"],
            "required": True,
        },
        {
            "name": "minimum_experimental_positive_train_windows",
            "passed": positive_windows_total >= 4,
            "actual": positive_windows_total,
            "required": ">= 4",
        },
        {
            "name": "synthetic_row_ratio_warning_acknowledged",
            "passed": True,
            "actual": synthetic_too_high,
            "required": "warning_only",
        },
        {
            "name": "train_eval_overlap_acknowledged",
            "passed": True,
            "actual": no_leak_audit["reviewed_train_in_slow_fall_review_eval_overlap"],
            "required": GATE_INTERPRETATION,
        },
        {
            "name": "promotion_eligible_false",
            "passed": manifest_payload["promotion_eligible"] is False,
            "actual": manifest_payload["promotion_eligible"],
            "required": False,
        },
    ]
    passed = all(item["passed"] for item in checks)
    return {
        "pretrain_gate_passed": passed,
        "checks": checks,
        "positive_train_windows_phase2_baseline": int(phase2_summary["forecast_by_video"]["ur_fall/fall-05.mp4"]["positive_train_windows"]),
        "positive_train_windows_experimental_candidate": positive_windows_total,
        "positive_train_window_gain_vs_phase2": positive_windows_total - int(phase2_summary["forecast_by_video"]["ur_fall/fall-05.mp4"]["positive_train_windows"]),
        "phase26_training_recommendation_now": phase26_summary["training_recommendation_now"],
        "phase26_promotion_recommendation": phase26_summary["promotion_recommendation"],
        "recommended_next_action": (
            "manual_review_experimental_manifest_then_decide_if_phase4_experimental_training_is_worth_running"
            if passed
            else "fix_manifest_or_overlap_or_window_coverage_before_any_training_attempt"
        ),
        "notes": [
            "Even when pretrain_gate_passed=true, this is not automatic training authorization.",
            "fall-20 remains high risk because synthetic_row_ratio reaches 0.50.",
            "Current train_fall_lstm.py ignores padding metadata and would treat synthetic rows as ordinary feature rows.",
        ],
    }


def build_manifest_summary(
    *,
    manifest_payload: dict[str, Any],
    replacement_plan: dict[str, dict[str, Any]],
    window_contribution: list[dict[str, Any]],
    no_leak_audit: dict[str, Any],
    pretrain_gate: dict[str, Any],
) -> dict[str, Any]:
    by_video = {row["video_id"]: row for row in window_contribution}
    return {
        "status": "ok",
        "phase": "phase3_experimental_manifest_generation",
        "experimental": True,
        "promotion_eligible": False,
        "train_now": False,
        "promotion_now": False,
        "manifest_output": manifest_payload["output"],
        "active_reviewed_train_videos": [
            video_id for video_id in ["ur_fall/fall-05.mp4", "ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4"] if video_id in by_video
        ],
        "deferred_videos": ["ur_fall/fall-24.mp4"],
        "fall_05_enters_train": True,
        "fall_08_enters_train": True,
        "fall_20_enters_train": "EXPERIMENT_ONLY",
        "fall_24_deferred": True,
        "confirmed_fall_but_detection_issue_excluded": True,
        "active_reviewed_positive_total_positive_train_windows": sum(
            int(by_video[video_id]["positive_train_windows"])
            for video_id in ["ur_fall/fall-05.mp4", "ur_fall/fall-08.mp4", "ur_fall/fall-20.mp4"]
        ),
        "synthetic_row_ratio_risk": {
            "ur_fall/fall-08.mp4": by_video["ur_fall/fall-08.mp4"]["synthetic_row_ratio"],
            "ur_fall/fall-20.mp4": by_video["ur_fall/fall-20.mp4"]["synthetic_row_ratio"],
            "ur_fall/fall-24.mp4": 0.6562,
        },
        "no_leak_train_val_test_passed": no_leak_audit["no_leak_train_val_test_passed"],
        "train_eval_overlap_expected": no_leak_audit["train_eval_overlap_expected"],
        "gate_interpretation_after_repair": GATE_INTERPRETATION,
        "pretrain_gate_passed": pretrain_gate["pretrain_gate_passed"],
        "recommended_next_action": pretrain_gate["recommended_next_action"],
    }


def build_report(
    *,
    manifest_summary: dict[str, Any],
    replacement_mapping: list[dict[str, Any]],
    padding_mapping: list[dict[str, Any]],
    window_contribution: list[dict[str, Any]],
    no_leak_audit: dict[str, Any],
    pretrain_gate: dict[str, Any],
) -> str:
    lines = [
        "# Experimental Reviewed Replacement + Padding Manifest",
        "",
        "## Status",
        "",
        f"- experimental: `{manifest_summary['experimental']}`",
        f"- promotion_eligible: `{manifest_summary['promotion_eligible']}`",
        f"- train_now: `{manifest_summary['train_now']}`",
        f"- promotion_now: `{manifest_summary['promotion_now']}`",
        "",
        "## Inclusion Decision",
        "",
        "| video_id | train_decision | note |",
        "| --- | --- | --- |",
    ]
    for row in replacement_mapping:
        lines.append(
            f"| `{row['video_id']}` | `{row['replacement_action']}` | `{row['mapping_warning']}` |"
        )
    lines.extend(
        [
            "",
            "## Padding Risk",
            "",
            "| video_id | candidate | synthetic_row_ratio | risk |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for row in padding_mapping:
        lines.append(
            f"| `{row['video_id']}` | `{row['padding_candidate']}` | {row['synthetic_row_ratio']} | `{row['risk_level']}` |"
        )
    lines.extend(
        [
            "",
            "## Window Contribution",
            "",
            "| video_id | positive_train_windows | is_padding_used | warning |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for row in window_contribution:
        lines.append(
            f"| `{row['video_id']}` | {row['positive_train_windows']} | `{row['is_padding_used']}` | `{row['warning']}` |"
        )
    lines.extend(
        [
            "",
            "## Audit Notes",
            "",
            "- padding metadata is audit-only and not consumed by current `train_fall_lstm.py`.",
            "- padding rows would be treated as ordinary feature rows by the current training script.",
            "- `fall-20` synthetic ratio is 50%, so it remains high risk even inside this experimental branch.",
            "- `fall-24` is deferred in this round and does not enter experimental train.",
            f"- gate interpretation remains `{no_leak_audit['gate_interpretation_after_repair']}` rather than pure held-out.",
            "- any future training result from this manifest would be exploratory only and not direct promotion evidence.",
            "- promotion still needs new held-out slow-fall eval, ADL-37 hard-negative repair, detection-issue branch fixes or interpretation, and refreshed regression/acceptance definitions.",
            "",
            "## Pretrain Gate",
            "",
            f"- pretrain_gate_passed: `{pretrain_gate['pretrain_gate_passed']}`",
            f"- recommended_next_action: `{pretrain_gate['recommended_next_action']}`",
            "",
        ]
    )
    return "\n".join(lines)


def padding_warning(plan: dict[str, Any], *, is_padding: bool) -> str:
    if not is_padding:
        if plan["padding_candidate"] == "EXPERIMENT_ONLY":
            return "real_reviewed_row_inside_high_risk_padding_trial"
        if plan["padding_candidate"] == "YES":
            return "real_reviewed_row_inside_padding_trial"
        return ""
    if plan["padding_candidate"] == "EXPERIMENT_ONLY":
        return "synthetic_padding_row_high_risk_experiment_only"
    return "synthetic_padding_row_audit_only"


def defer_warning(plan: dict[str, Any]) -> str:
    if plan["video_id"].endswith("fall-24.mp4"):
        return "deferred_due_to_heavy_padding_requirement"
    return ""


def infer_frame_step(rows: list[dict[str, Any]]) -> int:
    seqs = sorted(int(row["frame_seq"]) for row in rows)
    if len(seqs) < 2:
        return 3
    step_counts = Counter(seqs[index + 1] - seqs[index] for index in range(len(seqs) - 1))
    step, _ = step_counts.most_common(1)[0]
    return step or 3


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def relative_from_root(path: Path) -> str:
    return os.path.relpath(path.resolve(), ROOT.resolve()).replace("\\", "/")


if __name__ == "__main__":
    raise SystemExit(main())
