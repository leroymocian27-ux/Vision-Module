from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW = ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"
DEFAULT_AUDIT = ROOT / "evaluations" / "fall_temporal_v6" / "residual_fn_audit" / "temporal_v6_residual_fn_audit.json"
DEFAULT_FRAMES_DIR = ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_stride8" / "v6_decision"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "temporal_v6_review" / "professor_review_packet"

SHEET_FIELDS = [
    "video_id",
    "video_path",
    "residual_category",
    "suggested_review_decision",
    "fall_subtype",
    "best_timestamp_ms",
    "best_frame_index",
    "frame_window_csv",
    "missing_evidence",
    "recommended_review_action",
    "review_status",
    "usable_for_training",
    "review_decision",
    "fall_start_ms",
    "ground_contact_start_ms",
    "low_posture_start_ms",
    "motion_end_ms",
    "recovery_start_ms",
    "recovered_within_5s",
    "scene_type",
    "support_surface",
    "occlusion_level",
    "track_quality_issue",
    "pose_quality_issue",
    "reviewer",
    "review_notes",
]

FRAME_WINDOW_FIELDS = [
    "video_name",
    "frame_index",
    "timestamp_ms",
    "fall_state",
    "alarm_confirmed",
    "fall_prob",
    "fall_hint_label",
    "fall_hint_confidence",
    "lstm_probability",
    "v6_motion_path",
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
    "v6_scene_type",
    "v6_scene_support_surface",
    "v6_decision_reason",
    "fusion_state",
    "fusion_suppressed_reason",
    "tracking_state",
    "target_lost",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build professor review packet for temporal v6 residual false negatives.")
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="Residual review seed JSONL.")
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT), help="Residual FN audit JSON.")
    parser.add_argument("--frames-dir", default=str(DEFAULT_FRAMES_DIR), help="Directory with offline per-frame JSONL files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output review packet directory.")
    parser.add_argument("--window-ms", type=int, default=1600, help="Frame window radius around best_timestamp_ms.")
    args = parser.parse_args()

    result = build_packet(
        review_path=Path(args.review),
        audit_path=Path(args.audit),
        frames_dir=Path(args.frames_dir),
        output_dir=Path(args.output_dir),
        window_ms=args.window_ms,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_packet(
    *,
    review_path: Path,
    audit_path: Path,
    frames_dir: Path,
    output_dir: Path,
    window_ms: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    frame_window_dir = output_dir / "frame_windows"
    frame_window_dir.mkdir(parents=True, exist_ok=True)
    review_rows = read_jsonl(review_path)
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"items": []}
    audit_by_video = {str(item.get("video_id") or ""): item for item in audit.get("items") or []}

    sheet_rows: list[dict[str, Any]] = []
    missing_frame_files: list[str] = []
    for row in sorted(review_rows, key=lambda item: str(item.get("video_id") or "")):
        audit_item = audit_by_video.get(str(row.get("video_id") or ""), {})
        enriched = {**audit_item, **row}
        frame_source = frames_path_for(enriched, frames_dir)
        window_csv = frame_window_dir / f"{safe_stem(str(enriched.get('video_id') or enriched.get('video') or 'unknown'))}_window.csv"
        if frame_source.exists():
            frame_rows = select_frame_window(read_jsonl(frame_source), best_timestamp_ms=enriched.get("best_timestamp_ms"), window_ms=window_ms)
            write_frame_window(window_csv, frame_rows)
        else:
            missing_frame_files.append(str(frame_source))
            write_frame_window(window_csv, [])
        sheet_rows.append(sheet_row(enriched, window_csv=window_csv, output_dir=output_dir))

    sheet_path = output_dir / "residual_fn_review_sheet.csv"
    write_csv(sheet_path, sheet_rows, SHEET_FIELDS)
    markdown_path = output_dir / "residual_fn_review_packet.md"
    markdown_path.write_text(render_markdown(sheet_rows, output_dir=output_dir), encoding="utf-8")
    summary_path = output_dir / "review_packet_summary.json"
    summary = {
        "review_rows": len(review_rows),
        "sheet": str(sheet_path.resolve()),
        "markdown": str(markdown_path.resolve()),
        "frame_window_dir": str(frame_window_dir.resolve()),
        "missing_frame_files": missing_frame_files,
        "window_ms": window_ms,
        "next_step": "Professor/reviewer should fill residual_fn_review_seed.jsonl, then run validation and training dataset builders.",
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def sheet_row(row: dict[str, Any], *, window_csv: Path, output_dir: Path) -> dict[str, Any]:
    return {
        "video_id": row.get("video_id"),
        "video_path": row.get("video_path") or row.get("path"),
        "residual_category": row.get("residual_category"),
        "suggested_review_decision": row.get("suggested_review_decision"),
        "fall_subtype": row.get("fall_subtype"),
        "best_timestamp_ms": row.get("best_timestamp_ms"),
        "best_frame_index": row.get("best_frame_index"),
        "frame_window_csv": relative_path(window_csv, output_dir),
        "missing_evidence": join_values(row.get("missing_evidence")),
        "recommended_review_action": row.get("recommended_review_action"),
        "review_status": row.get("review_status"),
        "usable_for_training": row.get("usable_for_training"),
        "review_decision": row.get("review_decision") or "",
        "fall_start_ms": row.get("fall_start_ms"),
        "ground_contact_start_ms": row.get("ground_contact_start_ms"),
        "low_posture_start_ms": row.get("low_posture_start_ms"),
        "motion_end_ms": row.get("motion_end_ms"),
        "recovery_start_ms": row.get("recovery_start_ms"),
        "recovered_within_5s": row.get("recovered_within_5s"),
        "scene_type": row.get("scene_type"),
        "support_surface": row.get("support_surface"),
        "occlusion_level": row.get("occlusion_level"),
        "track_quality_issue": row.get("track_quality_issue"),
        "pose_quality_issue": row.get("pose_quality_issue"),
        "reviewer": row.get("reviewer") or "",
        "review_notes": row.get("review_notes") or "",
    }


def select_frame_window(rows: list[dict[str, Any]], *, best_timestamp_ms: Any, window_ms: int) -> list[dict[str, Any]]:
    if best_timestamp_ms is None:
        return rows[: min(len(rows), 16)]
    best = float(best_timestamp_ms)
    radius = max(0, int(window_ms))
    selected = [
        row
        for row in rows
        if row.get("timestamp_ms") is not None and abs(float(row.get("timestamp_ms")) - best) <= radius
    ]
    return selected or nearest_rows(rows, best_timestamp_ms=best, limit=16)


def nearest_rows(rows: list[dict[str, Any]], *, best_timestamp_ms: float, limit: int) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: abs(float(row.get("timestamp_ms") or 0.0) - best_timestamp_ms),
    )[:limit]


def write_frame_window(path: Path, rows: list[dict[str, Any]]) -> None:
    trimmed = [{field: row.get(field) for field in FRAME_WINDOW_FIELDS} for row in rows]
    write_csv(path, trimmed, FRAME_WINDOW_FIELDS)


def render_markdown(sheet_rows: list[dict[str, Any]], *, output_dir: Path) -> str:
    lines = [
        "# Temporal V6 Residual FN Professor Review Packet",
        "",
        "Purpose: review the remaining false negatives before adding them to temporal/LSTM training.",
        "",
        "Reviewer should edit `data/temporal_v6_review/residual_fn_review_seed.jsonl` after checking each case.",
        "",
        "Required final labels: `review_status`, `usable_for_training`, `review_decision`, event-time fields, scene/support labels, reviewer, and notes.",
        "",
        "## Cases",
        "",
    ]
    for row in sheet_rows:
        lines.extend(
            [
                f"### {row.get('video_id')}",
                "",
                f"- residual_category: `{row.get('residual_category')}`",
                f"- suggested_review_decision: `{row.get('suggested_review_decision')}`",
                f"- fall_subtype: `{row.get('fall_subtype')}`",
                f"- best_timestamp_ms: `{row.get('best_timestamp_ms')}`",
                f"- frame_window_csv: `{row.get('frame_window_csv')}`",
                f"- missing_evidence: `{row.get('missing_evidence')}`",
                f"- recommended_review_action: {row.get('recommended_review_action')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def frames_path_for(row: dict[str, Any], frames_dir: Path) -> Path:
    video_id = str(row.get("video_id") or row.get("video") or "")
    stem = Path(video_id.split("/", 1)[-1]).stem
    return frames_dir / f"offline_eval_{safe_eval_slug(stem)}_frames.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def join_values(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return "" if value is None else str(value)


def relative_path(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), start.resolve()).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def safe_eval_slug(value: str) -> str:
    keep = []
    for char in value:
        keep.append(char if char.isalnum() or char in {"-", "_"} else "_")
    return "".join(keep).strip("_") or "video"


def safe_stem(value: str) -> str:
    return safe_eval_slug(value.replace("/", "_").replace("\\", "_").replace(".", "_"))


if __name__ == "__main__":
    raise SystemExit(main())
