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
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"

CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class ReviewedItem:
    batch_id: str
    image_name: str
    image_path: Path
    label_path: Path
    video_id: str
    scene: str
    group: str

    @property
    def split_group(self) -> str:
        return f"{self.batch_id}::{self.video_id}"

    @property
    def output_stem(self) -> str:
        digest = hashlib.sha1(f"{self.batch_id}/{self.image_name}".encode("utf-8")).hexdigest()[:8]
        return f"{self.batch_id}_{Path(self.image_name).stem}_{digest}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a YOLO fall_hint_v2 incremental dataset from selected reviewed batches."
    )
    parser.add_argument("--start-batch", type=int, default=13)
    parser.add_argument("--end-batch", type=int, default=19)
    parser.add_argument(
        "--output",
        default=str(ROOT / "datasets" / "fall_hint_v2_incremental_b013_b019"),
    )
    parser.add_argument("--seed", type=int, default=20260701)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--include-empty", action="store_true")
    parser.add_argument("--skip-invalid", action="store_true")
    args = parser.parse_args()

    dataset = Path(args.output)
    if not dataset.is_absolute():
        dataset = ROOT / dataset
    batch_ids = [f"batch_{index:03d}" for index in range(args.start_batch, args.end_batch + 1)]
    items, skipped = collect_reviewed_items(
        batch_ids=batch_ids,
        include_empty=args.include_empty,
        skip_invalid=args.skip_invalid,
    )
    if not items:
        raise SystemExit("No reviewed labels found for selected batches.")

    split_by_group = assign_splits(
        items,
        seed=args.seed,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )
    reset_dataset_dirs(dataset)
    write_data_yaml(dataset / "data.yaml", dataset)

    rows: list[dict[str, str]] = []
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    batch_counts: Counter[str] = Counter()
    for item in items:
        split = split_by_group[item.split_group]
        out_image = dataset / "images" / split / f"{item.output_stem}{item.image_path.suffix.lower()}"
        out_label = dataset / "labels" / split / f"{item.output_stem}.txt"
        shutil.copy2(item.image_path, out_image)
        shutil.copy2(item.label_path, out_label)

        class_counts = count_label_classes(item.label_path)
        stats[split]["images"] += 1
        if not class_counts:
            stats[split]["empty"] += 1
        for class_id, count in class_counts.items():
            stats[split][CLASS_NAMES[class_id]] += count
            stats[split]["boxes"] += count
        batch_counts[item.batch_id] += 1

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
                "split_group": item.split_group,
                "class_counts": json.dumps(
                    {CLASS_NAMES[class_id]: count for class_id, count in sorted(class_counts.items())},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )

    write_csv(dataset / "meta" / "manifest.csv", rows)
    summary = {
        "dataset": str(dataset),
        "data_yaml": str(dataset / "data.yaml"),
        "source_batches": batch_ids,
        "item_count": len(items),
        "split_group_count": len(split_by_group),
        "include_empty": args.include_empty,
        "skip_invalid": args.skip_invalid,
        "skipped": skipped,
        "batch_counts": dict(batch_counts),
        "class_names": CLASS_NAMES,
        "splits": {split: dict(counter) for split, counter in stats.items()},
        "warnings": build_warnings(stats),
        "guardrail": "Only selected batches with human_review/meta status=reviewed are included.",
    }
    (dataset / "meta" / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def collect_reviewed_items(
    *,
    batch_ids: list[str],
    include_empty: bool,
    skip_invalid: bool,
) -> tuple[list[ReviewedItem], list[dict[str, str]]]:
    items: list[ReviewedItem] = []
    skipped: list[dict[str, str]] = []
    for batch_id in batch_ids:
        batch_dir = RAW_ROOT / batch_id
        frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        meta_dir = batch_dir / "human_review" / "meta"
        if not frames_dir.exists() or not labels_dir.exists() or not meta_dir.exists():
            continue
        for meta_path in sorted(meta_dir.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if meta.get("status") != "reviewed":
                continue
            image_name = str(meta.get("image") or f"{meta_path.stem}.jpg")
            image_path = frames_dir / image_name
            if not image_path.exists() or image_path.suffix.lower() not in IMAGE_EXTS:
                continue
            label_path = labels_dir / f"{Path(image_name).stem}.txt"
            if not label_path.exists():
                continue
            if not include_empty and label_path.read_text(encoding="utf-8").strip() == "":
                continue
            try:
                validate_label_file(label_path)
            except ValueError as exc:
                if not skip_invalid:
                    raise
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": image_name,
                        "label_path": str(label_path),
                        "reason": str(exc),
                    }
                )
                continue
            frame_row = frame_manifest.get(image_name, {})
            items.append(
                ReviewedItem(
                    batch_id=batch_id,
                    image_name=image_name,
                    image_path=image_path,
                    label_path=label_path,
                    video_id=frame_row.get("video_id") or Path(image_name).stem,
                    scene=frame_row.get("scene") or "",
                    group=frame_row.get("group") or "",
                )
            )
    return items, skipped


def assign_splits(
    items: list[ReviewedItem],
    *,
    seed: int,
    train_ratio: float,
    val_ratio: float,
) -> dict[str, str]:
    by_group: dict[str, list[ReviewedItem]] = defaultdict(list)
    for item in items:
        by_group[item.split_group].append(item)

    groups = list(by_group)
    random.Random(seed).shuffle(groups)

    total = sum(len(values) for values in by_group.values())
    train_target = total * train_ratio
    val_target = total * val_ratio
    counts = Counter()
    split_by_group: dict[str, str] = {}
    for group in groups:
        group_size = len(by_group[group])
        if counts["train"] < train_target:
            split = "train"
        elif counts["val"] < val_target:
            split = "val"
        else:
            split = "test"
        split_by_group[group] = split
        counts[split] += group_size
    return split_by_group


def reset_dataset_dirs(dataset: Path) -> None:
    for subdir in [
        dataset / "images" / "train",
        dataset / "images" / "val",
        dataset / "images" / "test",
        dataset / "labels" / "train",
        dataset / "labels" / "val",
        dataset / "labels" / "test",
        dataset / "meta",
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
        if class_id not in CLASS_NAMES:
            raise ValueError(f"{path}:{line_index}: bad class id {class_id}")
        x_center, y_center, width, height = map(float, parts[1:])
        if not (0 <= x_center <= 1 and 0 <= y_center <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError(f"{path}:{line_index}: bad bbox values {line}")


def count_label_classes(path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            counts[int(float(line.split()[0]))] += 1
    return counts


def write_data_yaml(path: Path, dataset: Path) -> None:
    names = "\n".join(f"  {index}: {name}" for index, name in CLASS_NAMES.items())
    path.write_text(
        "\n".join(
            [
                f"path: {dataset.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                names,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_warnings(stats: dict[str, Counter[str]]) -> list[str]:
    totals = Counter()
    for counter in stats.values():
        totals.update({key: value for key, value in counter.items() if key in CLASS_NAMES.values()})
    warnings = []
    for class_name in CLASS_NAMES.values():
        if totals[class_name] < 30:
            warnings.append(f"low sample count for {class_name}: {totals[class_name]}")
    if totals["standing"] > max(1, totals["falling"] + totals["fallen"] + totals["lying"]):
        warnings.append("standing remains dominant; consider class balancing during training")
    return warnings


if __name__ == "__main__":
    raise SystemExit(main())
