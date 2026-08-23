from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
REVIEWED_ROOT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_BATCH_ID = "batch_030_relabel_audit"

CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a Fall Hint relabel/review batch for invalid labels and duplicate class conflicts."
    )
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"{batch_dir} already exists; pass --overwrite only if intentionally rebuilding")
        shutil.rmtree(batch_dir)

    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    review_labels_dir = batch_dir / "human_review" / "labels"
    review_meta_dir = batch_dir / "human_review" / "meta"
    meta_dir = batch_dir / "meta"
    for path in [frames_dir, prelabels_dir, review_labels_dir, review_meta_dir, meta_dir]:
        path.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    frame_rows: list[dict[str, str]] = []
    index = 1

    invalid_rows = read_csv(REVIEWED_ROOT / "meta" / "relabel_invalid_labels.csv")
    for row in invalid_rows:
        image_path = RAW_ROOT / row["batch_id"] / "frames" / row["image"]
        if not image_path.exists():
            continue
        new_name = build_name(index, "must_fix_invalid_class", row["batch_id"], Path(row["image"]).stem, image_path.suffix)
        shutil.copy2(image_path, frames_dir / new_name)

        # Keep the original invalid draft visible in the UI. If the reviewer saves
        # without changing class 7, the server drops it; this makes the failure mode
        # empty rather than silently retaining an illegal class.
        source_label = Path(row["label_path"])
        if source_label.exists():
            shutil.copy2(source_label, prelabels_dir / f"{Path(new_name).stem}.txt")
        else:
            (prelabels_dir / f"{Path(new_name).stem}.txt").write_text("", encoding="utf-8")

        rows.append(
            {
                "repair_index": f"{index:04d}",
                "repair_image": new_name,
                "repair_label": f"{Path(new_name).stem}.txt",
                "repair_type": "must_fix_invalid_class",
                "priority": "must_fix",
                "source_batch_id": row["batch_id"],
                "source_image": row["image"],
                "source_label_path": row["label_path"],
                "source_archive_image": "",
                "source_archive_label": "",
                "conflict_group_id": "",
                "current_classes": "invalid_class_7",
                "note": row.get("reason", ""),
            }
        )
        frame_rows.append(
            {
                "image": new_name,
                "video_id": row["image"],
                "scene": "MUST_FIX: invalid class 7",
                "group": "fix_invalid_label",
                "source_video": row.get("label_path", ""),
                "frame_index": "",
            }
        )
        index += 1

    conflict_rows = read_csv(REVIEWED_ROOT / "meta" / "relabel_duplicate_class_conflicts.csv")
    for row in conflict_rows:
        archive_image = REVIEWED_ROOT / "images" / row["archive_image"]
        archive_label = REVIEWED_ROOT / "labels" / row["archive_label"]
        if not archive_image.exists() or not archive_label.exists():
            continue
        new_name = build_name(index, row["group_id"], row["batch_id"], Path(row["archive_image"]).stem, archive_image.suffix)
        shutil.copy2(archive_image, frames_dir / new_name)
        shutil.copy2(archive_label, prelabels_dir / f"{Path(new_name).stem}.txt")
        rows.append(
            {
                "repair_index": f"{index:04d}",
                "repair_image": new_name,
                "repair_label": f"{Path(new_name).stem}.txt",
                "repair_type": "duplicate_class_conflict",
                "priority": "needs_human_review",
                "source_batch_id": row["batch_id"],
                "source_image": row["original_image"],
                "source_label_path": row["original_label_path"],
                "source_archive_image": row["archive_image"],
                "source_archive_label": row["archive_label"],
                "conflict_group_id": row["group_id"],
                "current_classes": row["classes"],
                "note": "Exact duplicate image has conflicting class labels across reviewed samples.",
            }
        )
        frame_rows.append(
            {
                "image": new_name,
                "video_id": f"{row['group_id']} | {row['archive_image']} | {row['original_image']}",
                "scene": "REVIEW: duplicate image class conflict",
                "group": row["group_id"],
                "source_video": row.get("source_video", ""),
                "frame_index": "",
            }
        )
        index += 1

    write_csv(meta_dir / "repair_manifest.csv", rows)
    write_csv(meta_dir / "frame_manifest.csv", frame_rows)
    write_classes(batch_dir / "classes.txt")
    write_readme(batch_dir / "README.md", rows)
    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "item_count": len(rows),
        "must_fix_invalid_class_items": sum(1 for row in rows if row["repair_type"] == "must_fix_invalid_class"),
        "duplicate_class_conflict_items": sum(1 for row in rows if row["repair_type"] == "duplicate_class_conflict"),
        "duplicate_class_conflict_groups": len(
            {row["conflict_group_id"] for row in rows if row["conflict_group_id"]}
        ),
        "review_instruction": "Open in the labeler, correct class/bbox, save every item. Saved results go to human_review/labels and human_review/meta.",
    }
    (meta_dir / "prepare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise SystemExit(f"Missing audit report: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def build_name(index: int, reason: str, batch_id: str, source_stem: str, suffix: str) -> str:
    clean_reason = safe_token(reason)[:24]
    clean_batch = safe_token(batch_id)
    clean_stem = safe_token(source_stem)[:48]
    return f"repair_{index:04d}_{clean_reason}_{clean_batch}_{clean_stem}{suffix.lower()}"


def safe_token(value: str) -> str:
    chars = []
    for char in value:
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("_")
    return "_".join("".join(chars).strip("_").split("_"))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        if not fieldnames:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_classes(path: Path) -> None:
    path.write_text(
        "\n".join(CLASS_NAMES[index] for index in sorted(CLASS_NAMES)) + "\n",
        encoding="utf-8",
    )


def write_readme(path: Path, rows: list[dict[str, str]]) -> None:
    text = "\n".join(
        [
            "# Fall Hint Relabel Audit Batch",
            "",
            "This batch contains only samples that must be fixed or strongly need human review before final training.",
            "",
            "Included:",
            "",
            f"- Must-fix invalid class samples: {sum(1 for row in rows if row['repair_type'] == 'must_fix_invalid_class')}",
            f"- Duplicate class conflict samples: {sum(1 for row in rows if row['repair_type'] == 'duplicate_class_conflict')}",
            "",
            "How to review:",
            "",
            "1. Open the labeler.",
            "2. For `MUST_FIX: invalid class 7`, choose the correct 0-6 class and correct the box.",
            "3. For duplicate conflict items, make the class and bbox match the visible image.",
            "4. Save every item.",
            "",
            "Saved labels are written to `human_review/labels`; reviewed status is written to `human_review/meta`.",
            "Use `meta/repair_manifest.csv` to map repaired items back to their original reviewed sample.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
