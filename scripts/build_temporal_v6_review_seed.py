from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build temporal v6 residual FN review seed JSONL.")
    parser.add_argument(
        "--audit",
        default=str(
            ROOT
            / "evaluations"
            / "fall_temporal_v6"
            / "residual_fn_audit"
            / "temporal_v6_residual_fn_audit.json"
        ),
        help="Residual FN audit JSON from build_temporal_v6_residual_audit.py.",
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"),
        help="Output JSONL for manual residual temporal review.",
    )
    parser.add_argument(
        "--summary",
        default=str(ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed_summary.json"),
        help="Output JSON summary.",
    )
    args = parser.parse_args()

    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    rows = build_review_rows(audit)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_path, rows)
    summary = summarize(rows, audit_path=Path(args.audit), output_path=output_path)
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_review_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [review_row(item) for item in audit.get("items") or []]
    return sorted(rows, key=lambda item: str(item.get("video_id") or ""))


def review_row(item: dict[str, Any]) -> dict[str, Any]:
    video_id = str(item.get("video_id") or video_id_from_path(str(item.get("video") or "")))
    category = str(item.get("residual_category") or "unknown")
    return {
        "video_id": video_id,
        "source_dataset": video_id.split("/", 1)[0] if "/" in video_id else "unknown",
        "video_path": item.get("path"),
        "binary_label": "fall",
        "expected_alarm": True,
        "review_status": "needs_temporal_review",
        "usable_for_training": False,
        "residual_category": category,
        "recommended_review_action": item.get("recommended_review_action"),
        "suggested_review_decision": suggested_review_decision(category),
        "fall_subtype": suggested_fall_subtype(category),
        "scene_type": item.get("scene_type") or "floor_risk_zone",
        "support_surface": item.get("support_surface") or "none",
        "fall_start_ms": None,
        "ground_contact_start_ms": None,
        "low_posture_start_ms": None,
        "motion_end_ms": None,
        "recovery_start_ms": None,
        "recovered_within_5s": None,
        "occlusion_level": "unknown",
        "track_quality_issue": category == "detector_or_tracking_evidence_missing",
        "pose_quality_issue": category in {"pose_or_low_posture_collapse_after_drop", "scene_or_pose_context_uncertain"},
        "best_timestamp_ms": item.get("best_timestamp_ms"),
        "best_frame_index": item.get("best_frame_index"),
        "best_motion_path": item.get("best_motion_path"),
        "max_scores": item.get("max_scores") or {},
        "missing_evidence": item.get("missing_evidence") or [],
        "reviewer": None,
        "review_notes": "",
    }


def suggested_review_decision(category: str) -> str:
    if category == "detector_or_tracking_evidence_missing":
        return "confirmed_fall_but_detection_issue"
    if category == "slow_or_normal_lying_ambiguous":
        return "ambiguous_second_review"
    if category == "insufficient_multi_evidence_for_rules":
        return "confirmed_fall_train"
    if category in {"pose_or_low_posture_collapse_after_drop", "scene_or_pose_context_uncertain"}:
        return "confirmed_fall_train"
    return "ambiguous_second_review"


def suggested_fall_subtype(category: str) -> str:
    mapping = {
        "detector_or_tracking_evidence_missing": "fall_with_tracking_loss",
        "pose_or_low_posture_collapse_after_drop": "fall_with_pose_collapse",
        "slow_or_normal_lying_ambiguous": "slow_fall_or_lying_ambiguous",
        "scene_or_pose_context_uncertain": "fall_with_scene_or_pose_uncertainty",
        "insufficient_multi_evidence_for_rules": "hard_recall_fall",
    }
    return mapping.get(category, "ambiguous_needs_second_review")


def summarize(rows: list[dict[str, Any]], *, audit_path: Path, output_path: Path) -> dict[str, Any]:
    categories: dict[str, int] = {}
    decisions: dict[str, int] = {}
    for row in rows:
        category = str(row.get("residual_category") or "unknown")
        decision = str(row.get("suggested_review_decision") or "unknown")
        categories[category] = categories.get(category, 0) + 1
        decisions[decision] = decisions.get(decision, 0) + 1
    return {
        "audit": str(audit_path.resolve()),
        "output": str(output_path.resolve()),
        "row_count": len(rows),
        "category_counts": categories,
        "suggested_review_decision_counts": decisions,
        "next_step": "Reviewer should fill event-time fields and set review_status=reviewed or approved before training.",
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def video_id_from_path(video: str) -> str:
    if not video:
        return ""
    return f"ur_fall/{Path(video).name}"


if __name__ == "__main__":
    raise SystemExit(main())
