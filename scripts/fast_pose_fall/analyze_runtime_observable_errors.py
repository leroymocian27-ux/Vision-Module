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
            values.append(str(value).replace("|", "/").replace("\n", " ")[:260])
        out.append("|" + "|".join(values) + "|")
    return "\n".join(out) + "\n"


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
    height_deltas = [safe_float(r.get("bbox_height_delta")) for r in rows if r.get("bbox_height_delta") is not None]
    velocities = [safe_float(r.get("velocity_y")) for r in rows if r.get("velocity_y") is not None]
    speeds = [safe_float(r.get("speed")) for r in rows if r.get("speed") is not None]
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
        "scene_tags": first.get("scene_tags") or [],
        "hard_negative": bool(first.get("hard_negative")),
        "frame_rows": len(rows),
        "max_fall_score": max(scores) if scores else 0.0,
        "mean_fall_score": sum(scores) / len(scores) if scores else 0.0,
        "max_aspect_ratio": max(aspects) if aspects else 0.0,
        "max_center_y_delta": max(deltas) if deltas else 0.0,
        "max_height_delta": max(height_deltas) if height_deltas else 0.0,
        "max_velocity_y": max(velocities) if velocities else 0.0,
        "mean_speed": sum(speeds) / len(speeds) if speeds else 0.0,
        "max_speed": max(speeds) if speeds else 0.0,
        "max_stillness_duration_sec": max(stillness) if stillness else 0.0,
        "max_track_age_sec": max(track_age) if track_age else 0.0,
        "max_person_confidence": max(confidences) if confidences else 0.0,
        "first_threshold_time_sec": first_threshold_time,
    }


def classify_blocking_gate(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    runtime = decision.get("runtime_features") or {}
    gates = []
    if safe_float(asset["max_fall_score"]) < 0.74:
        gates.append("fall_score_below_candidate_threshold")
    if not runtime.get("has_recent_descent"):
        gates.append("recent_descent_gate")
    if not runtime.get("has_fallen_hold_stillness"):
        gates.append("fallen_hold_stillness_gate")
    if not runtime.get("track_is_stable"):
        gates.append("track_stability_gate")
    if runtime.get("is_moving_continuously"):
        gates.append("continuous_motion_suppressor")
    if runtime.get("is_horizontal_posture") and safe_float(asset["max_fall_score"]) < 0.82:
        gates.append("horizontal_posture_high_confidence_gate")
    return ", ".join(gates) or "unknown_runtime_gate"


def possible_relaxation(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    gate = classify_blocking_gate(asset, decision)
    if "fall_score_below" in gate:
        return "Evaluate lower candidate threshold or split-specific calibration, but only after adding larger frozen local_test."
    if "recent_descent" in gate:
        return "Add transition_score derived from multi-frame bbox/pose; do not relax raw descent alone."
    if "fallen_hold_stillness" in gate:
        return "Separate MARK_4 candidate from MARK_5 confirmation; keep confirmation conservative."
    if "continuous_motion" in gate:
        return "Use moving-but-falling transition model or pose shadow before relaxing motion suppressor."
    return "Manual review of feature extraction quality before threshold relaxation."


def risk_if_relaxed(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    gate = classify_blocking_gate(asset, decision)
    if "continuous_motion" in gate:
        return "May reintroduce walking_slow and recovery false positives."
    if "horizontal_posture" in gate:
        return "May reintroduce lying-without-fall false positives."
    if "recent_descent" in gate:
        return "May confuse sitting/squat/bending/lying hard negatives with falls."
    if "fall_score_below" in gate:
        return "May increase public/local ADL false positives."
    return "Unknown; needs targeted capture and review."


def why_triggered(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    return "; ".join(decision.get("reasons") or []) or "runtime rule predicted fall"


def missing_signal_for_fp(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    tags = " ".join(asset.get("scene_tags") or []).lower()
    runtime = decision.get("runtime_features") or {}
    if "standing" in tags or "recovery" in tags:
        return "standing/recovery intent signal; pose torso/hip stability; person-state classifier"
    if "bending" in tags:
        return "bending_pickup vs fall transition score; hand/object interaction or torso recovery"
    if "lying" in tags:
        return "lying-without-transition detector; pose visibility and transition_score"
    if runtime.get("is_moving_continuously"):
        return "motion continuity suppressor needs better fallen_hold_score"
    return "runtime semantic signal missing; needs manual tag review and pose shadow"


def suppressor_rule_for_fp(asset: dict[str, Any], decision: dict[str, Any]) -> str:
    tags = " ".join(asset.get("scene_tags") or []).lower()
    if "standing" in tags or "recovery" in tags:
        return "Require fallen_hold_score or pose-horizontal confirmation before MARK_4 on upright/recovery-like motion."
    if "bending" in tags:
        return "Downgrade high aspect/descent if bbox height recovers quickly and no still fallen hold."
    if "lying" in tags:
        return "Require transition_score plus persistence; otherwise stay MARK_3."
    return "Add body_completeness/person_presence and transition quality gates."


def write_false_negative_review(path: Path, fn_assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> Counter:
    rows = []
    gate_counts: Counter = Counter()
    for asset in fn_assets:
        decision = decisions[asset["asset_id"]]
        gate = classify_blocking_gate(asset, decision)
        for part in gate.split(", "):
            gate_counts[part] += 1
        rows.append(
            {
                "asset_id": asset["asset_id"],
                "dataset": asset["dataset"],
                "split": asset["split"],
                "label": asset["label"],
                "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                "mean_fall_score": round(safe_float(asset["mean_fall_score"]), 4),
                "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                "max_center_y_delta": round(safe_float(asset["max_center_y_delta"]), 3),
                "max_velocity_y": round(safe_float(asset["max_velocity_y"]), 3),
                "max_stillness_duration_sec": round(safe_float(asset["max_stillness_duration_sec"]), 3),
                "track_age_max": round(safe_float(asset["max_track_age_sec"]), 3),
                "which_gate_blocked": gate,
                "possible_relaxation": possible_relaxation(asset, decision),
                "risk_if_relaxed": risk_if_relaxed(asset, decision),
            }
        )
    md = [
        "# Runtime False Negative Review 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        f"Total FN reviewed: {len(fn_assets)}\n",
        "## Dominant Blocking Gates\n",
        table([{"gate": key, "count": value} for key, value in gate_counts.most_common()], ["gate", "count"]),
        "## False Negatives\n",
        table(
            rows,
            [
                "asset_id",
                "dataset",
                "split",
                "label",
                "max_fall_score",
                "mean_fall_score",
                "max_aspect_ratio",
                "max_center_y_delta",
                "max_velocity_y",
                "max_stillness_duration_sec",
                "track_age_max",
                "which_gate_blocked",
                "possible_relaxation",
                "risk_if_relaxed",
            ],
        ),
        "## Interpretation\n",
        "- Low recall is mainly caused by conservative runtime-only gates that require high fall_score, recent descent, plausible transition timing, and suppress continuous movement.\n",
        "- Public-set failures may also reflect feature extraction quality: motion boxes from video differ from curated temporal JSONL and may not reliably capture body state.\n",
    ]
    path.write_text("\n".join(md), encoding="utf-8")
    return gate_counts


def write_false_positive_review(path: Path, fp_assets: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> Counter:
    rows = []
    trigger_counts: Counter = Counter()
    for asset in fp_assets:
        decision = decisions[asset["asset_id"]]
        runtime = decision.get("runtime_features") or {}
        for key, value in runtime.items():
            if value:
                trigger_counts[key] += 1
        rows.append(
            {
                "asset_id": asset["asset_id"],
                "dataset": asset["dataset"],
                "split": asset["split"],
                "scene_tags for analysis only": asset["scene_tags"],
                "max_fall_score": round(safe_float(asset["max_fall_score"]), 4),
                "mean_fall_score": round(safe_float(asset["mean_fall_score"]), 4),
                "max_aspect_ratio": round(safe_float(asset["max_aspect_ratio"]), 4),
                "max_center_y_delta": round(safe_float(asset["max_center_y_delta"]), 3),
                "max_velocity_y": round(safe_float(asset["max_velocity_y"]), 3),
                "max_stillness_duration_sec": round(safe_float(asset["max_stillness_duration_sec"]), 3),
                "track_age_max": round(safe_float(asset["max_track_age_sec"]), 3),
                "why_triggered": why_triggered(asset, decision),
                "which_runtime_signal_missing": missing_signal_for_fp(asset, decision),
                "possible_suppressor_rule": suppressor_rule_for_fp(asset, decision),
            }
        )
    md = [
        "# Runtime False Positive Review 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        f"Total FP reviewed: {len(fp_assets)}\n",
        "## Dominant Trigger Features\n",
        table([{"feature": key, "count": value} for key, value in trigger_counts.most_common()], ["feature", "count"]),
        "## False Positives\n",
        table(
            rows,
            [
                "asset_id",
                "dataset",
                "split",
                "scene_tags for analysis only",
                "max_fall_score",
                "mean_fall_score",
                "max_aspect_ratio",
                "max_center_y_delta",
                "max_velocity_y",
                "max_stillness_duration_sec",
                "track_age_max",
                "why_triggered",
                "which_runtime_signal_missing",
                "possible_suppressor_rule",
            ],
        ),
        "## Interpretation\n",
        "- Remaining false positives are runtime-observable high-motion/posture cases where semantic tags are unavailable.\n",
        "- Suppression needs runtime quality signals, especially transition_score, fallen_hold_score, and pose/body completeness.\n",
    ]
    path.write_text("\n".join(md), encoding="utf-8")
    return trigger_counts


def write_feature_gap_report(path: Path, metrics: dict[str, Any], gate_counts: Counter, trigger_counts: Counter) -> None:
    md = [
        "# Runtime Feature Gap Report 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        "## Summary\n",
        "Runtime-observable Visual Risk Mark is tag-leakage-free but recall is low. It is currently better as a suppressor/downgrade layer than a primary fall detector.\n",
        "## Required Answers\n",
        "1. 当前 runtime-observable 规则为什么召回低？\n",
        "Because it demands runtime-only high-confidence evidence: candidate score, recent descent, plausible transition timing, track stability, and movement/stillness gates. This avoids tag leakage but blocks many true falls, especially public_val/public_test.\n",
        "2. 哪些判断目前只能靠 scene_tags，缺少 runtime 替代信号？\n",
        "no_person, lying-without-transition, walking-without-stillness, sitting/squat, partial_limb, edge_person, and occlusion need runtime quality/pose/transition substitutes.\n",
        "3. 哪些特征最容易导致 local_val 误报？\n",
        f"Dominant trigger features: {dict(trigger_counts.most_common())}. Local recovery/standing/bending can produce high aspect/descent from motion boxes.\n",
        "4. 哪些特征最容易导致 public_test 漏检？\n",
        f"Dominant blocking gates: {dict(gate_counts.most_common())}. Public-test failures are often blocked by score/descent/continuous-motion gates and may include motion-box extraction quality issues.\n",
        "5. 现在是否应该把 Visual Risk Mark 当 detector？\n",
        "NO. Recall is too low for a primary detector.\n",
        "6. 现在是否更适合把 Visual Risk Mark 当 suppressor/downgrade layer？\n",
        "YES. Keep main fall_score/existing detector for recall; use Visual Risk Mark to downgrade low-confidence, no-person-like, lying-without-transition, walking-without-stillness, and unstable-track cases.\n",
        "## Visual Risk Mark Role\n",
        "suppressor\n",
        "## Metrics Snapshot\n",
        table(
            [
                {
                    "metric": key,
                    "value": value,
                }
                for key, value in metrics["runtime_observable_metrics"].items()
            ],
            ["metric", "value"],
        ),
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def write_quality_signal_plan(path: Path) -> None:
    signals = [
        ("is_partial_body_runtime", "bbox + pose keypoint extents", "bbox touches frame edge or keypoints truncated", "optional", "partial body false positives", "not enough samples"),
        ("is_edge_person_runtime", "bbox geometry", "bbox_edge_touch_ratio over threshold", "no", "edge-person false positives", "not enough samples"),
        ("is_occluded_runtime", "pose/keypoint continuity + bbox instability", "keypoint dropout or sudden body-completeness drop", "yes preferred", "occlusion false positives/false negatives", "not enough samples"),
        ("pose_keypoint_coverage", "pose keypoints", "visible keypoints / expected keypoints", "yes", "low-quality pose decisions", "pose shadow needed"),
        ("torso_visibility", "pose shoulders/hips", "visible torso landmarks ratio", "yes", "lying/sitting ambiguity", "pose shadow needed"),
        ("hip_knee_ankle_visibility", "pose lower-body keypoints", "visible lower-body landmarks ratio", "yes", "fallen vs crouch/squat ambiguity", "pose shadow needed"),
        ("track_stability_score", "track age + bbox continuity", "age, IoU continuity, missing-frame rate", "no", "short/noisy track false positives", "partially supported"),
        ("fallen_hold_score", "bbox/pose temporal window", "low speed + horizontal/low posture persistence", "no-pose possible; pose improves", "walking/recovery false positives", "partially supported"),
        ("transition_score", "bbox center/height/aspect over time", "standing-to-low/horizontal change within window", "no-pose possible; pose improves", "lying-without-fall false positives", "partially supported"),
        ("bbox_edge_touch_ratio", "bbox geometry", "fraction of bbox perimeter touching frame margins", "no", "edge/partial false positives", "computable now"),
        ("body_completeness_score", "bbox + pose", "bbox size consistency plus keypoint coverage", "pose preferred", "partial/occlusion false positives", "pose shadow needed"),
        ("person_presence_quality", "detector confidence + track continuity", "confidence, track age, missing frames, bbox stability", "no", "no-person/ghost motion false positives", "partially supported"),
    ]
    rows = [
        {
            "signal": name,
            "source_fields": source,
            "calculation": calc,
            "needs_pose": needs_pose,
            "used_to_reduce": reduce,
            "current_data_support": support,
        }
        for name, source, calc, needs_pose, reduce, support in signals
    ]
    md = [
        "# Runtime Quality Signal Plan 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        table(rows, ["signal", "source_fields", "calculation", "needs_pose", "used_to_reduce", "current_data_support"]),
        "## Notes\n",
        "- `is_partial_body`, `is_edge_person`, and `is_occluded` should remain not_runtime_safe_yet until proven to be computed from runtime bbox/pose quality rather than scene tags.\n",
        "- Prioritize no-pose signals first: track_stability_score, fallen_hold_score, transition_score, bbox_edge_touch_ratio, person_presence_quality.\n",
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def write_capture_plan(path: Path) -> None:
    categories = [
        ("partial_limb", 6, 6, True, True),
        ("edge_person", 6, 6, True, True),
        ("occlusion", 6, 6, True, True),
        ("multi_person", 4, 4, True, True),
        ("standing recovery", 4, 4, False, True),
        ("bending pickup", 4, 4, True, True),
        ("walking slow", 4, 4, True, True),
        ("lying without fall", 6, 6, True, True),
        ("sitting/squat", 6, 6, True, True),
        ("no_person", 4, 4, True, False),
        ("real fall simulation from multiple angles", 8, 8, False, True),
        ("fall followed by fallen_hold", 6, 6, False, True),
        ("fall followed by recovery", 6, 6, False, True),
    ]
    rows = [
        {
            "category": category,
            "local_val_add": local_val,
            "local_test_freeze": local_test,
            "hard_negative_test": "YES" if hard_neg else "NO",
            "manual_min_event_annotation": "YES" if manual else "NO",
        }
        for category, local_val, local_test, hard_neg, manual in categories
    ]
    md = [
        "# Capture Plan For Missing Hard Cases 20260622\n",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}\n",
        table(rows, ["category", "local_val_add", "local_test_freeze", "hard_negative_test", "manual_min_event_annotation"]),
        "## Freeze Policy\n",
        "- local_test must be enlarged and frozen.\n",
        "- Newly frozen local_test clips must not be used for threshold tuning.\n",
        "- local_val can be used for threshold exploration; local_test is held out for acceptance only.\n",
        "## Practical Recording Notes\n",
        "- Keep camera, lighting, clothing, and distance varied but documented.\n",
        "- Include no-person and ghost-motion cases to validate person_presence_quality.\n",
        "- For fall simulations, record from front/side/back and include both fallen_hold and recovery endings.\n",
    ]
    path.write_text("\n".join(md), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze runtime-observable Visual Risk Mark feature gaps and capture needs.")
    parser.add_argument("--features-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "features")
    parser.add_argument("--metrics", type=Path, default=ROOT / "evaluations" / "fast_pose_fall" / "runtime_observable_risk_mark_metrics_20260622.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "evaluations" / "fast_pose_fall")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for split in EVAL_SPLITS:
        for row in load_jsonl(args.features_dir / f"features_{split}.jsonl"):
            grouped[row["asset_id"]].append(row)
    assets = [aggregate_asset(rows) for rows in grouped.values()]
    decisions = {asset["asset_id"]: assign_runtime_observable_risk_mark(asset) for asset in assets}
    fn_assets = [asset for asset in assets if asset["label"] == "fall" and not decisions[asset["asset_id"]]["predicted_fall"]]
    fp_assets = [asset for asset in assets if asset["label"] != "fall" and decisions[asset["asset_id"]]["predicted_fall"]]

    by_split_fn = Counter(asset["split"] for asset in fn_assets)
    by_split_fp = Counter(asset["split"] for asset in fp_assets)

    fn_path = args.output_dir / "runtime_false_negative_review_20260622.md"
    fp_path = args.output_dir / "runtime_false_positive_review_20260622.md"
    gap_path = args.output_dir / "runtime_feature_gap_report_20260622.md"
    signal_path = args.output_dir / "runtime_quality_signal_plan_20260622.md"
    capture_path = args.output_dir / "capture_plan_for_missing_hard_cases_20260622.md"

    gate_counts = write_false_negative_review(fn_path, fn_assets, decisions)
    trigger_counts = write_false_positive_review(fp_path, fp_assets, decisions)
    write_feature_gap_report(gap_path, metrics, gate_counts, trigger_counts)
    write_quality_signal_plan(signal_path)
    write_capture_plan(capture_path)

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

    report = {
        "status": "PASS",
        "files_created": [str(fn_path), str(fp_path), str(gap_path), str(signal_path), str(capture_path)],
        "false_negative_review": {
            "public_val_fn": by_split_fn["public_val"],
            "public_test_fn": by_split_fn["public_test"],
            "local_val_fn": by_split_fn["local_val"],
            "dominant_blocking_gates": dict(gate_counts.most_common(8)),
        },
        "false_positive_review": {
            "local_val_fp": by_split_fp["local_val"],
            "hard_negative_fp": by_split_fp["hard_negative_test"],
            "dominant_trigger_features": dict(trigger_counts.most_common(8)),
        },
        "feature_gap_summary": "Runtime-observable rules are conservative and should be suppressor/downgrade layer, not primary detector.",
        "recommended_visual_risk_mark_role": "suppressor",
        "runtime_quality_signals_needed": [
            "track_stability_score",
            "fallen_hold_score",
            "transition_score",
            "bbox_edge_touch_ratio",
            "person_presence_quality",
            "pose_keypoint_coverage",
            "body_completeness_score",
        ],
        "capture_plan_summary": "Expand frozen local_test and hard_negative_test with partial_limb, edge_person, occlusion, lying-without-fall, walking_slow, sitting/squat, no_person, multi_person, and fall transition variants.",
        "ready_for_runtime_shadow": "PARTIAL",
        "ready_for_training": "NO",
        "ready_for_pose_use_for_fall": "NO",
        "ready_for_real_post": "NO",
        "runtime_safety_status": {
            "MAIN_SYSTEM_REPORT_DRY_RUN": get_env_value("MAIN_SYSTEM_REPORT_DRY_RUN"),
            "pose_use_for_fall": get_env_value("POSE_USE_FOR_FALL") or "not_set_assumed_false_for_this_stage",
            "real_post_sent": "NO",
        },
        "git_status_after": git_status,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
