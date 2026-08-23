from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEWED = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_AUGMENTED = ROOT / "datasets" / "fall_hint_v2_augmented_only_b001_b029"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_training_reviewed_aug_filtered_20260702"

CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]


@dataclass(frozen=True)
class ReviewedItem:
    row: dict[str, str]
    image_path: Path
    label_path: Path
    image_name: str
    label_name: str
    stem: str
    split_key: str
    classes: tuple[int, ...]
    is_empty: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a YOLO Fall Hint training dataset from reviewed originals plus "
            "filtered augmented copies. Augmented samples are train-only."
        )
    )
    parser.add_argument("--reviewed", type=Path, default=DEFAULT_REVIEWED)
    parser.add_argument("--augmented", type=Path, default=DEFAULT_AUGMENTED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--test-ratio", type=float, default=0.10)
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


def validate_label(path: Path) -> tuple[bool, tuple[int, ...], str]:
    if not path.exists():
        return False, tuple(), "missing_label"
    classes: list[int] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            return False, tuple(), f"line_{line_no}_bad_column_count_{len(parts)}"
        try:
            cls = int(float(parts[0]))
            x, y, w, h = [float(v) for v in parts[1:]]
        except ValueError:
            return False, tuple(), f"line_{line_no}_non_numeric"
        if cls < 0 or cls >= len(CLASS_NAMES):
            return False, tuple(), f"line_{line_no}_bad_class_{cls}"
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            return False, tuple(), f"line_{line_no}_bad_bbox"
        classes.append(cls)
    return True, tuple(classes), ""


def load_exclusion_sets(reviewed: Path) -> tuple[set[str], set[tuple[str, str]], list[dict[str, object]]]:
    meta = reviewed / "meta"
    excluded_archive_images: set[str] = set()
    excluded_batch_images: set[tuple[str, str]] = set()
    rows: list[dict[str, object]] = []

    for row in read_csv(meta / "relabel_duplicate_class_conflicts.csv"):
        archive_image = row.get("archive_image", "")
        if archive_image:
            excluded_archive_images.add(archive_image)
            rows.append(
                {
                    "source": "relabel_duplicate_class_conflicts.csv",
                    "reason": "duplicate_class_conflict_pending_repair",
                    "archive_image": archive_image,
                    "batch_id": row.get("batch_id", ""),
                    "original_image": row.get("original_image", ""),
                    "group_id": row.get("group_id", ""),
                    "classes": row.get("classes", ""),
                }
            )

    for row in read_csv(meta / "relabel_invalid_labels.csv"):
        archive_image = row.get("archive_image", "")
        if archive_image:
            excluded_archive_images.add(archive_image)
            rows.append(
                {
                    "source": "relabel_invalid_labels.csv",
                    "reason": "invalid_label_pending_repair",
                    "archive_image": archive_image,
                    "batch_id": row.get("batch_id", ""),
                    "original_image": row.get("original_image", ""),
                    "group_id": row.get("group_id", ""),
                    "classes": row.get("classes", ""),
                }
            )

    for row in read_csv(meta / "relabel_untrusted_frames.csv"):
        batch_id = row.get("batch_id", "")
        image = row.get("image", "")
        if batch_id and image:
            excluded_batch_images.add((batch_id, image))
            rows.append(
                {
                    "source": "relabel_untrusted_frames.csv",
                    "reason": "untrusted_no_review_meta",
                    "archive_image": "",
                    "batch_id": batch_id,
                    "original_image": image,
                    "group_id": "",
                    "classes": "",
                }
            )

    return excluded_archive_images, excluded_batch_images, rows


def collect_reviewed_items(reviewed: Path, excluded_archive: set[str], excluded_batch_images: set[tuple[str, str]]) -> tuple[list[ReviewedItem], list[dict[str, object]]]:
    manifest = read_csv(reviewed / "meta" / "manifest.csv")
    items: list[ReviewedItem] = []
    skipped: list[dict[str, object]] = []

    for row in manifest:
        image_rel = row.get("new_image", "")
        label_rel = row.get("new_label", "")
        image_name = Path(image_rel).name
        label_name = Path(label_rel).name
        batch_id = row.get("batch_id", "")
        original_image = row.get("original_image", "")

        reason = ""
        if image_name in excluded_archive:
            reason = "excluded_by_relabel_audit_archive_image"
        elif (batch_id, original_image) in excluded_batch_images:
            reason = "excluded_by_untrusted_original_frame"

        image_path = reviewed / image_rel
        label_path = reviewed / label_rel
        if not reason and not image_path.exists():
            reason = "missing_image"
        valid, classes, label_reason = validate_label(label_path)
        if not reason and not valid:
            reason = label_reason

        if reason:
            skipped.append(
                {
                    "dataset": "reviewed",
                    "reason": reason,
                    "image": image_name,
                    "label": label_name,
                    "batch_id": batch_id,
                    "original_image": original_image,
                }
            )
            continue

        split_key = row.get("source_video") or row.get("video_id") or row.get("group") or image_name
        items.append(
            ReviewedItem(
                row=row,
                image_path=image_path,
                label_path=label_path,
                image_name=image_name,
                label_name=label_name,
                stem=Path(image_name).stem,
                split_key=split_key,
                classes=classes,
                is_empty=len(classes) == 0,
            )
        )

    return items, skipped


def split_reviewed_items(items: list[ReviewedItem], seed: int, train_ratio: float, val_ratio: float, test_ratio: float) -> dict[str, list[ReviewedItem]]:
    total_ratio = train_ratio + val_ratio + test_ratio
    if abs(total_ratio - 1.0) > 0.0001:
        raise ValueError(f"split ratios must sum to 1.0, got {total_ratio}")

    groups: dict[str, list[ReviewedItem]] = defaultdict(list)
    for item in items:
        groups[item.split_key].append(item)

    group_items = list(groups.items())

    def sort_key(entry: tuple[str, list[ReviewedItem]]) -> str:
        digest = hashlib.sha256(f"{seed}:{entry[0]}".encode("utf-8")).hexdigest()
        return digest

    group_items.sort(key=sort_key)
    total = len(items)
    target = {
        "train": int(total * train_ratio),
        "val": int(total * val_ratio),
        "test": total - int(total * train_ratio) - int(total * val_ratio),
    }

    splits: dict[str, list[ReviewedItem]] = {"train": [], "val": [], "test": []}
    for key, group in group_items:
        del key
        counts = {name: len(values) for name, values in splits.items()}
        deficits = {name: target[name] - counts[name] for name in splits}
        preferred = max(deficits, key=lambda name: (deficits[name], -counts[name], name))
        if deficits[preferred] <= 0:
            preferred = min(counts, key=lambda name: (counts[name] / max(1, target[name]), counts[name], name))
        splits[preferred].extend(group)

    return splits


def class_counts_for_labels(label_paths: list[Path]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for path in label_paths:
        valid, classes, reason = validate_label(path)
        if not valid:
            raise ValueError(f"invalid label after copy: {path} {reason}")
        counts.update(classes)
    return counts


def copy_pair(src_image: Path, src_label: Path, dst_images: Path, dst_labels: Path) -> None:
    dst_images.mkdir(parents=True, exist_ok=True)
    dst_labels.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_image, dst_images / src_image.name)
    shutil.copy2(src_label, dst_labels / src_label.name)


def build_dataset(args: argparse.Namespace) -> dict[str, object]:
    reviewed = args.reviewed.resolve()
    augmented = args.augmented.resolve()
    output = args.output.resolve()

    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"Output exists, refuse to overwrite without --overwrite: {output}")
        shutil.rmtree(output)

    for split in ["train", "val", "test"]:
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)
    (output / "meta").mkdir(parents=True, exist_ok=True)

    excluded_archive, excluded_batch_images, exclusion_rows = load_exclusion_sets(reviewed)
    reviewed_items, skipped = collect_reviewed_items(reviewed, excluded_archive, excluded_batch_images)
    if not reviewed_items:
        raise SystemExit("No reviewed items left after filtering.")

    splits = split_reviewed_items(
        reviewed_items,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
    )

    manifest_rows: list[dict[str, object]] = []
    train_stems = {item.stem for item in splits["train"]}
    for split, items in splits.items():
        for item in items:
            copy_pair(item.image_path, item.label_path, output / "images" / split, output / "labels" / split)
            manifest_rows.append(
                {
                    "split": split,
                    "kind": "reviewed_original",
                    "image": f"images/{split}/{item.image_name}",
                    "label": f"labels/{split}/{item.label_name}",
                    "source_image": item.row.get("new_image", ""),
                    "source_label": item.row.get("new_label", ""),
                    "source_batch_id": item.row.get("batch_id", ""),
                    "source_original_image": item.row.get("original_image", ""),
                    "source_video": item.row.get("source_video", ""),
                    "classes": " ".join(str(c) for c in item.classes),
                    "is_empty_label": str(item.is_empty).lower(),
                }
            )

    aug_manifest = read_csv(augmented / "meta" / "augment_manifest.csv")
    aug_kept = 0
    for row in aug_manifest:
        source_stem = row.get("source_new_stem", "")
        augmented_image_rel = row.get("augmented_image", "")
        augmented_label_rel = row.get("augmented_label", "")
        if source_stem not in train_stems:
            skipped.append(
                {
                    "dataset": "augmented",
                    "reason": "source_not_in_filtered_train_split",
                    "image": Path(augmented_image_rel).name,
                    "label": Path(augmented_label_rel).name,
                    "batch_id": row.get("source_batch_id", ""),
                    "original_image": row.get("source_original_image", ""),
                }
            )
            continue
        image_path = augmented / augmented_image_rel
        label_path = augmented / augmented_label_rel
        valid, classes, reason = validate_label(label_path)
        if not image_path.exists() or not valid:
            skipped.append(
                {
                    "dataset": "augmented",
                    "reason": "missing_or_invalid_augmented_pair" if not image_path.exists() else reason,
                    "image": Path(augmented_image_rel).name,
                    "label": Path(augmented_label_rel).name,
                    "batch_id": row.get("source_batch_id", ""),
                    "original_image": row.get("source_original_image", ""),
                }
            )
            continue
        copy_pair(image_path, label_path, output / "images" / "train", output / "labels" / "train")
        aug_kept += 1
        manifest_rows.append(
            {
                "split": "train",
                "kind": "augmented_train_only",
                "image": f"images/train/{image_path.name}",
                "label": f"labels/train/{label_path.name}",
                "source_image": row.get("source_image", ""),
                "source_label": row.get("source_label", ""),
                "source_batch_id": row.get("source_batch_id", ""),
                "source_original_image": row.get("source_original_image", ""),
                "source_video": "",
                "classes": " ".join(str(c) for c in classes),
                "is_empty_label": str(len(classes) == 0).lower(),
                "augmentation_name": row.get("augmentation_name", ""),
                "augmentation_params": row.get("augmentation_params", ""),
            }
        )

    data_yaml = output / "data.yaml"
    names_yaml = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(CLASS_NAMES))
    data_yaml.write_text(
        "\n".join(
            [
                f"path: {output.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "names:",
                names_yaml,
                "",
            ]
        ),
        encoding="utf-8",
    )

    split_counts: dict[str, dict[str, object]] = {}
    validation_errors: list[str] = []
    for split in ["train", "val", "test"]:
        images = sorted((output / "images" / split).glob("*"))
        labels = sorted((output / "labels" / split).glob("*.txt"))
        image_stems = {p.stem for p in images}
        label_stems = {p.stem for p in labels}
        missing_labels = sorted(image_stems - label_stems)
        orphan_labels = sorted(label_stems - image_stems)
        if missing_labels:
            validation_errors.append(f"{split}: missing labels for {missing_labels[:10]}")
        if orphan_labels:
            validation_errors.append(f"{split}: orphan labels for {orphan_labels[:10]}")
        counts = class_counts_for_labels(labels)
        split_counts[split] = {
            "images": len(images),
            "labels": len(labels),
            "empty_labels": sum(1 for label in labels if not label.read_text(encoding="utf-8").strip()),
            "class_box_counts": {CLASS_NAMES[idx]: counts.get(idx, 0) for idx in range(len(CLASS_NAMES))},
        }

    if validation_errors:
        raise SystemExit("Validation failed: " + "; ".join(validation_errors))

    write_csv(output / "meta" / "manifest.csv", manifest_rows)
    write_csv(output / "meta" / "skipped.csv", skipped)
    write_csv(output / "meta" / "excluded_by_audit.csv", exclusion_rows)
    summary = {
        "reviewed_source": str(reviewed),
        "augmented_source": str(augmented),
        "output": str(output),
        "seed": args.seed,
        "split_ratios": {
            "train": args.train_ratio,
            "val": args.val_ratio,
            "test": args.test_ratio,
        },
        "reviewed_items_after_filter": len(reviewed_items),
        "reviewed_split_counts": {split: len(items) for split, items in splits.items()},
        "augmented_train_items_kept": aug_kept,
        "skipped_count": len(skipped),
        "excluded_audit_row_count": len(exclusion_rows),
        "split_counts": split_counts,
        "guardrails": [
            "Unresolved duplicate class conflicts are excluded.",
            "Untrusted rows without reviewed meta are excluded.",
            "Augmented samples are used in train only.",
            "Validation and test splits contain original reviewed samples only.",
            "Source reviewed and augmented-only directories are not modified.",
        ],
    }
    (output / "meta" / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    args = parse_args()
    random.seed(args.seed)
    summary = build_dataset(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
