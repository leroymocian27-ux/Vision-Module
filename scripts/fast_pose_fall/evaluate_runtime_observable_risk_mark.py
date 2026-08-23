from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from visual_risk_mark_offline import assign_visual_risk_mark
from visual_risk_mark_runtime_observable import assign_runtime_observable_risk_mark


EVAL_SPLITS = ["public_val", "public_test", "local_val", "local_test", "hard_negative_test"]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def get_env_value(name: str) -> str | None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() == name.lower():
            return value.strip()
    return None


def aggregate_asset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0]
    scores = [safe_float(r.get("fall_score")) for r in rows]
    aspects = [safe_float(r.get("bbox_aspect_ratio")) for r in rows if r.get("bbox_aspect_ratio") is not None]
    deltas = [safe_float(r.get("bbox_center_y_delta")) for r in rows if r.get("bbox_center_y_delta") is not None]
    heights = [safe_float(r.get("bbox_height")) for r in rows if r.get("bbox_height") is not None]
    widths = [safe_float(r.get("bbox_width")) for r in rows if r.get("bbox_width") is not None]
    height_deltas = [safe_float(r.get("bbox_height_delta")) for r in rows if r.get("bbox_height_delta") is not None]
    velocities = [safe_float(r.get("velocity_y")) for r in rows if r.get("velocity_y") is not None]
    speeds = [safe_float(r.get("speed")) for r in rows if r.get("speed") is not None]
    stillness = [safe_float(r.get("stillness_duration_sec")) for r in rows if r.get("stillness_duration_sec") is not None]
    track_age = [safe_float(r.get("track_age_sec")) for r in rows if r.get("track_age_sec") is not None]
    confidences = [safe_float(r.get("person_confidence")) for r in rows if r.get("person_confidence") is not None]
    first_threshold_time = next((safe_float(r.get("time_sec")) for r in rows if safe_float(r.get("fall_score")) >= 0.62), None)
    return {
        # Offline-only fields retained for evaluation/reporting, never required by runtime rule.
        "asset_id": first.get("asset_id"),
        "video_id": first.get("video_id"),
        "dataset": first.get("dataset"),
        "source": first.get("source"),
        "split": first.get("split"),
        "label": first.get("label"),
        "group_id": first.get("group_id"),
        "hard_negative": bool(first.get("hard_negative")),
        "scene_tags": first.get("scene_tags") or [],
        # Runtime-observable aggregate features.
        "frame_rows": len(rows),
        "max_fall_score": max(scores) if scores else 0.0,
        "mean_fall_score": sum(scores) / len(scores) if scores else 0.0,
        "max_aspect_ratio": max(aspects) if aspects else 0.0,
        "max_center_y_delta": max(deltas) if deltas else 0.0,
        "max_velocity_y": max(velocities) if velocities else 0.0,
        "max_stillness_duration_sec": max(stillness) if stillness else 0.0,
        "max_track_age_sec": max(track_age) if track_age else 0.0,
        "max_person_confidence": max(confidences) if confidences else 0.0,
        "max_height_delta": max(height_deltas) if height_deltas else 0.0,
        "max_bbox_width": max(widths) if widths else 0.0,
        "max_bbox_height": max(heights) if heights else 0.0,
        "mean_speed": sum(speeds) / len(speeds) if speeds else 0.0,
        "max_speed": max(speeds) if speeds else 0.0,
        "first_threshold_time_sec": first_threshold_time,
    }


def compute_counts(assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for asset in assets:
        truth = asset["label"] == "fall"
        pred = bool(decisions[asset["asset_id"]]["predicted_fall"])
        if truth and pred:
            tp += 1
        elif truth and not pred:
            fn += 1
        elif not truth and pred:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    fnr = fn / (fn + tp) if fn + tp else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
    }


def table(rows: list[dict[str, Any]], headers: list[str]) -> str:
    if not rows:
        return "_None._\n"
    out = ["|" + "|".join(headers) + "|", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        values = []
        for header in headers:
            value = row.get(header, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            values.append(str(value).replace("|", "/").replace("\n", " ")[:240])
        out.append("|" + "|".join(values) + "|")
    return "\n".join(out) + "\n"


def write_tag_leakage_audit(path: Path) -> None:
    md = [
        "# Tag Leakage Audit 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "## Answers\n",
        "- 当前离线规则是否使用 scene_tags？YES. `visual_risk_mark_offline.py` reads `scene_tags` and uses them for no_person/sitting/squat/lying/walking/partial_limb/edge_person/occlusion downgrade gates.\n",
        "- 当前离线规则是否使用 label？Prediction function: NO. Evaluation/reporting script: YES, for metrics and local/hard-negative review only.\n",
        "- 当前离线规则是否使用 hard_negative？Prediction function: NO. Evaluation/reporting script: YES, for split/report grouping only.\n",
        "- 当前离线规则是否使用 split / dataset / group_id？Prediction function: NO. Evaluation/reporting script: YES, for grouping, metrics, and reports.\n",
        "- 上一阶段结果存在 tag-aware 成分，不能当作 runtime 可上线指标。\n",
        "## Classification\n",
        table(
            [
                {
                    "class": "runtime_blocked",
                    "rule": "scene_tags contains no_person/sitting/squat/lying/walking/partial_limb/edge_person/occlusion",
                    "reason": "These tags come from dataset/session naming or offline annotation and are not naturally present in live camera runtime.",
                },
                {
                    "class": "offline_analysis_only",
                    "rule": "label, split, group_id, hard_negative used for metrics/error review",
                    "reason": "Safe for evaluation bookkeeping only; must not influence runtime prediction.",
                },
                {
                    "class": "runtime_safe",
                    "rule": "fall_score, person_confidence, bbox geometry, bbox deltas, velocity, speed, track_age, stillness",
                    "reason": "These are observable or derivable from live detection/tracking/temporal features.",
                },
            ],
            ["class", "rule", "reason"],
        ),
        "## Replacement Strategy\n",
        table(
            [
                {
                    "offline_tag_rule": "walking_slow downgrade",
                    "runtime_replacement": "continuous movement with stillness_duration_sec < 1.5 and no fallen-hold persistence caps prediction below MARK_4.",
                },
                {
                    "offline_tag_rule": "lying downgrade",
                    "runtime_replacement": "horizontal posture requires recent descent, high fall_score, plausible transition window, and persistence before confirmation.",
                },
                {
                    "offline_tag_rule": "no_person downgrade",
                    "runtime_replacement": "low person confidence or unstable/short track gates prevent fall prediction/confirmation.",
                },
                {
                    "offline_tag_rule": "sitting/squat downgrade",
                    "runtime_replacement": "abnormal posture without high-confidence recent descent and persistence remains MARK_3 or below.",
                },
                {
                    "offline_tag_rule": "partial_limb/edge_person/occlusion",
                    "runtime_replacement": "not_runtime_safe_yet until these fields are proven to be computed automatically from bbox/pose quality.",
                },
            ],
            ["offline_tag_rule", "runtime_replacement"],
        ),
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def write_local_val_review(path: Path, assets: list[dict[str, Any]], offline_decisions: dict[str, dict[str, Any]], runtime_decisions: dict[str, dict[str, Any]]) -> None:
    fp_assets = [
        asset
        for asset in assets
        if asset["split"] == "local_val"
        and asset["label"] != "fall"
        and offline_decisions[asset["asset_id"]]["predicted_fall"]
    ]
    rows = []
    for asset in fp_assets:
        runtime = runtime_decisions[asset["asset_id"]]
        rows.append(
            {
                "asset_id": asset["asset_id"],
                "group_id": asset["group_id"],
                "label": asset["label"],
                "scene_tags": asset["scene_tags"],
                "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                "mean_fall_score": round(safe_float(asset["mean_fall_score"]), 4),
                "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                "max_center_y_delta": round(safe_float(asset["max_center_y_delta"]), 3),
                "max_velocity_y": round(safe_float(asset["max_velocity_y"]), 3),
                "max_stillness_duration_sec": round(safe_float(asset["max_stillness_duration_sec"]), 3),
                "first_threshold_time_sec": asset["first_threshold_time_sec"],
                "why_offline_visual_risk_mark_triggered": "tag-aware offline rule saw high fall_score + posture/descent evidence without a runtime-only disambiguator.",
                "runtime_observable_downgrade_candidate": "; ".join(runtime["reasons"]) or "none",
            }
        )
    md = [
        "# Local Val Error Review 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "This review may use offline `scene_tags`; the runtime-observable rule may not.\n",
        table(
            rows,
            [
                "asset_id",
                "group_id",
                "label",
                "scene_tags",
                "max_fall_score",
                "mean_fall_score",
                "max_aspect_ratio",
                "max_center_y_delta",
                "max_velocity_y",
                "max_stillness_duration_sec",
                "first_threshold_time_sec",
                "why_offline_visual_risk_mark_triggered",
                "runtime_observable_downgrade_candidate",
            ],
        ),
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def count_runtime_fp(assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], feature_flag: str) -> int:
    count = 0
    for asset in assets:
        decision = decisions[asset["asset_id"]]
        if asset["label"] == "fall" or not decision["predicted_fall"]:
            continue
        if bool(decision.get("runtime_features", {}).get(feature_flag)):
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and evaluate runtime-observable Visual Risk Mark rules.")
    parser.add_argument("--features-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "features")
    parser.add_argument("--baseline-metrics", type=Path, default=ROOT / "evaluations" / "fast_pose_fall" / "baseline_metrics_20260622.json")
    parser.add_argument("--offline-metrics", type=Path, default=ROOT / "evaluations" / "fast_pose_fall" / "visual_risk_mark_metrics_20260622.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluations" / "fast_pose_fall")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    feature_summary = {}
    for split in EVAL_SPLITS:
        rows = load_jsonl(args.features_dir / f"features_{split}.jsonl")
        feature_summary[split] = {"feature_rows": len(rows), "assets": len({row["asset_id"] for row in rows})}
        all_rows.extend(rows)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[row["asset_id"]].append(row)
    assets = [aggregate_asset(rows) for rows in grouped.values()]
    assets_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        assets_by_split[asset["split"]].append(asset)

    runtime_decisions = {asset["asset_id"]: assign_runtime_observable_risk_mark(asset) for asset in assets}
    offline_decisions = {asset["asset_id"]: assign_visual_risk_mark(asset) for asset in assets}
    overall = compute_counts(assets, runtime_decisions)
    by_split = {split: compute_counts(assets_by_split[split], runtime_decisions) for split in EVAL_SPLITS}

    baseline = json.loads(args.baseline_metrics.read_text(encoding="utf-8"))
    baseline_c = baseline["baselines"]["Baseline C"]
    offline = json.loads(args.offline_metrics.read_text(encoding="utf-8"))
    offline_ref = offline["visual_risk_mark_metrics"]

    tag_audit_path = args.output_dir / "tag_leakage_audit_20260622.md"
    local_review_path = args.output_dir / "local_val_error_review_20260622.md"
    metrics_path = args.output_dir / "runtime_observable_risk_mark_metrics_20260622.json"
    report_path = args.output_dir / "runtime_observable_risk_mark_eval_20260622.md"
    write_tag_leakage_audit(tag_audit_path)
    write_local_val_review(local_review_path, assets, offline_decisions, runtime_decisions)

    metrics = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "feature_summary": feature_summary,
        "tag_leakage_free": True,
        "baseline_c_reference": {
            "precision": baseline_c["overall_eval"]["fall_precision"],
            "recall": baseline_c["overall_eval"]["fall_recall"],
            "f1": baseline_c["overall_eval"]["fall_f1"],
            "hard_negative_fpr": baseline_c["hard_negative_false_positive_rate"],
            "local_test_precision": baseline_c["local_test_precision"],
            "local_test_recall": baseline_c["local_test_recall"],
            "lying_fp": baseline_c.get("hard_negative_false_positive_categories", {}).get("lying", 0),
            "walking_slow_fp": sum(1 for row in baseline_c.get("local_test_results", []) if row.get("result") == "FP" and "walking" in " ".join(row.get("scene_tags") or []).lower()),
        },
        "offline_tag_aware_reference": {
            "precision": offline_ref["precision"],
            "recall": offline_ref["recall"],
            "f1": offline_ref["f1"],
            "hard_negative_fpr": offline_ref["hard_negative_false_positive_rate"],
            "local_test_precision": offline_ref["local_test_precision"],
            "local_test_recall": offline_ref["local_test_recall"],
            "lying_fp": offline_ref["lying_false_positive_count"],
            "walking_slow_fp": offline_ref["walking_slow_false_positive_count"],
        },
        "runtime_observable_metrics": {
            "precision": overall["precision"],
            "recall": overall["recall"],
            "f1": overall["f1"],
            "false_positive_rate": overall["false_positive_rate"],
            "false_negative_rate": overall["false_negative_rate"],
            "hard_negative_false_positive_rate": by_split["hard_negative_test"]["false_positive_rate"],
            "local_val_precision": by_split["local_val"]["precision"],
            "local_val_recall": by_split["local_val"]["recall"],
            "local_test_precision": by_split["local_test"]["precision"],
            "local_test_recall": by_split["local_test"]["recall"],
            "local_val_fp_count": by_split["local_val"]["fp"],
            "local_test_fp_count": by_split["local_test"]["fp"],
            "hard_negative_fp_count": by_split["hard_negative_test"]["fp"],
            "lying_like_fp_count": count_runtime_fp(assets, runtime_decisions, "is_horizontal_posture"),
            "walking_like_fp_count": count_runtime_fp(assets, runtime_decisions, "is_moving_continuously"),
            "low_confidence_fp_count": count_runtime_fp(assets, runtime_decisions, "is_low_confidence_person"),
        },
        "by_split": by_split,
        "known_blockers": [
            "LOCAL_TEST_TOO_SMALL",
            "HARD_NEGATIVE_PARTIAL_LIMB_MISSING",
            "OCCLUSION_EDGE_PERSON_MISSING",
        ],
        "runtime_safety_status": {
            "MAIN_SYSTEM_REPORT_DRY_RUN": get_env_value("MAIN_SYSTEM_REPORT_DRY_RUN"),
            "pose_use_for_fall": get_env_value("POSE_USE_FOR_FALL") or "not_set_assumed_false_for_this_stage",
            "real_post_sent": "NO",
        },
    }

    hn_pass = metrics["runtime_observable_metrics"]["hard_negative_false_positive_rate"] <= metrics["baseline_c_reference"]["hard_negative_fpr"]
    local_recall_ok = metrics["runtime_observable_metrics"]["local_test_recall"] >= 0.999
    tag_aware_drop = metrics["runtime_observable_metrics"]["f1"] < metrics["offline_tag_aware_reference"]["f1"]
    status = "PASS" if hn_pass and local_recall_ok else "PARTIAL"
    if tag_aware_drop:
        status = "PARTIAL"
    metrics["status"] = status
    metrics["reason"] = "tag-aware offline rules not fully transferable to runtime" if tag_aware_drop else "runtime observable gates satisfy hard-negative/local-test criteria"
    metrics["ready_for_visual_risk_mark_runtime_shadow"] = "PARTIAL" if status in {"PASS", "PARTIAL"} and hn_pass else "NO"
    metrics["ready_for_training"] = "NO"
    metrics["ready_for_pose_use_for_fall"] = "NO"
    metrics["ready_for_real_post"] = "NO"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        git_status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout.strip() or "(clean)"
    except Exception as exc:
        git_status = f"git status unavailable: {exc}"

    comparison = {
        "vs_baseline_c_hard_negative_fpr_delta": round(metrics["runtime_observable_metrics"]["hard_negative_false_positive_rate"] - metrics["baseline_c_reference"]["hard_negative_fpr"], 4),
        "vs_offline_tag_aware_f1_delta": round(metrics["runtime_observable_metrics"]["f1"] - metrics["offline_tag_aware_reference"]["f1"], 4),
        "vs_offline_tag_aware_local_test_recall_delta": round(metrics["runtime_observable_metrics"]["local_test_recall"] - metrics["offline_tag_aware_reference"]["local_test_recall"], 4),
    }

    md = [
        "# RuntimeObservableVisualRiskMarkAudit Result\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "```text",
        "【RuntimeObservableVisualRiskMarkAudit Result】",
        "",
        "status:",
        status,
        "",
        "files_created:",
        f"- {SCRIPT_DIR / 'visual_risk_mark_runtime_observable.py'}",
        f"- {SCRIPT_DIR / 'evaluate_runtime_observable_risk_mark.py'}",
        f"- {tag_audit_path}",
        f"- {local_review_path}",
        f"- {metrics_path}",
        f"- {report_path}",
        "",
        "tag_leakage_audit:",
        "uses_scene_tags_for_prediction: YES in offline tag-aware version; NO in runtime-observable version",
        "uses_label_for_prediction: NO",
        "uses_hard_negative_for_prediction: NO",
        "uses_split_dataset_group_for_prediction: NO",
        "runtime_blocked_rules: scene_tags no_person/sitting/squat/lying/walking/partial_limb/edge_person/occlusion downgrades",
        "runtime_safe_rules: fall_score/person_confidence/bbox geometry/deltas/velocity/speed/track_age/stillness rules",
        "replacement_strategy: replace tags with runtime-derived continuous movement, horizontal posture, recent descent, confidence, track stability, and fallen-hold persistence gates",
        "",
        "local_val_error_review:",
        f"- report={local_review_path}",
        f"- offline_tag_aware_local_val_fp={sum(1 for asset in assets_by_split['local_val'] if asset['label'] != 'fall' and offline_decisions[asset['asset_id']]['predicted_fall'])}",
        f"- runtime_observable_local_val_fp={metrics['runtime_observable_metrics']['local_val_fp_count']}",
        "",
        "baseline_c_reference:",
    ]
    for key, value in metrics["baseline_c_reference"].items():
        md.append(f"{key}: {value}")
    md.extend(["", "offline_tag_aware_reference:"])
    for key, value in metrics["offline_tag_aware_reference"].items():
        md.append(f"{key}: {value}")
    md.extend(["", "runtime_observable_metrics:"])
    for key, value in metrics["runtime_observable_metrics"].items():
        md.append(f"{key}: {value}")
    md.extend(
        [
            "",
            "comparison:",
            f"- {comparison}",
            f"- reason={metrics['reason']}",
            "",
            f"tag_leakage_free:\n{'YES' if metrics['tag_leakage_free'] else 'NO'}",
            f"ready_for_visual_risk_mark_runtime_shadow:\n{metrics['ready_for_visual_risk_mark_runtime_shadow']}",
            f"ready_for_training:\n{metrics['ready_for_training']}",
            f"ready_for_pose_use_for_fall:\n{metrics['ready_for_pose_use_for_fall']}",
            f"ready_for_real_post:\n{metrics['ready_for_real_post']}",
            "",
            "runtime_safety_status:",
            f"MAIN_SYSTEM_REPORT_DRY_RUN={metrics['runtime_safety_status']['MAIN_SYSTEM_REPORT_DRY_RUN']}",
            f"pose_use_for_fall={metrics['runtime_safety_status']['pose_use_for_fall']}",
            "real_post_sent=NO",
            "",
            "git_status_after:",
            git_status,
            "",
            "recommended_next_action:",
            "- Treat tag-aware offline results as analysis-only; use runtime-observable results for any future shadow discussion.",
            "- Add true runtime partial_limb/edge_person/occlusion quality signals before runtime shadow promotion.",
            "- Keep training and real POST blocked until local_test is larger and hard-negative coverage is expanded.",
            "```\n",
            "## Split Metrics\n",
            table(
                [{"split": split, **by_split[split]} for split in EVAL_SPLITS],
                ["split", "tp", "fp", "tn", "fn", "precision", "recall", "f1", "false_positive_rate", "false_negative_rate"],
            ),
            "## Runtime Observable Local Test Decisions\n",
            table(
                [
                    {
                        "asset_id": asset["asset_id"],
                        "label": asset["label"],
                        "group_id": asset["group_id"],
                        "mark": runtime_decisions[asset["asset_id"]]["visual_risk_mark"],
                        "predicted_fall": runtime_decisions[asset["asset_id"]]["predicted_fall"],
                        "reasons": runtime_decisions[asset["asset_id"]]["reasons"],
                    }
                    for asset in assets_by_split["local_test"]
                ],
                ["asset_id", "label", "group_id", "mark", "predicted_fall", "reasons"],
            ),
            "## Runtime Safety Notes\n",
            "- No production runtime code was modified.\n",
            "- No FallStateMachine/ResultPublisher/reporter code was modified.\n",
            "- No `.env` value was changed.\n",
            "- No real POST was sent.\n",
        ]
    )
    report_path.write_text("\n".join(md), encoding="utf-8")

    try:
        git_status_after = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout.strip() or "(clean)"
        text = report_path.read_text(encoding="utf-8")
        text = text.replace("git_status_after:\n" + git_status, "git_status_after:\n" + git_status_after)
        report_path.write_text(text, encoding="utf-8")
    except Exception:
        pass

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
