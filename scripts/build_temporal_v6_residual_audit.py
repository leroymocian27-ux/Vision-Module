from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCORE_COLUMNS = [
    "v6_fall_evidence_score",
    "v6_adl_suppression_score",
    "v6_vertical_drop_score",
    "v6_low_posture_score",
    "v6_post_fall_stillness_score",
    "v6_floor_contact_score",
    "v6_impact_proxy_score",
    "v6_low_posture_duration_ms",
    "v6_track_quality_score",
    "v6_recovery_score",
    "v6_support_surface_score",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a residual FN audit for temporal v6 fall review.")
    parser.add_argument(
        "--comparison",
        default=str(
            ROOT
            / "evaluations"
            / "fall_temporal_v6"
            / "slow_fall_review_stride8"
            / "temporal_v6_regression_comparison.json"
        ),
        help="Baseline/v6 comparison JSON produced by run_temporal_v6_regression_eval.py.",
    )
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_manifest.json"),
        help="Source manifest for fall review videos.",
    )
    parser.add_argument(
        "--frames-dir",
        default=str(ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_stride8" / "v6_decision"),
        help="Directory containing offline_eval_<video>_frames.csv files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "evaluations" / "fall_temporal_v6" / "residual_fn_audit"),
        help="Directory where residual audit JSON and Markdown files are written.",
    )
    args = parser.parse_args()

    output = build_residual_audit(
        comparison_path=Path(args.comparison),
        manifest_path=Path(args.manifest),
        frames_dir=Path(args.frames_dir),
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "temporal_v6_residual_fn_audit.json"
    md_path = output_dir / "temporal_v6_residual_fn_audit.md"
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(output), encoding="utf-8")
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(md_path.resolve()), **output["summary"]}, ensure_ascii=False, indent=2))
    return 0


def build_residual_audit(*, comparison_path: Path, manifest_path: Path, frames_dir: Path) -> dict[str, Any]:
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_by_name = {
        Path(str(item.get("path") or item.get("video_id") or "")).name: item for item in manifest.get("videos") or []
    }
    residual_rows = [
        row
        for row in comparison.get("per_video") or []
        if row.get("expected_alarm") is True and row.get("v6_confirmed") is False
    ]
    items = [audit_item(row, manifest_by_name.get(str(row.get("video")) or "") or {}, frames_dir) for row in residual_rows]
    items = sorted(items, key=lambda item: item["video"])
    summary = summarize(items, comparison)
    return {
        "summary": summary,
        "items": items,
        "source": {
            "comparison": str(comparison_path.resolve()),
            "manifest": str(manifest_path.resolve()),
            "frames_dir": str(frames_dir.resolve()),
        },
    }


def audit_item(row: dict[str, Any], manifest_item: dict[str, Any], frames_dir: Path) -> dict[str, Any]:
    video = str(row.get("video") or "")
    frames = load_frames(frames_dir / f"offline_eval_{safe_slug(Path(video).stem)}_frames.csv")
    best = best_evidence_frame(frames)
    max_scores = max_score_summary(frames)
    category, action = classify_residual(max_scores, best)
    missing = missing_evidence(max_scores)
    return {
        "video": video,
        "video_id": manifest_item.get("video_id"),
        "path": manifest_item.get("path"),
        "scene_type": row.get("scene_type", manifest_item.get("scene_type")),
        "support_surface": manifest_item.get("support_surface"),
        "v6_block_point": row.get("v6_block_point"),
        "fall_state_peak": best.get("fall_state"),
        "best_timestamp_ms": to_int(best.get("timestamp_ms")),
        "best_frame_index": to_int(best.get("frame_index")),
        "best_motion_path": best.get("v6_motion_path"),
        "best_scores": {col: to_float(best.get(col)) for col in SCORE_COLUMNS},
        "max_scores": max_scores,
        "decision_reason": parse_reason(best.get("v6_decision_reason")),
        "residual_category": category,
        "missing_evidence": missing,
        "recommended_review_action": action,
    }


def load_frames(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def best_evidence_frame(frames: list[dict[str, str]]) -> dict[str, str]:
    if not frames:
        return {}
    return max(frames, key=evidence_rank)


def evidence_rank(row: dict[str, str]) -> float:
    return (
        to_float(row.get("v6_fall_evidence_score")) * 2.0
        + to_float(row.get("v6_vertical_drop_score"))
        + to_float(row.get("v6_low_posture_score"))
        + to_float(row.get("v6_floor_contact_score"))
        + to_float(row.get("v6_impact_proxy_score"))
        + to_float(row.get("v6_post_fall_stillness_score"))
        - to_float(row.get("v6_adl_suppression_score"))
        - to_float(row.get("v6_support_surface_score"))
        - to_float(row.get("v6_recovery_score"))
    )


def max_score_summary(frames: list[dict[str, str]]) -> dict[str, float]:
    return {col: max((to_float(row.get(col)) for row in frames), default=0.0) for col in SCORE_COLUMNS}


def classify_residual(max_scores: dict[str, float], best: dict[str, str]) -> tuple[str, str]:
    fall_evidence = max_scores["v6_fall_evidence_score"]
    vertical_drop = max_scores["v6_vertical_drop_score"]
    low_posture = max_scores["v6_low_posture_score"]
    stillness = max_scores["v6_post_fall_stillness_score"]
    floor_contact = max_scores["v6_floor_contact_score"]
    impact = max_scores["v6_impact_proxy_score"]
    support = max_scores["v6_support_surface_score"]
    pose_success = str(best.get("pose_success") or "").lower() == "true"

    if not best or (fall_evidence < 0.15 and vertical_drop < 0.35 and low_posture < 0.10):
        return (
            "detector_or_tracking_evidence_missing",
            "Review detector, tracking ID, and pose availability. Prefer detector/pose training samples; do not add a state-machine fallback.",
        )
    if vertical_drop >= 0.70 and low_posture < 0.20 and floor_contact < 0.36:
        return (
            "pose_or_low_posture_collapse_after_drop",
            "Annotate fall start/end and post-fall posture. Prefer low-posture/floor-contact training; do not widen fast-drop rules.",
        )
    if low_posture >= 0.60 and stillness >= 0.60 and vertical_drop < 0.50 and impact < 0.35:
        return (
            "slow_or_normal_lying_ambiguous",
            "Review frame by frame as true fall vs voluntary lying. Add support_surface/floor_risk labels before slow-fall training.",
        )
    if fall_evidence < 0.40 and floor_contact < 0.30 and impact < 0.40:
        return (
            "insufficient_multi_evidence_for_rules",
            "Keep as hard-recall training data. Current evidence is too weak for a safe new rule.",
        )
    if not pose_success or support >= 0.35:
        return (
            "scene_or_pose_context_uncertain",
            "Review support surface, occlusion, and pose failure. Then route to training or scene-context correction.",
        )
    return (
        "temporal_model_training_candidate",
        "Add fall_start_ms, low_posture_start_ms, and recovery labels for temporal-model training.",
    )


def missing_evidence(max_scores: dict[str, float]) -> list[str]:
    missing: list[str] = []
    if max_scores["v6_fall_evidence_score"] < 0.65:
        missing.append("fall_evidence_below_fast_candidate")
    if max_scores["v6_low_posture_score"] < 0.55:
        missing.append("low_posture_weak")
    if max_scores["v6_floor_contact_score"] < 0.35:
        missing.append("floor_contact_weak")
    if max_scores["v6_impact_proxy_score"] < 0.50:
        missing.append("impact_weak")
    if max_scores["v6_vertical_drop_score"] < 0.50:
        missing.append("vertical_drop_weak")
    if max_scores["v6_low_posture_duration_ms"] < 600:
        missing.append("low_posture_hold_short")
    return missing


def summarize(items: list[dict[str, Any]], comparison: dict[str, Any]) -> dict[str, Any]:
    categories: dict[str, int] = {}
    for item in items:
        category = str(item.get("residual_category") or "unknown")
        categories[category] = categories.get(category, 0) + 1
    metrics = comparison.get("v6_event_metrics") or {}
    return {
        "residual_fn_count": len(items),
        "fall_event_recall": metrics.get("fall_event_recall"),
        "confirmed_false_positive_count": metrics.get("confirmed_false_positive_count"),
        "duplicate_alarm_videos": comparison.get("duplicate_alarm_videos") or [],
        "category_counts": categories,
    }


def render_markdown(output: dict[str, Any]) -> str:
    summary = output["summary"]
    lines = [
        "# Temporal V6 Residual FN Audit",
        "",
        "## Summary",
        "",
        f"- residual_fn_count: {summary['residual_fn_count']}",
        f"- fall_event_recall: {summary.get('fall_event_recall')}",
        f"- confirmed_false_positive_count: {summary.get('confirmed_false_positive_count')}",
        f"- duplicate_alarm_videos: {summary.get('duplicate_alarm_videos')}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in sorted((summary.get("category_counts") or {}).items()):
        lines.append(f"- {category}: {count}")
    lines.extend(
        [
            "",
            "## Residual Items",
            "",
            "| Video | Category | Best ms | Max fall | Max drop | Max low | Max floor | Max impact | Missing | Review action |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in output["items"]:
        max_scores = item["max_scores"]
        lines.append(
            "| {video} | {category} | {ms} | {fall:.3f} | {drop:.3f} | {low:.3f} | {floor:.3f} | {impact:.3f} | {missing} | {action} |".format(
                video=item["video"],
                category=item["residual_category"],
                ms=item["best_timestamp_ms"],
                fall=max_scores["v6_fall_evidence_score"],
                drop=max_scores["v6_vertical_drop_score"],
                low=max_scores["v6_low_posture_score"],
                floor=max_scores["v6_floor_contact_score"],
                impact=max_scores["v6_impact_proxy_score"],
                missing=", ".join(item["missing_evidence"]),
                action=item["recommended_review_action"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_reason(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return [str(value)]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


def safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


def to_float(value: object) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
