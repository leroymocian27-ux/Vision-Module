from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_ID = "batch_035_boundary_pair_review_20260705"
BATCH_DIR = ROOT / "datasets" / "fall_hint_v2_raw" / BATCH_ID
FRAMES_DIR = BATCH_DIR / "frames"
LABELS_DIR = BATCH_DIR / "human_review" / "labels"
META_DIR = BATCH_DIR / "meta"
REVIEW_QUEUE_PATH = META_DIR / "review_queue.csv"
SUMMARY_PATH = META_DIR / "review_validation_summary.json"
REVIEWED_ROWS_PATH = META_DIR / "review_validation_reviewed_rows.csv"
REVIEWED_DECISIONS = {"pass_train", "pass_val", "reject", "needs_fix"}
ALL_DECISIONS = REVIEWED_DECISIONS | {"pending"}
ALLOWED_TRI_STATE = {"pending", "true", "false"}
CLASS_NAME_TO_ID = {
    "falling": 0,
    "fallen": 1,
    "lying": 2,
    "sitting": 3,
    "bending": 4,
    "kneeling": 5,
    "standing": 6,
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def main() -> int:
    if not FRAMES_DIR.exists():
        raise SystemExit(f"missing frames dir: {FRAMES_DIR}")
    if not REVIEW_QUEUE_PATH.exists():
        raise SystemExit(f"missing review queue: {REVIEW_QUEUE_PATH}")

    rows = read_csv(REVIEW_QUEUE_PATH)
    frame_names = {path.name for path in FRAMES_DIR.iterdir() if path.suffix.lower() in IMAGE_EXTS}
    decision_counts: Counter[str] = Counter()
    issues: list[dict[str, str]] = []
    reviewed_rows: list[dict[str, str]] = []

    for row in rows:
        item_id = str(row.get("item_id") or "")
        target_image_path = Path(str(row.get("target_image_path") or ""))
        target_label_path = Path(str(row.get("target_label_path") or ""))
        image_name = target_image_path.name
        label_name = target_label_path.name
        decision = str(row.get("review_decision") or "").strip()
        train_flag = str(row.get("usable_for_training") or "").strip().lower()
        val_flag = str(row.get("usable_for_validation") or "").strip().lower()
        correct_class = str(row.get("correct_class") or "").strip()

        row_issue = []
        if image_name not in frame_names:
            row_issue.append("missing_image")
        if not (LABELS_DIR / label_name).exists():
            row_issue.append("missing_label")
        label_valid, label_reason = validate_yolo_label(LABELS_DIR / label_name)
        if not label_valid:
            row_issue.append(label_reason)
        if decision not in ALL_DECISIONS:
            row_issue.append("invalid_decision")
        if train_flag not in ALLOWED_TRI_STATE:
            row_issue.append("invalid_usable_for_training")
        if val_flag not in ALLOWED_TRI_STATE:
            row_issue.append("invalid_usable_for_validation")
        if correct_class and correct_class not in CLASS_NAME_TO_ID:
            row_issue.append("invalid_correct_class")

        if decision:
            decision_counts[decision] += 1

        reviewed_rows.append(
            {
                "item_id": item_id,
                "image": image_name,
                "label": label_name,
                "boundary_category": str(row.get("boundary_category") or ""),
                "related_failure_case": str(row.get("related_failure_case") or ""),
                "review_decision": decision or "",
                "usable_for_training": train_flag or "",
                "usable_for_validation": val_flag or "",
                "correct_class": correct_class,
                "label_valid": "true" if label_valid else "false",
                "label_issue": label_reason,
                "row_issue": ";".join(row_issue),
            }
        )

        if row_issue:
            issues.append(
                {
                    "item_id": item_id,
                    "image": image_name,
                    "issues": ";".join(row_issue),
                }
            )

    total = len(rows)
    reviewed = sum(1 for row in rows if str(row.get("review_decision") or "").strip() in REVIEWED_DECISIONS)
    invalid_decision_count = sum(1 for row in rows if str(row.get("review_decision") or "").strip() not in ALL_DECISIONS)
    needs_fix_count = decision_counts.get("needs_fix", 0)
    ready_for_merge = (
        reviewed == total
        and invalid_decision_count == 0
        and not any("missing_image" in issue["issues"] or "missing_label" in issue["issues"] for issue in issues)
        and needs_fix_count == 0
    )

    summary = {
        "batch_id": BATCH_ID,
        "total_rows": total,
        "reviewed_rows": reviewed,
        "pending_rows": total - reviewed,
        "decision_counts": dict(sorted(decision_counts.items())),
        "invalid_decision_count": invalid_decision_count,
        "issue_count": len(issues),
        "needs_fix_count": needs_fix_count,
        "ready_for_merge": ready_for_merge,
    }

    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(REVIEWED_ROWS_PATH, reviewed_rows)
    if issues:
        write_csv(META_DIR / "review_validation_issues.csv", issues)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ready_for_merge else 2


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        if not fieldnames:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_yolo_label(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing_label"
    for line_index, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, f"line_{line_index}_bad_column_count"
        try:
            class_id = int(float(parts[0]))
            x_center, y_center, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            return False, f"line_{line_index}_non_numeric"
        if class_id not in range(7):
            return False, f"line_{line_index}_bad_class_id"
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            return False, f"line_{line_index}_bad_bbox"
    return True, ""


if __name__ == "__main__":
    raise SystemExit(main())
