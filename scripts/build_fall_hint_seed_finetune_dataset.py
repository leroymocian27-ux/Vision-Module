from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POSITIVE_DATASET = ROOT / "datasets" / "fall_hint_v2_clean_reviewed_only_noaug_20260703"
DEFAULT_REVIEWED_SOURCE = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_finetune_seed_7_3testmodel_v1"

CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class EmptyItem:
    row: dict[str, str]
    image_path: Path
    label_path: Path
    stem: str
    sort_key: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a seed finetune dataset by reusing reviewed positive splits and adding reviewed empty negatives."
    )
    parser.add_argument("--positive-dataset", type=Path, default=DEFAULT_POSITIVE_DATASET)
    parser.add_argument("--reviewed-source", type=Path, default=DEFAULT_REVIEWED_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--empty-train-ratio", type=float, default=0.05)
    parser.add_argument("--empty-train-max-ratio", type=float, default=0.08)
    parser.add_argument("--empty-holdout-count", type=int, default=40)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


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


def read_label_classes(path: Path) -> tuple[bool, tuple[int, ...], str]:
    if not path.exists():
        return False, tuple(), "missing_label"
    classes: list[int] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, tuple(), f"line_{line_no}_bad_column_count"
        try:
            cls = int(float(parts[0]))
            x, y, w, h = [float(value) for value in parts[1:]]
        except ValueError:
            return False, tuple(), f"line_{line_no}_non_numeric"
        if cls < 0 or cls >= len(CLASS_NAMES):
            return False, tuple(), f"line_{line_no}_bad_class_{cls}"
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            return False, tuple(), f"line_{line_no}_bad_bbox"
        classes.append(cls)
    return True, tuple(classes), ""


def audit_excluded_archive_images(source: Path) -> set[str]:
    excluded: set[str] = set()
    meta = source / "meta"
    for filename in ["relabel_duplicate_class_conflicts.csv", "relabel_invalid_labels.csv"]:
        for row in read_csv(meta / filename):
            archive_image = row.get("archive_image", "")
            if archive_image:
                excluded.add(archive_image)
    return excluded


def hashed_sort_key(seed: int, *parts: str) -> str:
    return hashlib.sha256("|".join([str(seed), *parts]).encode("utf-8")).hexdigest()


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"missing source directory: {src}")
    shutil.copytree(src, dst)


def ensure_positive_dataset(dataset: Path) -> tuple[list[dict[str, str]], dict[str, dict[str, object]]]:
    manifest_path = dataset / "meta" / "manifest.csv"
    summary_path = dataset / "meta" / "build_summary.json"
    if not manifest_path.exists():
        raise SystemExit(f"missing positive manifest: {manifest_path}")
    if not summary_path.exists():
        raise SystemExit(f"missing positive build summary: {summary_path}")
    manifest = read_csv(manifest_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for split in ["train", "val", "test"]:
        image_dir = dataset / "images" / split
        label_dir = dataset / "labels" / split
        if not image_dir.exists() or not label_dir.exists():
            raise SystemExit(f"positive dataset missing split directories for {split}: {dataset}")
    return manifest, summary["split_counts"]


def collect_empty_candidates(source: Path, seed: int) -> tuple[list[EmptyItem], list[dict[str, object]]]:
    excluded_images = audit_excluded_archive_images(source)
    candidates: list[EmptyItem] = []
    skipped: list[dict[str, object]] = []
    for row in read_csv(source / "meta" / "manifest.csv"):
        image_rel = row.get("new_image", "")
        label_rel = row.get("new_label", "")
        image_path = source / image_rel
        label_path = source / label_rel
        image_name = Path(image_rel).name
        valid, classes, reason = read_label_classes(label_path)
        if image_name in excluded_images:
            reason = "excluded_by_relabel_audit"
        elif not image_path.exists():
            reason = "missing_image"
        elif not valid:
            reason = reason or "invalid_label"
        elif classes:
            reason = "not_empty_label"
        if reason:
            skipped.append(
                {
                    "archive_image": image_name,
                    "archive_label": Path(label_rel).name,
                    "batch_id": row.get("batch_id", ""),
                    "source_video": row.get("source_video", ""),
                    "reason": reason,
                }
            )
            continue
        candidates.append(
            EmptyItem(
                row=row,
                image_path=image_path,
                label_path=label_path,
                stem=Path(image_name).stem,
                sort_key=hashed_sort_key(
                    seed,
                    row.get("source_video", ""),
                    row.get("batch_id", ""),
                    row.get("original_image", ""),
                    image_name,
                ),
            )
        )
    candidates.sort(key=lambda item: item.sort_key)
    return candidates, skipped


def copy_empty_item(item: EmptyItem, image_dir: Path, label_dir: Path) -> tuple[str, str]:
    image_name = f"{item.stem}{item.image_path.suffix.lower()}"
    label_name = f"{item.stem}.txt"
    image_out = image_dir / image_name
    label_out = label_dir / label_name
    shutil.copy2(item.image_path, image_out)
    shutil.copy2(item.label_path, label_out)
    return image_name, label_name


def count_boxes(label_dir: Path) -> tuple[int, int, Counter[int]]:
    labels = sorted(label_dir.glob("*.txt"))
    counts: Counter[int] = Counter()
    empty = 0
    for label_path in labels:
        valid, classes, reason = read_label_classes(label_path)
        if not valid:
            raise SystemExit(f"invalid label in output: {label_path} -> {reason}")
        if not classes:
            empty += 1
        counts.update(classes)
    return len(labels), empty, counts


def validate_images_and_labels(image_dir: Path, label_dir: Path) -> None:
    image_stems = {path.stem for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES}
    label_stems = {path.stem for path in label_dir.glob("*.txt")}
    if image_stems != label_stems:
        missing = sorted(image_stems - label_stems)
        orphan = sorted(label_stems - image_stems)
        raise SystemExit(f"image/label mismatch in {image_dir.parent.name}: missing={missing[:10]} orphan={orphan[:10]}")


def write_data_yaml(output: Path) -> None:
    (output / "data.yaml").write_text(
        "\n".join(
            [
                f"path: {output.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                *[f"  {idx}: {name}" for idx, name in enumerate(CLASS_NAMES)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (output / "classes.txt").write_text("\n".join(CLASS_NAMES) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    positive_dataset = args.positive_dataset.resolve()
    reviewed_source = args.reviewed_source.resolve()
    output = args.output.resolve()
    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"output exists, refuse to overwrite without --overwrite: {output}")
        shutil.rmtree(output)

    positive_manifest, positive_splits = ensure_positive_dataset(positive_dataset)
    candidates, skipped = collect_empty_candidates(reviewed_source, args.seed)
    if len(candidates) <= args.empty_holdout_count:
        raise SystemExit("not enough empty reviewed items for requested holdout")

    positive_train_count = int(positive_splits["train"]["images"])
    empty_train_cap = int(math.floor(positive_train_count * args.empty_train_ratio))
    if empty_train_cap <= 0:
        raise SystemExit("empty train cap computed to zero; increase ratio or inspect positive dataset size")
    max_allowed = int(math.floor(positive_train_count * args.empty_train_max_ratio))
    if empty_train_cap > max_allowed:
        empty_train_cap = max_allowed

    holdout_items = candidates[: args.empty_holdout_count]
    train_items = candidates[args.empty_holdout_count : args.empty_holdout_count + empty_train_cap]

    if len(train_items) < empty_train_cap:
        raise SystemExit("not enough empty reviewed items after holdout selection")

    for src_name, dst_name in [("images", "images"), ("labels", "labels"), ("meta", "meta")]:
        copy_tree(positive_dataset / src_name, output / dst_name)

    audit_root = output / "audits" / "empty_holdout"
    (audit_root / "images").mkdir(parents=True, exist_ok=True)
    (audit_root / "labels").mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(output / "meta" / "manifest.csv")
    for row in manifest_rows:
        row["source_role"] = "reviewed_positive"

    train_image_dir = output / "images" / "train"
    train_label_dir = output / "labels" / "train"
    empty_train_rows: list[dict[str, object]] = []
    for item in train_items:
        image_name, label_name = copy_empty_item(item, train_image_dir, train_label_dir)
        row = {
            "split": "train",
            "image": f"images/train/{image_name}",
            "label": f"labels/train/{label_name}",
            "source_archive_image": item.row.get("new_image", ""),
            "source_archive_label": item.row.get("new_label", ""),
            "source_batch_id": item.row.get("batch_id", ""),
            "source_original_image": item.row.get("original_image", ""),
            "source_video": item.row.get("source_video", ""),
            "video_id": item.row.get("video_id", ""),
            "classes": "",
            "class_names": "",
            "source_role": "reviewed_empty_train",
        }
        manifest_rows.append(row)
        empty_train_rows.append(row)

    holdout_rows: list[dict[str, object]] = []
    for item in holdout_items:
        image_name, label_name = copy_empty_item(item, audit_root / "images", audit_root / "labels")
        holdout_rows.append(
            {
                "split": "empty_holdout",
                "image": f"audits/empty_holdout/images/{image_name}",
                "label": f"audits/empty_holdout/labels/{label_name}",
                "source_archive_image": item.row.get("new_image", ""),
                "source_archive_label": item.row.get("new_label", ""),
                "source_batch_id": item.row.get("batch_id", ""),
                "source_original_image": item.row.get("original_image", ""),
                "source_video": item.row.get("source_video", ""),
                "video_id": item.row.get("video_id", ""),
                "source_role": "reviewed_empty_holdout",
            }
        )

    for split in ["train", "val", "test"]:
        validate_images_and_labels(output / "images" / split, output / "labels" / split)
    validate_images_and_labels(audit_root / "images", audit_root / "labels")

    write_data_yaml(output)
    write_csv(output / "meta" / "manifest.csv", manifest_rows)
    write_csv(output / "meta" / "empty_train_manifest.csv", empty_train_rows)
    write_csv(output / "meta" / "empty_holdout_manifest.csv", holdout_rows)
    write_csv(output / "meta" / "empty_candidates_skipped.csv", skipped)

    split_counts: dict[str, dict[str, object]] = {}
    for split in ["train", "val", "test"]:
        label_count, empty_count, box_counts = count_boxes(output / "labels" / split)
        image_count = len([p for p in (output / "images" / split).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
        split_counts[split] = {
            "images": image_count,
            "labels": label_count,
            "empty_labels": empty_count,
            "boxes": sum(box_counts.values()),
            "class_box_counts": {CLASS_NAMES[idx]: box_counts.get(idx, 0) for idx in range(len(CLASS_NAMES))},
        }

    holdout_label_count, holdout_empty_count, holdout_box_counts = count_boxes(audit_root / "labels")
    holdout_image_count = len([p for p in (audit_root / "images").iterdir() if p.suffix.lower() in IMAGE_SUFFIXES])
    summary = {
        "positive_dataset": str(positive_dataset),
        "reviewed_source": str(reviewed_source),
        "output": str(output),
        "seed": args.seed,
        "empty_train_ratio": args.empty_train_ratio,
        "empty_train_max_ratio": args.empty_train_max_ratio,
        "empty_train_cap": empty_train_cap,
        "empty_holdout_count": args.empty_holdout_count,
        "positive_train_count": positive_train_count,
        "selected_empty_train_count": len(train_items),
        "selected_empty_holdout_count": len(holdout_items),
        "unused_empty_candidates": max(0, len(candidates) - len(train_items) - len(holdout_items)),
        "split_counts": split_counts,
        "empty_holdout": {
            "images": holdout_image_count,
            "labels": holdout_label_count,
            "empty_labels": holdout_empty_count,
            "boxes": sum(holdout_box_counts.values()),
        },
        "guardrails": [
            "Primary val/test are copied unchanged from the reviewed-only positive dataset.",
            "Only reviewed archive empty-label items are added to train.",
            "Reviewed relabel conflict and invalid-label archives are excluded.",
            "No augmented data is copied.",
        ],
    }
    (output / "meta" / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
