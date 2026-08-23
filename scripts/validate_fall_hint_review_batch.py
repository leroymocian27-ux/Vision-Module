from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate whether a Fall Hint human-review batch is complete and safe to merge."
    )
    parser.add_argument("--batch-id", default="batch_031_hardcase_audit")
    parser.add_argument("--require-all-reviewed", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_dir = RAW_ROOT / args.batch_id
    frames_dir = batch_dir / "frames"
    labels_dir = batch_dir / "human_review" / "labels"
    meta_dir = batch_dir / "human_review" / "meta"
    if not frames_dir.exists():
        raise SystemExit(f"missing frames dir: {frames_dir}")

    frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")
    images = sorted(path for path in frames_dir.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    class_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    invalid_items: list[dict[str, str]] = []
    reviewed_rows: list[dict[str, str]] = []

    for image_path in images:
        stem = image_path.stem
        label_path = labels_dir / f"{stem}.txt"
        status_path = meta_dir / f"{stem}.json"
        image_name = image_path.name
        status = "draft"
        if status_path.exists():
            try:
                status = str(json.loads(status_path.read_text(encoding="utf-8")).get("status") or "draft")
            except json.JSONDecodeError:
                status = "bad_meta_json"
        status_counts[status] += 1

        label_exists = label_path.exists()
        if status == "reviewed":
            valid, counts, reason = validate_label(label_path)
            if not valid:
                invalid_items.append(
                    {
                        "image": image_name,
                        "reason": reason,
                        "label_path": str(label_path),
                    }
                )
                continue
            if not counts:
                class_counts["__empty__"] += 1
            for cls, count in counts.items():
                class_counts[CLASS_NAMES[cls]] += count
            meta = frame_manifest.get(image_name, {})
            reviewed_rows.append(
                {
                    "image": image_name,
                    "status": status,
                    "scene": meta.get("scene", ""),
                    "group": meta.get("group", ""),
                    "label_path": str(label_path),
                    "box_count": str(sum(counts.values())),
                    "class_counts": json.dumps(
                        {CLASS_NAMES[cls]: count for cls, count in sorted(counts.items())},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
        elif not label_exists:
            invalid_items.append(
                {
                    "image": image_name,
                    "reason": "missing_review_label",
                    "label_path": str(label_path),
                }
            )

    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "frame_count": len(images),
        "status_counts": dict(status_counts),
        "reviewed_valid_count": len(reviewed_rows),
        "invalid_review_items": len(invalid_items),
        "reviewed_class_counts": dict(sorted(class_counts.items())),
        "ready_for_merge": len(reviewed_rows) == len(images) and not invalid_items,
    }

    if args.write_report:
        report_dir = batch_dir / "meta"
        write_csv(report_dir / "review_validation_reviewed_rows.csv", reviewed_rows)
        write_csv(report_dir / "review_validation_invalid_items.csv", invalid_items)
        (report_dir / "review_validation_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.require_all_reviewed and not summary["ready_for_merge"]:
        return 2
    return 0


def read_frame_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def validate_label(path: Path) -> tuple[bool, Counter[int], str]:
    if not path.exists():
        return False, Counter(), "missing_label"
    counts: Counter[int] = Counter()
    for line_index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, Counter(), f"line_{line_index}_bad_column_count"
        try:
            cls = int(float(parts[0]))
            x_center, y_center, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            return False, Counter(), f"line_{line_index}_non_numeric"
        if cls not in CLASS_NAMES:
            return False, Counter(), f"line_{line_index}_bad_class_{cls}"
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            return False, Counter(), f"line_{line_index}_bad_bbox"
        counts[cls] += 1
    return True, counts, ""


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


if __name__ == "__main__":
    raise SystemExit(main())
