from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
SOURCE_ROOT = ROOT / "datasets" / "falling_transition_positive_batch_20260705"
DEFAULT_BATCH_ID = "batch_034_falling_transition_positive_review_20260705"
DEFAULT_OUTPUT = ROOT / "datasets" / "falling_transition_positive_batch_20260705_reviewed_final"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Finalize the reviewed falling-transition positive batch into a reusable reviewed dataset package."
    )
    parser.add_argument("--source", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


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
    output = args.output.resolve()
    batch_dir = RAW_ROOT / args.batch_id
    validation_summary_path = batch_dir / "meta" / "review_validation_summary.json"
    reviewed_rows_path = batch_dir / "meta" / "review_validation_reviewed_rows.csv"

    if not validation_summary_path.exists():
        raise SystemExit(f"missing validation summary: {validation_summary_path}")
    if not reviewed_rows_path.exists():
        raise SystemExit(f"missing reviewed rows: {reviewed_rows_path}")

    validation_summary = json.loads(validation_summary_path.read_text(encoding="utf-8"))
    if validation_summary.get("ready_for_merge") is not True:
        raise SystemExit("review batch is not ready_for_merge; finalize only after full reviewed validation passes")

    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists, pass --overwrite to rebuild: {output}")
        shutil.rmtree(output)

    source_manifest = {row["item_id"]: row for row in read_csv(source / "manifest.csv")}
    source_review_queue = {row["item_id"]: row for row in read_csv(source / "review_queue.csv")}
    reviewed_rows = read_csv(reviewed_rows_path)

    image_dir = output / "images"
    label_dir = output / "labels"
    meta_dir = output / "meta"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[dict[str, object]] = []
    review_queue_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    transition_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    reviewed_class_counter: Counter[str] = Counter()

    for reviewed in reviewed_rows:
        item_id = Path(reviewed["image"]).stem
        source_row = source_manifest[item_id]
        queue_row = source_review_queue.get(item_id, {})
        notes = parse_notes(source_row.get("notes", ""))
        category = source_row["category"]
        original_class = source_row["class_name"]
        reviewed_counts = json.loads(reviewed["class_counts"]) if reviewed.get("class_counts") else {}
        reviewed_classes = list(reviewed_counts.keys())
        reviewed_class = reviewed_classes[0] if len(reviewed_classes) == 1 else "__multi__"
        reviewed_box_count = int(reviewed["box_count"]) if reviewed.get("box_count") else 0

        src_image = Path(source_row["target_image_path"])
        src_label = batch_dir / "human_review" / "labels" / f"{item_id}.txt"
        dst_image = image_dir / f"{item_id}{src_image.suffix.lower()}"
        dst_label = label_dir / f"{item_id}.txt"
        shutil.copy2(src_image, dst_image)
        shutil.copy2(src_label, dst_label)

        manifest_rows.append(
            {
                "item_id": item_id,
                "category": category,
                "original_candidate_class": original_class,
                "reviewed_class": reviewed_class,
                "reviewed_class_counts": json.dumps(reviewed_counts, ensure_ascii=False, sort_keys=True),
                "reviewed_box_count": reviewed_box_count,
                "source_dataset": source_row["source_dataset"],
                "source_image_path": source_row["source_image_path"],
                "source_label_path": source_row["source_label_path"],
                "final_image_path": str(dst_image),
                "final_label_path": str(dst_label),
                "source_video_id": source_row["source_video_id"],
                "frame_index": source_row["frame_index"],
                "near_miss_pattern": source_row["near_miss_pattern"],
                "is_positive_repair": source_row["is_positive_repair"],
                "manual_review_required": False,
                "review_batch_id": args.batch_id,
                "review_status": reviewed["status"],
                "source_batch_id": notes.get("batch_id", ""),
                "source_original_image": notes.get("original_image", ""),
                "source_video": notes.get("source_video", ""),
                "width": source_row["width"],
                "height": source_row["height"],
                "notes": source_row.get("notes", ""),
            }
        )
        review_queue_rows.append(
            {
                "item_id": item_id,
                "category": category,
                "target_image_path": str(dst_image),
                "target_label_path": str(dst_label),
                "review_decision": "accepted",
                "correct_class": reviewed_class,
                "usable_for_training": "accepted",
                "usable_for_validation": "pending",
                "reject_reason": "",
                "review_notes": f"manual review completed in {args.batch_id}",
            }
        )
        transition_rows.append(
            {
                "item_id": item_id,
                "category": category,
                "original_candidate_class": original_class,
                "reviewed_class": reviewed_class,
                "changed": original_class != reviewed_class,
                "source_batch_id": notes.get("batch_id", ""),
                "source_original_image": notes.get("original_image", ""),
            }
        )

        transition_counter[f"{original_class} -> {reviewed_class}"] += 1
        category_counter[category] += 1
        reviewed_class_counter[reviewed_class] += 1

    summary = {
        "dataset_name": output.name,
        "source_dataset": str(source),
        "review_batch_id": args.batch_id,
        "total_items": len(manifest_rows),
        "category_counts": dict(sorted(category_counter.items())),
        "reviewed_class_counts": dict(sorted(reviewed_class_counter.items())),
        "class_transition_counts": dict(sorted(transition_counter.items())),
        "changed_class_count": sum(1 for row in transition_rows if row["changed"]),
        "unchanged_class_count": sum(1 for row in transition_rows if not row["changed"]),
        "ready_for_training_candidate": True,
        "validation_ready_for_merge": True,
        "notes": [
            "This package contains only the 117 manually reviewed samples.",
            "Reviewed labels come from human_review/labels and replace the seed candidate labels.",
            "review_queue_final.csv marks all manually reviewed items as accepted for training candidate use.",
            "Validation and test use should still be decided separately in the next stage.",
        ],
    }

    write_csv(output / "manifest.csv", manifest_rows)
    write_csv(output / "review_queue_final.csv", review_queue_rows)
    write_csv(meta_dir / "class_transition.csv", transition_rows)
    write_json(output / "summary.json", summary)
    write_text(
        output / "README.md",
        "\n".join(
            [
                f"# {output.name}",
                "",
                "This folder contains the finalized reviewed version of",
                "`falling_transition_positive_batch_20260705`.",
                "",
                "What changed:",
                "- Images remain the same reviewed candidates.",
                "- Labels are replaced with the human-reviewed labels from the review batch.",
                "- `review_queue_final.csv` marks this reviewed packet as accepted for future training-candidate use.",
                "- Validation/test inclusion should still be decided in the next dataset-build stage.",
                "",
            ]
        )
        + "\n",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
