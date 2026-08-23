from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "datasets" / "falling_transition_positive_batch_20260705"
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
DEFAULT_BATCH_ID = "batch_034_falling_transition_positive_review_20260705"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a dedicated Fall Hint review batch from falling_transition_positive_batch_20260705."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_notes(notes: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in notes.split(";"):
        token = part.strip()
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    manifest_path = source / "manifest.csv"
    review_queue_path = source / "review_queue.csv"
    if not manifest_path.exists():
        raise SystemExit(f"missing manifest: {manifest_path}")
    if not review_queue_path.exists():
        raise SystemExit(f"missing review queue: {review_queue_path}")

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"batch already exists, pass --overwrite to rebuild: {batch_dir}")
        shutil.rmtree(batch_dir)

    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    meta_dir = batch_dir / "meta"
    review_labels_dir = batch_dir / "human_review" / "labels"
    review_meta_dir = batch_dir / "human_review" / "meta"
    for path in [frames_dir, prelabels_dir, meta_dir, review_labels_dir, review_meta_dir]:
        path.mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(manifest_path)
    queue_rows = {row["item_id"]: row for row in read_csv(review_queue_path)}

    frame_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    prepared_count = 0

    for row in manifest_rows:
        item_id = row["item_id"]
        source_image = Path(row["target_image_path"])
        source_label = Path(row["target_label_path"])
        if not source_image.exists() or not source_label.exists():
            continue

        image_name = f"{item_id}{source_image.suffix.lower()}"
        label_name = f"{item_id}.txt"
        shutil.copy2(source_image, frames_dir / image_name)
        shutil.copy2(source_label, prelabels_dir / label_name)

        notes = parse_notes(row.get("notes", ""))
        frame_rows.append(
            {
                "image": image_name,
                "video_id": row.get("source_video_id", ""),
                "scene": row.get("category", ""),
                "group": row.get("class_name", ""),
                "source_batch_id": notes.get("batch_id", ""),
                "source_original_image": notes.get("original_image", ""),
                "source_video": notes.get("source_video", ""),
                "source_manifest_index": item_id,
                "second_review_status": "draft",
            }
        )
        audit_rows.append(
            {
                "item_id": item_id,
                "image": image_name,
                "label": label_name,
                "category": row.get("category", ""),
                "class_name": row.get("class_name", ""),
                "near_miss_pattern": row.get("near_miss_pattern", ""),
                "source_batch_id": notes.get("batch_id", ""),
                "source_original_image": notes.get("original_image", ""),
                "source_video": notes.get("source_video", ""),
                "source_dataset_manifest_target": row.get("target_image_path", ""),
                "review_decision": queue_rows.get(item_id, {}).get("review_decision", "pending"),
            }
        )
        prepared_count += 1

    write_csv(
        meta_dir / "frame_manifest.csv",
        frame_rows,
        [
            "image",
            "video_id",
            "scene",
            "group",
            "source_batch_id",
            "source_original_image",
            "source_video",
            "source_manifest_index",
            "second_review_status",
        ],
    )
    write_csv(
        meta_dir / "audit_manifest.csv",
        audit_rows,
        [
            "item_id",
            "image",
            "label",
            "category",
            "class_name",
            "near_miss_pattern",
            "source_batch_id",
            "source_original_image",
            "source_video",
            "source_dataset_manifest_target",
            "review_decision",
        ],
    )
    (batch_dir / "classes.txt").write_text(
        "falling\nfallen\nlying\nsitting\nbending\nkneeling\nstanding\n",
        encoding="utf-8",
    )
    (batch_dir / "README.md").write_text(
        "\n".join(
            [
                "# Falling Transition Positive Review Batch",
                "",
                "This batch is a dedicated human-review package for the 117 samples from",
                "`datasets/falling_transition_positive_batch_20260705`.",
                "",
                "Review goal:",
                "- Verify bbox and class on every image.",
                "- Save each image as reviewed.",
                "- Reject any semantically wrong transition / fallen sample in later review_queue processing.",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "source_dataset": str(source),
        "prepared_images": prepared_count,
        "prepared_labels": prepared_count,
        "review_policy": "Seeded from falling_transition_positive_batch_20260705 target images/labels; human review writes to human_review/labels and human_review/meta.",
        "source_dataset_unchanged": True,
    }
    (meta_dir / "prepare_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
