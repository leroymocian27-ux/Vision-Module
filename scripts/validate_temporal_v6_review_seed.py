from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_REVIEW_STATUSES = {
    "needs_temporal_review",
    "approved",
    "reviewed",
    "second_review",
    "rejected",
}

ALLOWED_REVIEW_DECISIONS = {
    "confirmed_fall_train",
    "confirmed_fall_but_detection_issue",
    "hard_negative_train",
    "exclude_uncertain",
    "ambiguous_second_review",
    "exclude_bad_tracking",
    "exclude_not_fall",
}

TRAINABLE_REVIEW_DECISIONS = {
    "confirmed_fall_train",
    "confirmed_fall_but_detection_issue",
    "hard_negative_train",
}

TRAINABLE_REVIEW_STATUSES = {
    "approved",
    "reviewed",
}

REQUIRED_TRAINING_TIME_FIELDS = (
    "fall_start_ms",
    "ground_contact_start_ms",
    "low_posture_start_ms",
)

REQUIRED_TRAINING_CONTEXT_FIELDS = (
    "scene_type",
    "support_surface",
    "occlusion_level",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate temporal v6 manual review JSONL before training.")
    parser.add_argument(
        "--input",
        default=str(ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"),
        help="Reviewed temporal v6 JSONL file.",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="Optional output JSON summary path.",
    )
    args = parser.parse_args()

    rows = read_jsonl(Path(args.input))
    summary = validate_rows(rows, source=Path(args.input))
    if args.summary:
        summary_path = Path(args.summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["error_count"] else 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        row = json.loads(stripped)
        if not isinstance(row, dict):
            raise ValueError(f"Line {line_number} is not a JSON object.")
        row["_line_number"] = line_number
        rows.append(row)
    return rows


def validate_rows(rows: list[dict[str, Any]], *, source: Path | None = None) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    decision_counts: dict[str, int] = {}
    usable_count = 0

    for index, row in enumerate(rows, start=1):
        row_ref = row_reference(row, index)
        status = str(row.get("review_status") or "")
        decision = str(row.get("review_decision") or "")
        usable = row.get("usable_for_training")

        status_counts[status or "missing"] = status_counts.get(status or "missing", 0) + 1
        decision_counts[decision or "missing"] = decision_counts.get(decision or "missing", 0) + 1

        if not row.get("video_id"):
            add_issue(errors, row_ref, "missing_video_id", "video_id is required.")

        if status not in ALLOWED_REVIEW_STATUSES:
            add_issue(errors, row_ref, "invalid_review_status", f"review_status must be one of {sorted(ALLOWED_REVIEW_STATUSES)}.")

        if not isinstance(usable, bool):
            add_issue(errors, row_ref, "invalid_usable_for_training", "usable_for_training must be a boolean.")
            usable = False

        if usable:
            usable_count += 1
            validate_usable_row(row, row_ref, errors)
        elif status in TRAINABLE_REVIEW_STATUSES or status in {"rejected", "second_review"}:
            validate_approved_non_training_row(row, row_ref, errors, warnings)

    return {
        "source": str(source.resolve()) if source else None,
        "row_count": len(rows),
        "usable_for_training_count": usable_count,
        "status_counts": status_counts,
        "review_decision_counts": decision_counts,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def validate_usable_row(row: dict[str, Any], row_ref: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    if row.get("review_status") not in TRAINABLE_REVIEW_STATUSES:
        add_issue(
            errors,
            row_ref,
            "usable_row_not_approved",
            f"Training rows must have review_status in {sorted(TRAINABLE_REVIEW_STATUSES)}.",
        )

    decision = str(row.get("review_decision") or "")
    if decision not in TRAINABLE_REVIEW_DECISIONS:
        add_issue(
            errors,
            row_ref,
            "non_trainable_review_decision",
            f"Training rows require review_decision in {sorted(TRAINABLE_REVIEW_DECISIONS)}.",
        )

    for field in REQUIRED_TRAINING_TIME_FIELDS:
        if not is_non_negative_number(row.get(field)):
            add_issue(errors, row_ref, "missing_event_time", f"{field} must be a non-negative number for training rows.")

    motion_end_ms = row.get("motion_end_ms")
    if motion_end_ms is not None and not is_non_negative_number(motion_end_ms):
        add_issue(errors, row_ref, "invalid_motion_end_ms", "motion_end_ms must be null or a non-negative number.")

    recovery_start_ms = row.get("recovery_start_ms")
    if recovery_start_ms is not None and not is_non_negative_number(recovery_start_ms):
        add_issue(errors, row_ref, "invalid_recovery_start_ms", "recovery_start_ms must be null or a non-negative number.")

    if not isinstance(row.get("recovered_within_5s"), bool):
        add_issue(errors, row_ref, "missing_recovery_label", "recovered_within_5s must be true or false for training rows.")

    for field in REQUIRED_TRAINING_CONTEXT_FIELDS:
        value = str(row.get(field) or "").strip()
        if not value or value == "unknown":
            add_issue(errors, row_ref, "missing_context_label", f"{field} must be reviewed and cannot be unknown for training rows.")

    if not str(row.get("reviewer") or "").strip():
        add_issue(errors, row_ref, "missing_reviewer", "reviewer is required for training rows.")

    if not str(row.get("review_notes") or "").strip():
        add_issue(errors, row_ref, "missing_review_notes", "review_notes is required for training rows.")

    validate_trainable_decision_constraints(row, row_ref, errors)
    validate_timeline_order(row, row_ref, errors)


def validate_trainable_decision_constraints(row: dict[str, Any], row_ref: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    decision = str(row.get("review_decision") or "")
    if decision == "confirmed_fall_but_detection_issue":
        if not bool(row.get("track_quality_issue")) and not bool(row.get("pose_quality_issue")):
            add_issue(
                errors,
                row_ref,
                "missing_quality_issue_confirmation",
                "confirmed_fall_but_detection_issue requires track_quality_issue=true or pose_quality_issue=true.",
            )


def validate_approved_non_training_row(
    row: dict[str, Any],
    row_ref: dict[str, Any],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    decision = str(row.get("review_decision") or "")
    if decision and decision not in ALLOWED_REVIEW_DECISIONS:
        add_issue(
            errors,
            row_ref,
            "invalid_review_decision",
            f"Reviewed rows require review_decision in {sorted(ALLOWED_REVIEW_DECISIONS)}.",
        )
    if not str(row.get("reviewer") or "").strip():
        add_issue(errors, row_ref, "missing_reviewer", "Reviewed rows require reviewer.")
    if decision in TRAINABLE_REVIEW_DECISIONS:
        add_issue(
            warnings,
            row_ref,
            "approved_trainable_decision_not_used",
            "This row has a trainable review_decision but usable_for_training=false.",
        )


def validate_timeline_order(row: dict[str, Any], row_ref: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    fall_start = numeric_value(row.get("fall_start_ms"))
    ground_contact = numeric_value(row.get("ground_contact_start_ms"))
    low_posture = numeric_value(row.get("low_posture_start_ms"))
    motion_end = numeric_value(row.get("motion_end_ms"))
    recovery_start = numeric_value(row.get("recovery_start_ms"))

    if fall_start is not None and ground_contact is not None and ground_contact < fall_start:
        add_issue(errors, row_ref, "timeline_order_error", "ground_contact_start_ms cannot be before fall_start_ms.")
    if fall_start is not None and low_posture is not None and low_posture < fall_start:
        add_issue(errors, row_ref, "timeline_order_error", "low_posture_start_ms cannot be before fall_start_ms.")
    if fall_start is not None and motion_end is not None and motion_end < fall_start:
        add_issue(errors, row_ref, "timeline_order_error", "motion_end_ms cannot be before fall_start_ms.")
    if fall_start is not None and recovery_start is not None and recovery_start < fall_start:
        add_issue(errors, row_ref, "timeline_order_error", "recovery_start_ms cannot be before fall_start_ms.")


def row_reference(row: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "row": index,
        "line": row.get("_line_number"),
        "video_id": row.get("video_id"),
    }


def add_issue(issues: list[dict[str, Any]], row_ref: dict[str, Any], code: str, message: str) -> None:
    issues.append({**row_ref, "code": code, "message": message})


def is_non_negative_number(value: Any) -> bool:
    number = numeric_value(value)
    return number is not None and number >= 0


def numeric_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
