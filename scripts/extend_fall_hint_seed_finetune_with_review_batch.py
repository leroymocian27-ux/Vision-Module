from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
DEFAULT_BASE = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1_plus_batch031"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extend the seed finetune dataset by adding a fully reviewed hard-case batch to train only."
    )
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--batch-id", default="batch_031_hardcase_audit")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base = args.base.resolve()
    output = args.output.resolve()
    batch_dir = RAW_ROOT / args.batch_id

    if not (base / "data.yaml").exists():
        raise SystemExit(f"missing base dataset: {base}")
    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists; pass --overwrite to rebuild: {output}")
        shutil.rmtree(output)

    reviewed_items, validation_summary = collect_reviewed_batch(batch_dir)
    if validation_summary["ready_for_merge"] is not True:
        raise SystemExit(
            "review batch is not fully ready_for_merge; run validate_fall_hint_review_batch.py after finishing manual review"
        )

    shutil.copytree(base, output)
    manifest_path = output / "meta" / "manifest.csv"
    manifest_rows = read_csv(manifest_path)

    train_image_dir = output / "images" / "train"
    train_label_dir = output / "labels" / "train"
    added_rows: list[dict[str, object]] = []
    added_class_counts: Counter[str] = Counter()

    for index, item in enumerate(reviewed_items, start=1):
        out_stem = f"{args.batch_id}_{item['stem']}_{index:04d}"
        image_dst = train_image_dir / f"{out_stem}{item['image_path'].suffix.lower()}"
        label_dst = train_label_dir / f"{out_stem}.txt"
        shutil.copy2(item["image_path"], image_dst)
        shutil.copy2(item["label_path"], label_dst)
        class_names = " ".join(item["class_names"])
        class_ids = " ".join(str(value) for value in item["class_ids"])
        for class_name in item["class_names"]:
            added_class_counts[class_name] += 1
        manifest_rows.append(
            {
                "split": "train",
                "image": str(image_dst.relative_to(output)).replace("\\", "/"),
                "label": str(label_dst.relative_to(output)).replace("\\", "/"),
                "source_archive_image": "",
                "source_archive_label": "",
                "source_batch_id": args.batch_id,
                "source_original_image": item["image_name"],
                "source_video": item["source_video"],
                "video_id": item["video_id"],
                "classes": class_ids,
                "class_names": class_names,
                "source_role": "hardcase_review_train",
            }
        )
        added_rows.append(
            {
                "output_stem": out_stem,
                "image": path_for_report(image_dst),
                "label": path_for_report(label_dst),
                "source_batch_id": args.batch_id,
                "source_original_image": item["image_name"],
                "source_video": item["source_video"],
                "video_id": item["video_id"],
                "class_names": class_names,
            }
        )

    write_csv(manifest_path, manifest_rows)
    write_csv(output / "meta" / f"{args.batch_id}_added_rows.csv", added_rows)
    summary = {
        "base_dataset": str(base),
        "output_dataset": str(output),
        "added_batch_id": args.batch_id,
        "added_train_images": len(added_rows),
        "added_class_counts": dict(sorted(added_class_counts.items())),
        "val_test_preserved_from_base": True,
        "guardrails": [
            "Batch review must be fully complete before merge.",
            "New reviewed hard cases are added to train only.",
            "Base val/test and empty_holdout artifacts remain untouched.",
            "No augmented data is copied.",
        ],
    }
    (output / "meta" / f"{args.batch_id}_merge_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def path_for_report(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def collect_reviewed_batch(batch_dir: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    frames_dir = batch_dir / "frames"
    labels_dir = batch_dir / "human_review" / "labels"
    meta_dir = batch_dir / "human_review" / "meta"
    frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")
    images = sorted(path for path in frames_dir.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    reviewed_items: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    invalid_count = 0
    for image_path in images:
        stem = image_path.stem
        label_path = labels_dir / f"{stem}.txt"
        meta_path = meta_dir / f"{stem}.json"
        status = "draft"
        if meta_path.exists():
            try:
                status = str(json.loads(meta_path.read_text(encoding="utf-8")).get("status") or "draft")
            except json.JSONDecodeError:
                status = "bad_meta_json"
        status_counts[status] += 1
        if status != "reviewed":
            continue
        valid, class_ids, reason = validate_label(label_path)
        if not valid:
            invalid_count += 1
            continue
        meta_row = frame_manifest.get(image_path.name, {})
        reviewed_items.append(
            {
                "stem": stem,
                "image_name": image_path.name,
                "image_path": image_path,
                "label_path": label_path,
                "video_id": meta_row.get("video_id", image_path.name),
                "source_video": meta_row.get("source_video", ""),
                "class_ids": class_ids,
                "class_names": [CLASS_NAMES[value] for value in class_ids],
            }
        )
    summary = {
        "frame_count": len(images),
        "status_counts": dict(status_counts),
        "reviewed_valid_count": len(reviewed_items),
        "invalid_review_items": invalid_count,
        "ready_for_merge": len(reviewed_items) == len(images) and invalid_count == 0,
    }
    return reviewed_items, summary


def validate_label(path: Path) -> tuple[bool, tuple[int, ...], str]:
    if not path.exists():
        return False, tuple(), "missing_label"
    class_ids: list[int] = []
    for line_index, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, tuple(), f"line_{line_index}_bad_column_count"
        try:
            cls = int(float(parts[0]))
            x_center, y_center, width, height = [float(value) for value in parts[1:]]
        except ValueError:
            return False, tuple(), f"line_{line_index}_non_numeric"
        if cls < 0 or cls >= len(CLASS_NAMES):
            return False, tuple(), f"line_{line_index}_bad_class_{cls}"
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            return False, tuple(), f"line_{line_index}_bad_bbox"
        class_ids.append(cls)
    return True, tuple(class_ids), ""


def read_frame_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
