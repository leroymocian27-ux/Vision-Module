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
RAW_ROOT = ROOT / "datasets" / "person_yolo_raw"
DATASET = ROOT / "datasets" / "person_yolo"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = {0: "person"}


@dataclass(frozen=True)
class ReviewedItem:
    batch_id: str
    image_name: str
    image_path: Path
    label_path: Path
    video_id: str
    scene: str
    group: str
    source_dataset: str

    @property
    def output_stem(self) -> str:
        digest = hashlib.sha1(f"{self.batch_id}/{self.image_name}".encode("utf-8")).hexdigest()[:8]
        return f"{self.batch_id}_{Path(self.image_name).stem}_{digest}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a single-class YOLO person dataset from reviewed batches.")
    parser.add_argument("--seed", type=int, default=20260629)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    args = parser.parse_args()

    items = collect_reviewed_items()
    if not items:
        raise SystemExit("No reviewed person labels found.")

    split_by_item = assign_scene_stratified_splits(
        items,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )
    reset_dataset_dirs()
    write_data_yaml(DATASET / "data.yaml")

    rows: list[dict[str, str]] = []
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    group_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        split = split_by_item[item.output_stem]
        out_image = DATASET / "images" / split / f"{item.output_stem}{item.image_path.suffix.lower()}"
        out_label = DATASET / "labels" / split / f"{item.output_stem}.txt"
        shutil.copy2(item.image_path, out_image)
        shutil.copy2(item.label_path, out_label)

        box_count = count_boxes(item.label_path)
        stats[split]["images"] += 1
        stats[split]["boxes"] += box_count
        if box_count == 0:
            stats[split]["empty"] += 1
        group_stats[item.group][split] += 1
        group_stats[item.group]["images"] += 1
        group_stats[item.group]["boxes"] += box_count
        if box_count == 0:
            group_stats[item.group]["empty"] += 1

        rows.append(
            {
                "split": split,
                "batch_id": item.batch_id,
                "image": item.image_name,
                "output_image": str(out_image.relative_to(ROOT)).replace("\\", "/"),
                "output_label": str(out_label.relative_to(ROOT)).replace("\\", "/"),
                "video_id": item.video_id,
                "scene": item.scene,
                "group": item.group,
                "source_dataset": item.source_dataset,
                "boxes": str(box_count),
            }
        )

    write_csv(DATASET / "meta" / "manifest.csv", rows)
    summary = {
        "item_count": len(items),
        "class_names": CLASS_NAMES,
        "splits": {split: dict(counter) for split, counter in sorted(stats.items())},
        "groups": {group: dict(counter) for group, counter in sorted(group_stats.items())},
        "warnings": build_warnings(stats, group_stats),
    }
    (DATASET / "meta" / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def collect_reviewed_items() -> list[ReviewedItem]:
    items: list[ReviewedItem] = []
    for batch_dir in sorted(RAW_ROOT.glob("batch_*")):
        frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        meta_dir = batch_dir / "human_review" / "meta"
        if not frames_dir.exists() or not labels_dir.exists() or not meta_dir.exists():
            continue
        for meta_path in sorted(meta_dir.glob("*.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("status") != "reviewed":
                continue
            image_name = str(meta.get("image") or f"{meta_path.stem}.jpg")
            image_path = frames_dir / image_name
            label_path = labels_dir / f"{Path(image_name).stem}.txt"
            if not image_path.exists() or image_path.suffix.lower() not in IMAGE_EXTS:
                continue
            if not label_path.exists():
                continue
            validate_label_file(label_path)
            frame_row = frame_manifest.get(image_name, {})
            items.append(
                ReviewedItem(
                    batch_id=batch_dir.name,
                    image_name=image_name,
                    image_path=image_path,
                    label_path=label_path,
                    video_id=frame_row.get("video_id") or Path(image_name).stem,
                    scene=frame_row.get("scene") or "",
                    group=frame_row.get("group") or "",
                    source_dataset=frame_row.get("source_dataset") or "",
                )
            )
    return items


def assign_scene_stratified_splits(
    items: list[ReviewedItem],
    *,
    seed: int,
    train_ratio: float,
    val_ratio: float,
) -> dict[str, str]:
    by_group: dict[str, list[ReviewedItem]] = defaultdict(list)
    for item in items:
        by_group[item.group or "unknown"].append(item)

    rng = random.Random(seed)
    split_by_item: dict[str, str] = {}
    for group_items in by_group.values():
        shuffled = list(group_items)
        rng.shuffle(shuffled)
        total = len(shuffled)
        train_count = max(1, round(total * train_ratio))
        val_count = max(1, round(total * val_ratio)) if total >= 3 else 0
        if train_count + val_count >= total and total >= 3:
            train_count = total - val_count - 1
        for index, item in enumerate(shuffled):
            if index < train_count:
                split = "train"
            elif index < train_count + val_count:
                split = "val"
            else:
                split = "test"
            split_by_item[item.output_stem] = split
    return split_by_item


def reset_dataset_dirs() -> None:
    for subdir in [
        DATASET / "images" / "train",
        DATASET / "images" / "val",
        DATASET / "images" / "test",
        DATASET / "labels" / "train",
        DATASET / "labels" / "val",
        DATASET / "labels" / "test",
        DATASET / "meta",
    ]:
        if subdir.exists():
            shutil.rmtree(subdir)
        subdir.mkdir(parents=True, exist_ok=True)


def read_frame_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def validate_label_file(path: Path) -> None:
    for line_index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path}:{line_index}: expected 5 YOLO columns")
        class_id = int(float(parts[0]))
        if class_id != 0:
            raise ValueError(f"{path}:{line_index}: person dataset only allows class id 0")
        x_center, y_center, width, height = map(float, parts[1:])
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError(f"{path}:{line_index}: bad bbox values {line}")


def count_boxes(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def write_data_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"path: {DATASET.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                "  0: person",
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_warnings(stats: dict[str, Counter[str]], group_stats: dict[str, Counter[str]]) -> list[str]:
    warnings = []
    for split in ("train", "val", "test"):
        if stats[split]["images"] == 0:
            warnings.append(f"{split} split has no images")
        if stats[split]["boxes"] == 0:
            warnings.append(f"{split} split has no person boxes")
    for group, counter in group_stats.items():
        if counter["images"] < 10:
            warnings.append(f"low image count for group {group}: {counter['images']}")
    return warnings


if __name__ == "__main__":
    raise SystemExit(main())
