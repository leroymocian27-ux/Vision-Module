from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_reviewed_only_filtered_b001_b029_20260703"

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
class Item:
    row: dict[str, str]
    image_path: Path
    label_path: Path
    output_stem: str
    split_key: str
    classes: tuple[int, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a reviewed-only YOLO Fall Hint dataset without offline augmentation."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.16)
    parser.add_argument("--test-ratio", type=float, default=0.04)
    parser.add_argument("--include-empty", action="store_true")
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


def audit_excluded_archive_images(source: Path) -> tuple[set[str], list[dict[str, object]]]:
    meta = source / "meta"
    excluded: set[str] = set()
    rows: list[dict[str, object]] = []
    for filename, reason in [
        ("relabel_duplicate_class_conflicts.csv", "duplicate_class_conflict_pending_repair"),
        ("relabel_invalid_labels.csv", "invalid_label_pending_repair"),
    ]:
        for row in read_csv(meta / filename):
            archive_image = row.get("archive_image", "")
            if not archive_image:
                continue
            excluded.add(archive_image)
            rows.append(
                {
                    "source_file": filename,
                    "reason": reason,
                    "archive_image": archive_image,
                    "batch_id": row.get("batch_id", ""),
                    "original_image": row.get("original_image", ""),
                    "group_id": row.get("group_id", ""),
                    "classes": row.get("classes", ""),
                }
            )
    return excluded, rows


def collect_items(source: Path, include_empty: bool) -> tuple[list[Item], list[dict[str, object]], list[dict[str, object]]]:
    excluded_images, exclusion_rows = audit_excluded_archive_images(source)
    items: list[Item] = []
    skipped: list[dict[str, object]] = []
    for row in read_csv(source / "meta" / "manifest.csv"):
        image_rel = row.get("new_image", "")
        label_rel = row.get("new_label", "")
        image_name = Path(image_rel).name
        label_name = Path(label_rel).name
        image_path = source / image_rel
        label_path = source / label_rel
        valid, classes, reason = validate_label(label_path)
        if image_name in excluded_images:
            reason = "excluded_by_relabel_audit"
        elif not image_path.exists():
            reason = "missing_image"
        elif not valid:
            reason = reason or "invalid_label"
        elif not classes and not include_empty:
            reason = "empty_label_excluded_to_match_best_flow"
        if reason:
            skipped.append(
                {
                    "reason": reason,
                    "archive_image": image_name,
                    "archive_label": label_name,
                    "batch_id": row.get("batch_id", ""),
                    "original_image": row.get("original_image", ""),
                    "source_video": row.get("source_video", ""),
                }
            )
            continue
        split_key = row.get("source_video") or row.get("video_id") or row.get("group") or image_name
        output_stem = Path(image_name).stem
        items.append(
            Item(
                row=row,
                image_path=image_path,
                label_path=label_path,
                output_stem=output_stem,
                split_key=split_key,
                classes=classes,
            )
        )
    return items, skipped, exclusion_rows


def split_items(items: list[Item], seed: int, train_ratio: float, val_ratio: float, test_ratio: float) -> dict[str, list[Item]]:
    if abs((train_ratio + val_ratio + test_ratio) - 1.0) > 1e-6:
        raise ValueError("split ratios must sum to 1.0")
    groups: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        groups[item.split_key].append(item)
    grouped = list(groups.items())
    grouped.sort(key=lambda entry: hashlib.sha256(f"{seed}:{entry[0]}".encode("utf-8")).hexdigest())
    total = len(items)
    targets = {
        "train": int(total * train_ratio),
        "val": int(total * val_ratio),
        "test": total - int(total * train_ratio) - int(total * val_ratio),
    }
    splits: dict[str, list[Item]] = {"train": [], "val": [], "test": []}
    for _, group in grouped:
        deficits = {name: targets[name] - len(values) for name, values in splits.items()}
        split = max(deficits, key=lambda name: (deficits[name], -len(splits[name]), name))
        if deficits[split] <= 0:
            split = min(splits, key=lambda name: (len(splits[name]) / max(1, targets[name]), len(splits[name]), name))
        splits[split].extend(group)
    return splits


def copy_item(item: Item, output: Path, split: str) -> tuple[str, str]:
    image_name = f"{item.output_stem}{item.image_path.suffix.lower()}"
    label_name = f"{item.output_stem}.txt"
    image_out = output / "images" / split / image_name
    label_out = output / "labels" / split / label_name
    image_out.parent.mkdir(parents=True, exist_ok=True)
    label_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.image_path, image_out)
    shutil.copy2(item.label_path, label_out)
    return f"images/{split}/{image_name}", f"labels/{split}/{label_name}"


def count_split(output: Path, split: str) -> dict[str, object]:
    image_dir = output / "images" / split
    label_dir = output / "labels" / split
    labels = sorted(label_dir.glob("*.txt"))
    images = [p for p in image_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    image_stems = {path.stem for path in images}
    label_stems = {path.stem for path in labels}
    if image_stems != label_stems:
        missing = sorted(image_stems - label_stems)
        orphan = sorted(label_stems - image_stems)
        raise SystemExit(f"{split} image/label mismatch missing={missing[:10]} orphan={orphan[:10]}")
    counts: Counter[int] = Counter()
    empty = 0
    for label in labels:
        valid, classes, reason = validate_label(label)
        if not valid:
            raise SystemExit(f"invalid output label {label}: {reason}")
        if not classes:
            empty += 1
        counts.update(classes)
    return {
        "images": len(images),
        "labels": len(labels),
        "empty_labels": empty,
        "boxes": sum(counts.values()),
        "class_box_counts": {CLASS_NAMES[idx]: counts.get(idx, 0) for idx in range(len(CLASS_NAMES))},
    }


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if output.exists():
        if not args.overwrite:
            raise SystemExit(f"Output exists, refuse to overwrite without --overwrite: {output}")
        shutil.rmtree(output)
    for split in ["train", "val", "test"]:
        (output / "images" / split).mkdir(parents=True, exist_ok=True)
        (output / "labels" / split).mkdir(parents=True, exist_ok=True)
    (output / "meta").mkdir(parents=True, exist_ok=True)

    items, skipped, exclusion_rows = collect_items(source, include_empty=args.include_empty)
    if not items:
        raise SystemExit("no reviewed items after filtering")
    splits = split_items(items, args.seed, args.train_ratio, args.val_ratio, args.test_ratio)

    manifest_rows: list[dict[str, object]] = []
    for split, split_items_list in splits.items():
        for item in split_items_list:
            image_rel, label_rel = copy_item(item, output, split)
            manifest_rows.append(
                {
                    "split": split,
                    "image": image_rel,
                    "label": label_rel,
                    "source_archive_image": item.row.get("new_image", ""),
                    "source_archive_label": item.row.get("new_label", ""),
                    "source_batch_id": item.row.get("batch_id", ""),
                    "source_original_image": item.row.get("original_image", ""),
                    "source_video": item.row.get("source_video", ""),
                    "video_id": item.row.get("video_id", ""),
                    "classes": " ".join(str(cls) for cls in item.classes),
                    "class_names": " ".join(CLASS_NAMES[cls] for cls in item.classes),
                }
            )

    data_yaml = output / "data.yaml"
    data_yaml.write_text(
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
    write_csv(output / "meta" / "manifest.csv", manifest_rows)
    write_csv(output / "meta" / "skipped.csv", skipped)
    write_csv(output / "meta" / "excluded_by_relabel_audit.csv", exclusion_rows)
    split_counts = {split: count_split(output, split) for split in ["train", "val", "test"]}
    summary = {
        "source": str(source),
        "output": str(output),
        "seed": args.seed,
        "include_empty": args.include_empty,
        "offline_augmentation_used": False,
        "item_count": len(items),
        "skipped_count": len(skipped),
        "excluded_by_relabel_audit_rows": len(exclusion_rows),
        "split_counts": split_counts,
        "guardrails": [
            "Only reviewed archive images/labels are copied.",
            "No files are read from or copied from the augmented-only dataset.",
            "Unresolved relabel audit conflicts are excluded.",
            "Empty labels are excluded by default to match the previous best training flow.",
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
