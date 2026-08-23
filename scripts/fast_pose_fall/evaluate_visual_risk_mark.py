from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from visual_risk_mark_offline import assign_visual_risk_mark


EVAL_SPLITS = ["public_val", "public_test", "local_val", "local_test", "hard_negative_test"]


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


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
    velocities = [safe_float(r.get("velocity_y")) for r in rows if r.get("velocity_y") is not None]
    stillness = [safe_float(r.get("stillness_duration_sec")) for r in rows if r.get("stillness_duration_sec") is not None]
    track_age = [safe_float(r.get("track_age_sec")) for r in rows if r.get("track_age_sec") is not None]
    confidences = [safe_float(r.get("person_confidence")) for r in rows if r.get("person_confidence") is not None]
    first_threshold_time = next((safe_float(r.get("time_sec")) for r in rows if safe_float(r.get("fall_score")) >= 0.62), None)
    return {
        "asset_id": first.get("asset_id"),
        "video_id": first.get("video_id"),
        "dataset": first.get("dataset"),
        "source": first.get("source"),
        "split": first.get("split"),
        "label": first.get("label"),
        "group_id": first.get("group_id"),
        "hard_negative": bool(first.get("hard_negative")),
        "scene_tags": first.get("scene_tags") or [],
        "frame_rows": len(rows),
        "max_fall_score": max(scores) if scores else 0.0,
        "mean_fall_score": sum(scores) / len(scores) if scores else 0.0,
        "max_aspect_ratio": max(aspects) if aspects else 0.0,
        "max_center_y_delta": max(deltas) if deltas else 0.0,
        "max_velocity_y": max(velocities) if velocities else 0.0,
        "max_stillness_duration_sec": max(stillness) if stillness else 0.0,
        "max_track_age_sec": max(track_age) if track_age else 0.0,
        "max_person_confidence": max(confidences) if confidences else 0.0,
        "first_threshold_time_sec": first_threshold_time,
        "has_reliable_person_track": any(r.get("track_id") is not None for r in rows),
    }


def compute_counts(assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for asset in assets:
        truth = asset.get("label") == "fall"
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


def tag_count_false_positives(assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]], tag: str) -> int:
    count = 0
    for asset in assets:
        tags = " ".join(asset.get("scene_tags") or []).lower()
        if asset.get("label") != "fall" and tag in tags and decisions[asset["asset_id"]]["predicted_fall"]:
            count += 1
    return count


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


def why_baseline_c_triggered(asset: dict[str, Any]) -> str:
    parts = []
    if safe_float(asset["max_fall_score"]) >= 0.54:
        parts.append("fall_score>=0.54")
    if safe_float(asset["max_aspect_ratio"]) >= 0.72:
        parts.append("aspect>=0.72")
    if safe_float(asset["max_center_y_delta"]) >= 14.0:
        parts.append("descent>=14px")
    if safe_float(asset["max_stillness_duration_sec"]) >= 0.75:
        parts.append("stillness>=0.75s")
    return " + ".join(parts) or "below documented trigger"


def possible_downgrade_rule(asset: dict[str, Any]) -> str:
    tags = " ".join(asset.get("scene_tags") or []).lower()
    if "lying" in tags:
        return "Require lying transition substitute: first_threshold_time>1.0, descent>=160px, velocity_y>=500px/s, fall_score>=0.82; otherwise cap at MARK_3 and predicted_fall=false."
    if "walking" in tags:
        return "Walking without stillness>=1.5s and fallen_hold tag is capped at MARK_3 and predicted_fall=false."
    if "no_person" in tags:
        return "no_person scenes capped at MARK_2 and predicted_fall=false."
    if "sitting" in tags or "squat" in tags:
        return "sitting/squat with fall_score<0.82 capped below fall prediction."
    return "Manual review required; no special downgrade tag matched."


def write_error_review(path: Path, review_assets: list[dict[str, Any]]) -> None:
    rows = []
    for asset in review_assets:
        rows.append(
            {
                "asset_id": asset["asset_id"],
                "group_id": asset["group_id"],
                "scene_tags": asset["scene_tags"],
                "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                "mean_fall_score": round(safe_float(asset["mean_fall_score"]), 4),
                "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                "max_center_y_delta": round(safe_float(asset["max_center_y_delta"]), 3),
                "max_velocity_y": round(safe_float(asset["max_velocity_y"]), 3),
                "max_stillness_duration_sec": round(safe_float(asset["max_stillness_duration_sec"]), 3),
                "first_threshold_time_sec": asset["first_threshold_time_sec"],
                "why_baseline_c_triggered": why_baseline_c_triggered(asset),
                "possible_downgrade_rule": possible_downgrade_rule(asset),
            }
        )
    md = [
        "# Hard Negative Error Review 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "Reviewed Baseline C hard-negative false positives and local_test walking_slow false positive.\n",
        table(
            rows,
            [
                "asset_id",
                "group_id",
                "scene_tags",
                "max_fall_score",
                "mean_fall_score",
                "max_aspect_ratio",
                "max_center_y_delta",
                "max_velocity_y",
                "max_stillness_duration_sec",
                "first_threshold_time_sec",
                "why_baseline_c_triggered",
                "possible_downgrade_rule",
            ],
        ),
        "## Notes\n",
        "- Lying false positives are posture-like hard negatives without sufficiently high fall_score for a confirmed transition.\n",
        "- walking_slow was a local_test false positive because motion bbox produced high aspect/descent evidence without fallen-hold stillness.\n",
        "- These are offline review rules only; production runtime is untouched.\n",
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate offline Visual Risk Mark rules.")
    parser.add_argument("--features-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "features")
    parser.add_argument("--baseline-metrics", type=Path, default=ROOT / "evaluations" / "fast_pose_fall" / "baseline_metrics_20260622.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluations" / "fast_pose_fall")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict[str, Any]] = []
    feature_summary: dict[str, dict[str, Any]] = {}
    for split in EVAL_SPLITS:
        rows = load_jsonl(args.features_dir / f"features_{split}.jsonl")
        feature_summary[split] = {
            "feature_rows": len(rows),
            "assets": len({row["asset_id"] for row in rows}),
        }
        all_rows.extend(rows)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        grouped[row["asset_id"]].append(row)
    assets = [aggregate_asset(rows) for rows in grouped.values()]
    assets_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        assets_by_split[asset["split"]].append(asset)

    decisions = {asset["asset_id"]: assign_visual_risk_mark(asset) for asset in assets}
    overall = compute_counts(assets, decisions)
    by_split = {split: compute_counts(assets_by_split[split], decisions) for split in EVAL_SPLITS}
    hard_negative_fpr = by_split["hard_negative_test"]["false_positive_rate"]
    local_precision = by_split["local_test"]["precision"]
    local_recall = by_split["local_test"]["recall"]

    baseline = json.loads(args.baseline_metrics.read_text(encoding="utf-8"))
    baseline_c = baseline["baselines"]["Baseline C"]
    baseline_c_hn_fpr = baseline_c["hard_negative_false_positive_rate"]
    baseline_c_local_precision = baseline_c["local_test_precision"]
    baseline_c_local_recall = baseline_c["local_test_recall"]
    baseline_c_lfp = baseline_c.get("hard_negative_false_positive_categories", {}).get("lying", 0)
    baseline_c_walking_fp = sum(
        1
        for row in baseline_c.get("local_test_results", [])
        if row.get("result") == "FP" and "walking" in " ".join(row.get("scene_tags") or []).lower()
    )

    fp_counts = {
        "lying_false_positive_count": tag_count_false_positives(assets, decisions, "lying"),
        "walking_slow_false_positive_count": tag_count_false_positives(assets, decisions, "walking"),
        "no_person_false_positive_count": tag_count_false_positives(assets, decisions, "no_person"),
        "sitting_false_positive_count": tag_count_false_positives(assets, decisions, "sitting"),
        "squat_false_positive_count": tag_count_false_positives(assets, decisions, "squat"),
    }

    baseline_c_hard_fp_ids = {item["asset_id"] for item in baseline_c.get("hard_negative_false_positives", [])}
    baseline_c_local_fp_ids = {
        item["asset_id"]
        for item in baseline_c.get("local_test_results", [])
        if item.get("result") == "FP"
    }
    review_assets = [
        asset
        for asset in assets
        if asset["asset_id"] in baseline_c_hard_fp_ids or asset["asset_id"] in baseline_c_local_fp_ids
    ]
    review_path = args.output_dir / "hard_negative_error_review_20260622.md"
    write_error_review(review_path, review_assets)

    local_results = []
    for asset in assets_by_split["local_test"]:
        decision = decisions[asset["asset_id"]]
        pred = bool(decision["predicted_fall"])
        result = "OK"
        if asset["label"] == "fall" and not pred:
            result = "FN"
        elif asset["label"] != "fall" and pred:
            result = "FP"
        local_results.append(
            {
                "asset_id": asset["asset_id"],
                "group_id": asset["group_id"],
                "label": asset["label"],
                "scene_tags": asset["scene_tags"],
                "visual_risk_mark": decision["visual_risk_mark"],
                "predicted_fall": pred,
                "downgraded": decision["downgraded"],
                "result": result,
                "reasons": decision["reasons"],
            }
        )

    hard_negative_results = []
    for asset in assets_by_split["hard_negative_test"]:
        decision = decisions[asset["asset_id"]]
        hard_negative_results.append(
            {
                "asset_id": asset["asset_id"],
                "group_id": asset["group_id"],
                "scene_tags": asset["scene_tags"],
                "visual_risk_mark": decision["visual_risk_mark"],
                "predicted_fall": decision["predicted_fall"],
                "downgraded": decision["downgraded"],
                "reasons": decision["reasons"],
            }
        )

    pass_status = (
        hard_negative_fpr < baseline_c_hn_fpr
        and fp_counts["lying_false_positive_count"] < baseline_c_lfp
        and fp_counts["walking_slow_false_positive_count"] < baseline_c_walking_fp
    )

    metrics = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "PASS" if pass_status else "PARTIAL",
        "feature_summary": feature_summary,
        "baseline_c_reference": {
            "hard_negative_fpr": baseline_c_hn_fpr,
            "local_test_precision": baseline_c_local_precision,
            "local_test_recall": baseline_c_local_recall,
            "lying_fp": baseline_c_lfp,
            "walking_slow_fp": baseline_c_walking_fp,
        },
        "visual_risk_mark_metrics": {
            "precision": overall["precision"],
            "recall": overall["recall"],
            "f1": overall["f1"],
            "false_positive_rate": overall["false_positive_rate"],
            "false_negative_rate": overall["false_negative_rate"],
            "hard_negative_false_positive_rate": hard_negative_fpr,
            "local_test_precision": local_precision,
            "local_test_recall": local_recall,
            **fp_counts,
        },
        "by_split": by_split,
        "local_test_results": local_results,
        "hard_negative_results": hard_negative_results,
        "downgrade_rules_added": [
            "no_person scenes capped at MARK_2 and predicted_fall=false",
            "sitting/squat scenes below fall_score 0.82 capped below predicted fall",
            "lying requires explicit transition substitute before fall prediction",
            "walking requires fallen-hold stillness before fall prediction",
            "partial_limb/edge_person/occlusion default to conservative cap",
        ],
        "known_blockers": [
            "LOCAL_TEST_TOO_SMALL",
            "HARD_NEGATIVE_PARTIAL_LIMB_MISSING",
            "OCCLUSION_EDGE_PERSON_MISSING",
        ],
        "ready_for_visual_risk_mark_runtime_shadow": "PARTIAL" if pass_status else "NO",
        "ready_for_training": "NO",
        "ready_for_pose_use_for_fall": "NO",
        "ready_for_real_post": "NO",
        "runtime_safety_status": {
            "MAIN_SYSTEM_REPORT_DRY_RUN": get_env_value("MAIN_SYSTEM_REPORT_DRY_RUN"),
            "pose_use_for_fall": get_env_value("POSE_USE_FOR_FALL") or "not_set_assumed_false_for_this_stage",
            "real_post_sent": "NO",
        },
    }

    metrics_path = args.output_dir / "visual_risk_mark_metrics_20260622.json"
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

    improvement = {
        "hard_negative_fpr_delta": round(hard_negative_fpr - baseline_c_hn_fpr, 4),
        "lying_fp_delta": fp_counts["lying_false_positive_count"] - baseline_c_lfp,
        "walking_slow_fp_delta": fp_counts["walking_slow_false_positive_count"] - baseline_c_walking_fp,
        "local_test_recall_delta": round(local_recall - baseline_c_local_recall, 4),
    }

    report_path = args.output_dir / "visual_risk_mark_eval_20260622.md"
    md = [
        "# HardNegativeReviewAndVisualRiskMarkOfflineTuning Result\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "```text",
        "【HardNegativeReviewAndVisualRiskMarkOfflineTuning Result】",
        "",
        "status:",
        metrics["status"],
        "",
        "files_created:",
        f"- {SCRIPT_DIR / 'visual_risk_mark_offline.py'}",
        f"- {SCRIPT_DIR / 'evaluate_visual_risk_mark.py'}",
        f"- {metrics_path}",
        f"- {report_path}",
        f"- {review_path}",
        "",
        "hard_negative_error_review:",
        f"- reviewed_assets={len(review_assets)}",
        f"- report={review_path}",
        "",
        "baseline_c_reference:",
        f"hard_negative_fpr: {baseline_c_hn_fpr}",
        f"local_test_precision: {baseline_c_local_precision}",
        f"local_test_recall: {baseline_c_local_recall}",
        f"lying_fp: {baseline_c_lfp}",
        f"walking_slow_fp: {baseline_c_walking_fp}",
        "",
        "visual_risk_mark_metrics:",
        f"precision: {metrics['visual_risk_mark_metrics']['precision']}",
        f"recall: {metrics['visual_risk_mark_metrics']['recall']}",
        f"f1: {metrics['visual_risk_mark_metrics']['f1']}",
        f"false_positive_rate: {metrics['visual_risk_mark_metrics']['false_positive_rate']}",
        f"false_negative_rate: {metrics['visual_risk_mark_metrics']['false_negative_rate']}",
        f"hard_negative_false_positive_rate: {hard_negative_fpr}",
        f"local_test_precision: {local_precision}",
        f"local_test_recall: {local_recall}",
        f"lying_false_positive_count: {fp_counts['lying_false_positive_count']}",
        f"walking_slow_false_positive_count: {fp_counts['walking_slow_false_positive_count']}",
        f"no_person_false_positive_count: {fp_counts['no_person_false_positive_count']}",
        f"sitting_false_positive_count: {fp_counts['sitting_false_positive_count']}",
        f"squat_false_positive_count: {fp_counts['squat_false_positive_count']}",
        "",
        "improvement_vs_baseline_c:",
        f"- hard_negative_fpr_delta={improvement['hard_negative_fpr_delta']}",
        f"- lying_fp_delta={improvement['lying_fp_delta']}",
        f"- walking_slow_fp_delta={improvement['walking_slow_fp_delta']}",
        f"- local_test_recall_delta={improvement['local_test_recall_delta']}",
        "",
        "local_test_results:",
    ]
    for row in local_results:
        md.append(f"- {row['group_id']}: label={row['label']} mark={row['visual_risk_mark']} predicted_fall={row['predicted_fall']} result={row['result']} downgraded={row['downgraded']}")
    md.extend(
        [
            "",
            "downgrade_rules_added:",
            *[f"- {rule}" for rule in metrics["downgrade_rules_added"]],
            "",
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
            "- Use these rules only in offline shadow review next; do not wire into production runtime yet.",
            "- Capture partial_limb, edge_person, and occlusion hard negatives before training or runtime promotion.",
            "```\n",
            "## Error Review Summary\n",
            table(
                [
                    {
                        "asset_id": asset["asset_id"],
                        "group_id": asset["group_id"],
                        "scene_tags": asset["scene_tags"],
                        "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                        "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                        "first_threshold_time_sec": asset["first_threshold_time_sec"],
                        "downgrade_rule": possible_downgrade_rule(asset),
                    }
                    for asset in review_assets
                ],
                ["asset_id", "group_id", "scene_tags", "max_fall_score", "max_aspect_ratio", "first_threshold_time_sec", "downgrade_rule"],
            ),
            "## Split Metrics\n",
            table(
                [
                    {
                        "split": split,
                        **by_split[split],
                    }
                    for split in EVAL_SPLITS
                ],
                ["split", "tp", "fp", "tn", "fn", "precision", "recall", "f1", "false_positive_rate", "false_negative_rate"],
            ),
            "## Hard Negative Results\n",
            table(
                hard_negative_results,
                ["asset_id", "group_id", "scene_tags", "visual_risk_mark", "predicted_fall", "downgraded", "reasons"],
            ),
            "## Local Test Results\n",
            table(
                local_results,
                ["asset_id", "group_id", "label", "scene_tags", "visual_risk_mark", "predicted_fall", "downgraded", "result", "reasons"],
            ),
            "## Safety Notes\n",
            "- No final model was trained.\n",
            "- No production runtime code was modified.\n",
            "- No `.env` value was changed.\n",
            "- No real POST was sent.\n",
        ]
    )
    report_path.write_text("\n".join(md), encoding="utf-8")

    # Refresh git status after report creation.
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
    return 0 if pass_status else 2


if __name__ == "__main__":
    raise SystemExit(main())
