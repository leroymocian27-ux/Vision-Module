from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_temporal_v6_review_sheet import BOOL_FIELDS, NUMBER_FIELDS
from scripts.validate_temporal_v6_review_seed import TRAINABLE_REVIEW_DECISIONS, TRAINABLE_REVIEW_STATUSES, validate_rows

DEFAULT_SHEET = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "residual_fn_review_sheet.csv"
DEFAULT_JSON = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "residual_fn_review_progress_summary.json"
DEFAULT_MD = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "residual_fn_review_progress_summary.md"

CORE_REVIEW_FIELDS = (
    "review_status",
    "usable_for_training",
    "review_decision",
    "reviewer",
    "review_notes",
)

TRAINING_REQUIRED_FIELDS = (
    "fall_start_ms",
    "ground_contact_start_ms",
    "low_posture_start_ms",
    "motion_end_ms",
    "recovered_within_5s",
    "scene_type",
    "support_surface",
    "occlusion_level",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize professor residual FN review progress before apply/post-review.")
    parser.add_argument("--sheet", default=str(DEFAULT_SHEET), help="Professor review CSV sheet.")
    parser.add_argument("--output-json", default=str(DEFAULT_JSON), help="Summary JSON output.")
    parser.add_argument("--output-md", default=str(DEFAULT_MD), help="Summary markdown output.")
    args = parser.parse_args()

    summary = summarize_review_progress(Path(args.sheet))
    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def summarize_review_progress(sheet_path: Path) -> dict[str, Any]:
    raw_rows = read_sheet(sheet_path)
    normalized_rows = [normalize_row(row) for row in raw_rows]
    validation = validate_rows(normalized_rows, source=sheet_path)
    error_by_video = group_issues(validation.get("errors") or [])
    warning_by_video = group_issues(validation.get("warnings") or [])

    status_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    reviewed_rows = 0
    pending_rows = 0
    trainable_ready_rows = 0
    rows_summary: list[dict[str, Any]] = []

    for row in normalized_rows:
        video_id = str(row.get("video_id") or "")
        status = str(row.get("review_status") or "")
        decision = str(row.get("review_decision") or "")
        usable = row.get("usable_for_training")
        status_counts[status or "missing"] = status_counts.get(status or "missing", 0) + 1
        decision_counts[decision or "missing"] = decision_counts.get(decision or "missing", 0) + 1

        is_reviewed = status in TRAINABLE_REVIEW_STATUSES or status in {"rejected", "second_review"}
        reviewed_rows += 1 if is_reviewed else 0
        pending_rows += 0 if is_reviewed else 1

        missing_core = missing_fields(row, CORE_REVIEW_FIELDS, require_if=is_reviewed)
        missing_training = missing_training_fields(row) if usable is True else []
        row_errors = error_by_video.get(video_id, [])
        row_warnings = warning_by_video.get(video_id, [])
        row_ready = is_reviewed and not row_errors and (usable is False or (usable is True and not missing_training))
        trainable_ready_rows += 1 if row_ready and usable is True and decision in TRAINABLE_REVIEW_DECISIONS else 0

        rows_summary.append(
            {
                "video_id": video_id,
                "review_status": status,
                "usable_for_training": usable,
                "review_decision": decision or None,
                "is_reviewed": is_reviewed,
                "missing_core_fields": missing_core,
                "missing_training_fields": missing_training,
                "error_codes": [item["code"] for item in row_errors],
                "warning_codes": [item["code"] for item in row_warnings],
                "ready_row": row_ready,
            }
        )

    all_rows_reviewed = pending_rows == 0
    return {
        "sheet": str(sheet_path.resolve()),
        "row_count": len(normalized_rows),
        "reviewed_rows": reviewed_rows,
        "pending_rows": pending_rows,
        "all_rows_reviewed": all_rows_reviewed,
        "status_counts": status_counts,
        "review_decision_counts": decision_counts,
        "trainable_ready_rows": trainable_ready_rows,
        "validation_error_count": validation.get("error_count", 0),
        "validation_warning_count": validation.get("warning_count", 0),
        "ready_for_apply": all_rows_reviewed and validation.get("error_count", 0) == 0,
        "ready_for_post_review_pipeline": all_rows_reviewed and validation.get("error_count", 0) == 0,
        "rows": rows_summary,
    }


def read_sheet(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_row(row: dict[str, str]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        raw = "" if value is None else str(value).strip()
        if raw == "":
            normalized[key] = None if key in NUMBER_FIELDS else ""
            continue
        if key in BOOL_FIELDS:
            normalized[key] = parse_bool(raw)
        elif key in NUMBER_FIELDS:
            normalized[key] = parse_number(raw)
        else:
            normalized[key] = raw
    return normalized


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def parse_number(value: str) -> int | float:
    number = float(value)
    return int(number) if number.is_integer() else number


def group_issues(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in issues:
        video_id = str(item.get("video_id") or "")
        grouped.setdefault(video_id, []).append(item)
    return grouped


def missing_fields(row: dict[str, Any], fields: tuple[str, ...], *, require_if: bool) -> list[str]:
    if not require_if:
        return []
    missing: list[str] = []
    for field in fields:
        value = row.get(field)
        if isinstance(value, str):
            if not value.strip():
                missing.append(field)
        elif value is None:
            missing.append(field)
    return missing


def missing_training_fields(row: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in TRAINING_REQUIRED_FIELDS:
        value = row.get(field)
        if field in {"scene_type", "support_surface", "occlusion_level"}:
            text = str(value or "").strip()
            if not text or text == "unknown":
                missing.append(field)
            continue
        if value is None or value == "":
            missing.append(field)
    return missing


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Residual FN Review Progress Summary",
        "",
        f"- sheet: `{summary['sheet']}`",
        f"- row_count: `{summary['row_count']}`",
        f"- reviewed_rows: `{summary['reviewed_rows']}`",
        f"- pending_rows: `{summary['pending_rows']}`",
        f"- trainable_ready_rows: `{summary['trainable_ready_rows']}`",
        f"- validation_error_count: `{summary['validation_error_count']}`",
        f"- validation_warning_count: `{summary['validation_warning_count']}`",
        f"- ready_for_apply: `{summary['ready_for_apply']}`",
        f"- ready_for_post_review_pipeline: `{summary['ready_for_post_review_pipeline']}`",
        "",
        "## Row Status",
        "",
        "| video_id | review_status | usable_for_training | review_decision | missing_core_fields | missing_training_fields | error_codes | ready_row |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {video_id} | {review_status} | {usable_for_training} | {review_decision} | {missing_core_fields} | {missing_training_fields} | {error_codes} | {ready_row} |".format(
                video_id=row["video_id"],
                review_status=row["review_status"] or "missing",
                usable_for_training=row["usable_for_training"],
                review_decision=row["review_decision"] or "missing",
                missing_core_fields=", ".join(row["missing_core_fields"]) or "-",
                missing_training_fields=", ".join(row["missing_training_fields"]) or "-",
                error_codes=", ".join(row["error_codes"]) or "-",
                ready_row=row["ready_row"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
