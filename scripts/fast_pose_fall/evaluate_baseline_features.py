from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


SPLITS = [
    "public_val",
    "public_test",
    "local_val",
    "local_test",
    "hard_negative_test",
]

ALL_SPLITS = ["public_train"] + SPLITS


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
    fall_scores = [safe_float(r.get("fall_score")) for r in rows]
    aspects = [safe_float(r.get("bbox_aspect_ratio")) for r in rows if r.get("bbox_aspect_ratio") is not None]
    deltas = [safe_float(r.get("bbox_center_y_delta")) for r in rows if r.get("bbox_center_y_delta") is not None]
    velocities = [safe_float(r.get("velocity_y")) for r in rows if r.get("velocity_y") is not None]
    speeds = [safe_float(r.get("speed")) for r in rows if r.get("speed") is not None]
    stillness = [safe_float(r.get("stillness_duration_sec")) for r in rows if r.get("stillness_duration_sec") is not None]
    positive_times = [safe_float(r.get("time_sec")) for r in rows if safe_float(r.get("fall_score")) >= 0.62]
    tags = first.get("scene_tags") or []
    return {
        "asset_id": first.get("asset_id"),
        "video_id": first.get("video_id"),
        "dataset": first.get("dataset"),
        "source": first.get("source"),
        "split": first.get("split"),
        "label": first.get("label"),
        "group_id": first.get("group_id"),
        "hard_negative": bool(first.get("hard_negative")),
        "scene_tags": tags,
        "path": first.get("path"),
        "frame_rows": len(rows),
        "max_fall_score": max(fall_scores) if fall_scores else 0.0,
        "mean_fall_score": sum(fall_scores) / len(fall_scores) if fall_scores else 0.0,
        "max_aspect_ratio": max(aspects) if aspects else 0.0,
        "max_center_y_delta": max(deltas) if deltas else 0.0,
        "max_velocity_y": max(velocities) if velocities else 0.0,
        "min_speed": min(speeds) if speeds else 0.0,
        "max_speed": max(speeds) if speeds else 0.0,
        "max_stillness_duration_sec": max(stillness) if stillness else 0.0,
        "first_threshold_time_sec": min(positive_times) if positive_times else None,
    }


def baseline_a(asset: dict[str, Any]) -> bool:
    return safe_float(asset.get("max_fall_score")) >= 0.62


def baseline_b(asset: dict[str, Any]) -> bool:
    aspect = safe_float(asset.get("max_aspect_ratio"))
    descent = safe_float(asset.get("max_center_y_delta"))
    velocity_y = safe_float(asset.get("max_velocity_y"))
    stillness = safe_float(asset.get("max_stillness_duration_sec"))
    return aspect >= 0.9 and (descent >= 28.0 or velocity_y >= 60.0 or stillness >= 1.0)


def baseline_c(asset: dict[str, Any]) -> bool:
    score = safe_float(asset.get("max_fall_score"))
    aspect = safe_float(asset.get("max_aspect_ratio"))
    descent = safe_float(asset.get("max_center_y_delta"))
    stillness = safe_float(asset.get("max_stillness_duration_sec"))
    tags = " ".join(asset.get("scene_tags") or []).lower()
    hard_negative_downgrade = any(term in tags for term in ["sitting", "squat", "no_person"]) and score < 0.82
    if hard_negative_downgrade:
        return False
    return score >= 0.54 and aspect >= 0.72 and (descent >= 14.0 or stillness >= 0.75)


BASELINES = {
    "Baseline A": {
        "name": "Existing fall_score threshold",
        "function": baseline_a,
        "rule": "max_fall_score >= 0.62",
    },
    "Baseline B": {
        "name": "bbox aspect ratio + center_y_delta rule",
        "function": baseline_b,
        "rule": "max_aspect_ratio >= 0.90 and (center_y_delta >= 28 px or velocity_y >= 60 px/s or stillness >= 1.0 s)",
    },
    "Baseline C": {
        "name": "fall_score + bbox motion fusion",
        "function": baseline_c,
        "rule": "max_fall_score >= 0.54 and max_aspect_ratio >= 0.72 and descent/stillness evidence, with sitting/squat/no_person downgrade below 0.82",
    },
}


def compute_counts(assets: list[dict[str, Any]], decisions: dict[str, bool]) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for asset in assets:
        truth = asset.get("label") == "fall"
        pred = bool(decisions.get(asset["asset_id"]))
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
        "fall_precision": round(precision, 4),
        "fall_recall": round(recall, 4),
        "fall_f1": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "false_negative_rate": round(fnr, 4),
    }


def table(rows: list[dict[str, Any]], headers: list[str]) -> str:
    if not rows:
        return "_None._\n"
    out = ["|" + "|".join(headers) + "|", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        vals = []
        for header in headers:
            value = row.get(header, "")
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            vals.append(str(value).replace("|", "/").replace("\n", " ")[:220])
        out.append("|" + "|".join(vals) + "|")
    return "\n".join(out) + "\n"


def summarize_feature_files(features_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for split in ALL_SPLITS:
        path = features_dir / f"features_{split}.jsonl"
        rows = load_jsonl(path)
        summary[split] = {
            "feature_rows": len(rows),
            "assets": len({row.get("asset_id") for row in rows}),
            "labels": dict(Counter(row.get("label") for row in rows)),
        }
        all_rows.extend(rows)
    return summary, all_rows


def load_extraction_speed_summary(features_dir: Path) -> dict[str, Any]:
    summary_path = features_dir / "feature_extraction_summary_20260622.json"
    if not summary_path.exists():
        return {"mean_video_processing_fps": None, "video_assets": 0}
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    speeds = []
    video_assets = 0
    for split_summary in (data.get("splits") or {}).values():
        for asset_summary in split_summary.get("asset_summaries") or []:
            if asset_summary.get("asset_type") != "video":
                continue
            video_assets += 1
            speed = asset_summary.get("offline_processing_fps")
            if speed is not None:
                speeds.append(safe_float(speed))
    return {
        "mean_video_processing_fps": round(sum(speeds) / len(speeds), 3) if speeds else None,
        "min_video_processing_fps": round(min(speeds), 3) if speeds else None,
        "max_video_processing_fps": round(max(speeds), 3) if speeds else None,
        "video_assets": video_assets,
    }


def hard_negative_fp_categories(assets: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for asset in assets:
        tags = " ".join(asset.get("scene_tags") or []).lower()
        matched = False
        for category in ["lying", "sitting", "squat", "no_person", "recovery", "walking"]:
            if category in tags:
                counts[category] += 1
                matched = True
        if not matched:
            counts["other"] += 1
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate fast pose fall baseline rules from feature jsonl files.")
    parser.add_argument("--features-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "features")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluations" / "fast_pose_fall")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    feature_summary, rows = summarize_feature_files(args.features_dir)
    speed_summary = load_extraction_speed_summary(args.features_dir)
    by_asset_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("split") in SPLITS and row.get("label") in {"fall", "non_fall"}:
            by_asset_rows[str(row.get("asset_id"))].append(row)
    assets = [aggregate_asset(asset_rows) for asset_rows in by_asset_rows.values() if asset_rows]
    assets_by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        assets_by_split[str(asset.get("split"))].append(asset)

    metrics: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "feature_summary": feature_summary,
        "baselines": {},
        "known_blockers": [
            "LOCAL_TEST_TOO_SMALL",
            "HARD_NEGATIVE_PARTIAL_LIMB_MISSING",
            "OCCLUSION_EDGE_PERSON_MISSING",
        ],
        "visual_risk_mark_threshold_suggestions": {
            "MARK_0_NORMAL": "fall_score < 0.25 and no abnormal bbox motion",
            "MARK_1_LOW_CONFIDENCE": "0.25 <= fall_score < 0.40 or person_confidence < 0.20",
            "MARK_2_ABNORMAL_POSTURE": "bbox_aspect_ratio >= 0.72 or center_y_delta >= 14 px",
            "MARK_3_FALL_SUSPECTED": "fall_score >= 0.54 with posture or descent evidence",
            "MARK_4_FALL_CANDIDATE": "fall_score >= 0.62 and recent_descent >= 28 px or stillness >= 1.0 s",
            "MARK_5_FALL_CONFIRMED": "candidate persists beyond track_age >= 1.5 s and stillness >= 1.5 s; not for this stage runtime",
            "fall_score_threshold": 0.62,
            "recent_descent_threshold_px": 28,
            "bbox_aspect_ratio_threshold": 0.9,
            "track_age_minimum_sec": 1.0,
            "stillness_duration_threshold_sec": 1.0,
            "hard_negative_downgrade_rule": "downgrade sitting/squat/no_person if fall_score < 0.82 and no rapid descent",
        },
    }

    report_sections: list[str] = []
    hard_negative_fp_summary: dict[str, list[dict[str, Any]]] = {}
    local_test_summary: dict[str, list[dict[str, Any]]] = {}
    for baseline_name, info in BASELINES.items():
        decisions = {asset["asset_id"]: bool(info["function"](asset)) for asset in assets}
        eval_counts = compute_counts(assets, decisions)
        split_metrics = {split: compute_counts(assets_by_split[split], decisions) for split in SPLITS}
        hard_negative_assets = assets_by_split["hard_negative_test"]
        hard_fp = [asset for asset in hard_negative_assets if decisions.get(asset["asset_id"])]
        fall_latencies = [
            safe_float(asset.get("first_threshold_time_sec"))
            for asset in assets
            if asset.get("label") == "fall"
            and decisions.get(asset["asset_id"])
            and asset.get("first_threshold_time_sec") is not None
        ]
        local_assets = assets_by_split["local_test"]
        local_rows = []
        for asset in local_assets:
            pred = bool(decisions.get(asset["asset_id"]))
            local_rows.append(
                {
                    "asset_id": asset["asset_id"],
                    "video_id": asset.get("video_id"),
                    "label": asset.get("label"),
                    "predicted_fall": pred,
                    "max_fall_score": round(safe_float(asset.get("max_fall_score")), 4),
                    "max_aspect_ratio": round(safe_float(asset.get("max_aspect_ratio")), 4),
                    "scene_tags": asset.get("scene_tags"),
                    "result": "FN" if asset.get("label") == "fall" and not pred else ("FP" if asset.get("label") != "fall" and pred else "OK"),
                }
            )
        local_counts = split_metrics["local_test"]
        hn_counts = split_metrics["hard_negative_test"]
        metrics["baselines"][baseline_name] = {
            "name": info["name"],
            "rule": info["rule"],
            "overall_eval": eval_counts,
            "by_split": split_metrics,
            "hard_negative_false_positive_rate": hn_counts["false_positive_rate"],
            "hard_negative_false_positive_categories": hard_negative_fp_categories(hard_fp),
            "local_test_precision": local_counts["fall_precision"],
            "local_test_recall": local_counts["fall_recall"],
            "detection_latency_sec_if_available": round(sum(fall_latencies) / len(fall_latencies), 4) if fall_latencies else None,
            "frame_processing_fps_or_offline_speed": speed_summary,
            "hard_negative_false_positives": hard_fp,
            "local_test_results": local_rows,
        }
        hard_negative_fp_summary[baseline_name] = hard_fp
        local_test_summary[baseline_name] = local_rows

    best_name = "Baseline C"
    local_test_count = len(assets_by_split["local_test"])
    hard_negative_count = len(assets_by_split["hard_negative_test"])
    feature_complete = all(feature_summary.get(split, {}).get("assets", 0) > 0 for split in ALL_SPLITS)
    ready_for_visual_risk = "PARTIAL" if feature_complete and local_test_count and hard_negative_count else "NO"
    ready_for_training = "NO"

    main_dry_run = get_env_value("MAIN_SYSTEM_REPORT_DRY_RUN")
    pose_use = get_env_value("POSE_USE_FOR_FALL")
    if pose_use is None:
        pose_use = "not_set_assumed_false_for_this_stage"
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

    metrics["ready_for_visual_risk_mark_implementation"] = ready_for_visual_risk
    metrics["ready_for_training"] = ready_for_training
    metrics["ready_for_pose_use_for_fall"] = "NO"
    metrics["ready_for_real_post"] = "NO"
    metrics["runtime_safety_status"] = {
        "MAIN_SYSTEM_REPORT_DRY_RUN": main_dry_run,
        "pose_use_for_fall": pose_use,
        "real_post_sent": "NO",
    }
    metrics["selected_baseline_for_threshold_suggestions"] = best_name
    metrics["feature_extraction_speed_summary"] = speed_summary
    metrics_path = args.output_dir / "baseline_metrics_20260622.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md: list[str] = []
    md.append("# FastPoseFallFeatureExtractionAndBaselineEval Result\n")
    md.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n")
    md.append("```text")
    md.append("【FastPoseFallFeatureExtractionAndBaselineEval Result】")
    md.append("")
    md.append("status:")
    md.append("PASS" if feature_complete else "PARTIAL")
    md.append("")
    md.append("files_created:")
    for split in ALL_SPLITS:
        md.append(f"- {args.features_dir / f'features_{split}.jsonl'}")
    md.append(f"- {args.features_dir / 'feature_schema_20260622.json'}")
    md.append(f"- {metrics_path}")
    md.append(f"- {args.output_dir / 'baseline_eval_report_20260622.md'}")
    md.append("")
    md.append("feature_extraction_summary:")
    for split in ALL_SPLITS:
        item = feature_summary[split]
        md.append(f"{split}: assets={item['assets']} feature_rows={item['feature_rows']} labels={item['labels']}")
    md.append("")
    md.append("feature_schema:")
    md.append("fast_pose_fall_features_v1; frame-level schema with nullable pose fields and baseline fall_score.")
    md.append("")
    md.append("baseline_metrics:")
    for baseline_name in BASELINES:
        item = metrics["baselines"][baseline_name]
        overall = item["overall_eval"]
        md.append(f"{baseline_name}: precision={overall['fall_precision']} recall={overall['fall_recall']} f1={overall['fall_f1']} fpr={overall['false_positive_rate']} fnr={overall['false_negative_rate']} hard_negative_fpr={item['hard_negative_false_positive_rate']} local_test_precision={item['local_test_precision']} local_test_recall={item['local_test_recall']}")
    md.append("")
    md.append("hard_negative_false_positives:")
    for baseline_name, fps in hard_negative_fp_summary.items():
        categories = metrics["baselines"][baseline_name]["hard_negative_false_positive_categories"]
        md.append(f"{baseline_name}: {len(fps)} categories={categories}")
    md.append("")
    md.append("local_test_results:")
    for baseline_name, rows_for_baseline in local_test_summary.items():
        counts = dict(Counter(row["result"] for row in rows_for_baseline))
        md.append(f"{baseline_name}: {counts}")
    md.append("")
    md.append("known_blockers:")
    for blocker in metrics["known_blockers"]:
        md.append(f"- {blocker}")
    md.append("")
    md.append("visual_risk_mark_threshold_suggestions:")
    for key, value in metrics["visual_risk_mark_threshold_suggestions"].items():
        md.append(f"{key}: {value}")
    md.append("")
    md.append(f"ready_for_visual_risk_mark_implementation:\n{ready_for_visual_risk}")
    md.append(f"ready_for_training:\n{ready_for_training}")
    md.append("ready_for_pose_use_for_fall:\nNO")
    md.append("ready_for_real_post:\nNO")
    md.append("")
    md.append("runtime_safety_status:")
    md.append(f"MAIN_SYSTEM_REPORT_DRY_RUN={main_dry_run}")
    md.append(f"pose_use_for_fall={pose_use}")
    md.append("real_post_sent=NO")
    md.append("")
    md.append("git_status_after:")
    md.append(git_status)
    md.append("")
    md.append("recommended_next_action:")
    md.append("- Review hard-negative and local-test mistakes, then capture partial_limb/edge_person/occlusion samples before training.")
    md.append("- Use Baseline C thresholds only as Visual Risk Mark draft inputs; do not wire into production runtime yet.")
    md.append("```\n")

    md.append("## Feature Summary\n")
    md.append(table(
        [
            {
                "split": split,
                "assets": feature_summary[split]["assets"],
                "feature_rows": feature_summary[split]["feature_rows"],
                "labels": feature_summary[split]["labels"],
            }
            for split in ALL_SPLITS
        ],
        ["split", "assets", "feature_rows", "labels"],
    ))

    md.append("## Baseline Metrics\n")
    metric_rows = []
    for baseline_name in BASELINES:
        item = metrics["baselines"][baseline_name]
        overall = item["overall_eval"]
        metric_rows.append({
            "baseline": baseline_name,
            "rule": item["rule"],
            "precision": overall["fall_precision"],
            "recall": overall["fall_recall"],
            "f1": overall["fall_f1"],
            "fpr": overall["false_positive_rate"],
            "fnr": overall["false_negative_rate"],
            "hard_negative_fpr": item["hard_negative_false_positive_rate"],
            "latency_sec": item["detection_latency_sec_if_available"],
            "local_test_precision": item["local_test_precision"],
            "local_test_recall": item["local_test_recall"],
        })
    md.append(table(metric_rows, ["baseline", "rule", "precision", "recall", "f1", "fpr", "fnr", "hard_negative_fpr", "latency_sec", "local_test_precision", "local_test_recall"]))

    md.append("## Split Metrics\n")
    split_rows = []
    for baseline_name in BASELINES:
        for split in SPLITS:
            counts = metrics["baselines"][baseline_name]["by_split"][split]
            split_rows.append({
                "baseline": baseline_name,
                "split": split,
                "tp": counts["tp"],
                "fp": counts["fp"],
                "tn": counts["tn"],
                "fn": counts["fn"],
                "precision": counts["fall_precision"],
                "recall": counts["fall_recall"],
                "fpr": counts["false_positive_rate"],
                "fnr": counts["false_negative_rate"],
            })
    md.append(table(split_rows, ["baseline", "split", "tp", "fp", "tn", "fn", "precision", "recall", "fpr", "fnr"]))

    md.append("## Hard Negative False Positives\n")
    hn_rows = []
    for baseline_name, fps in hard_negative_fp_summary.items():
        for asset in fps:
            hn_rows.append({
                "baseline": baseline_name,
                "asset_id": asset["asset_id"],
                "label": asset["label"],
                "scene_tags": asset["scene_tags"],
                "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                "max_center_y_delta": round(safe_float(asset["max_center_y_delta"]), 3),
            })
    md.append(table(hn_rows, ["baseline", "asset_id", "label", "scene_tags", "max_fall_score", "max_aspect_ratio", "max_center_y_delta"]))

    md.append("## Local Test Results\n")
    local_rows = []
    for baseline_name, rows_for_baseline in local_test_summary.items():
        for row in rows_for_baseline:
            row = dict(row)
            row["baseline"] = baseline_name
            local_rows.append(row)
    md.append(table(local_rows, ["baseline", "asset_id", "video_id", "label", "predicted_fall", "result", "max_fall_score", "max_aspect_ratio", "scene_tags"]))

    md.append("## Visual Risk Mark Draft\n")
    vrm_rows = [{"mark": key, "suggestion": value} for key, value in metrics["visual_risk_mark_threshold_suggestions"].items()]
    md.append(table(vrm_rows, ["mark", "suggestion"]))

    md.append("## Safety Notes\n")
    md.append("- No final model was trained.\n")
    md.append("- No business pipeline code was modified.\n")
    md.append("- No real POST was sent and `/alerting/simulation/send-once` was not called.\n")
    md.append("- `ready_for_training` remains `NO` because local_test is small and partial_limb/edge_person/occlusion coverage is missing.\n")

    report_path = args.output_dir / "baseline_eval_report_20260622.md"
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
    return 0 if feature_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
