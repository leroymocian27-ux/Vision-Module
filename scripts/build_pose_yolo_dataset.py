from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "pose_yolo_raw"
DATASET = ROOT / "datasets" / "pose_yolo"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
CLASS_NAMES = {0: "person"}
KEYPOINT_COUNT = 17


@dataclass(frozen=True)
class PoseItem:
    batch_id: str
    image_name: str
    image_path: Path
    annotation: dict
    annotation_index: int
    group: str
    scene: str
    source_dataset: str

    @property
    def stem(self) -> str:
        source = f"{self.batch_id}_{Path(self.image_name).stem}_p{self.annotation_index:02d}"
        return source.replace(" ", "_")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build YOLO pose dataset from human-reviewed COCO-17 labels.")
    parser.add_argument("--seed", type=int, default=20260630)
    parser.add_argument("--train-ratio", type=float, default=0.80)
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--min-visible-keypoints", type=int, default=6)
    args = parser.parse_args()

    items, skipped = collect_items(min_visible_keypoints=args.min_visible_keypoints)
    if not items:
        raise SystemExit("No usable reviewed pose labels found.")

    split_by_stem = assign_splits(items, args.seed, args.train_ratio, args.val_ratio)
    reset_dataset_dirs()
    write_data_yaml(DATASET / "data.yaml")

    rows: list[dict[str, str]] = []
    stats: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        split = split_by_stem[item.stem]
        out_image = DATASET / "images" / split / f"{item.stem}{item.image_path.suffix.lower()}"
        out_label = DATASET / "labels" / split / f"{item.stem}.txt"
        shutil.copy2(item.image_path, out_image)
        out_label.write_text(to_yolo_pose_line(item.annotation), encoding="utf-8")

        visible = visible_keypoint_count(item.annotation)
        stats[split]["images"] += 1
        stats[split]["persons"] += 1
        stats[split]["visible_keypoints"] += visible
        stats[item.group or "unknown"]["persons"] += 1

        rows.append(
            {
                "split": split,
                "batch_id": item.batch_id,
                "image": item.image_name,
                "output_image": str(out_image.relative_to(ROOT)).replace("\\", "/"),
                "output_label": str(out_label.relative_to(ROOT)).replace("\\", "/"),
                "annotation_index": str(item.annotation_index),
                "group": item.group,
                "scene": item.scene,
                "source_dataset": item.source_dataset,
                "visible_keypoints": str(visible),
            }
        )

    write_csv(DATASET / "meta" / "manifest.csv", rows)
    summary = {
        "item_count": len(items),
        "class_names": CLASS_NAMES,
        "keypoint_count": KEYPOINT_COUNT,
        "min_visible_keypoints": args.min_visible_keypoints,
        "splits": {split: dict(counter) for split, counter in sorted(stats.items()) if split in {"train", "val", "test"}},
        "groups": {group: dict(counter) for group, counter in sorted(stats.items()) if group not in {"train", "val", "test"}},
        "skipped": dict(skipped),
        "warnings": build_warnings(stats),
    }
    (DATASET / "meta" / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def collect_items(*, min_visible_keypoints: int) -> tuple[list[PoseItem], Counter[str]]:
    items: list[PoseItem] = []
    skipped: Counter[str] = Counter()
    for batch_dir in sorted(RAW_ROOT.glob("batch_*")):
        frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        if not frames_dir.exists() or not labels_dir.exists():
            continue
        for label_path in sorted(labels_dir.glob("*.json")):
            payload = json.loads(label_path.read_text(encoding="utf-8"))
            if payload.get("status") != "reviewed":
                skipped["not_reviewed"] += 1
                continue
            image_name = str(payload.get("image") or f"{label_path.stem}.jpg")
            image_path = frames_dir / image_name
            if not image_path.exists() or image_path.suffix.lower() not in IMAGE_EXTS:
                skipped["missing_image"] += 1
                continue
            row = frame_manifest.get(image_name, {})
            for index, annotation in enumerate(payload.get("annotations", [])):
                validate_annotation(annotation)
                visible = visible_keypoint_count(annotation)
                if visible < min_visible_keypoints:
                    skipped["low_or_zero_visible_keypoints"] += 1
                    continue
                items.append(
                    PoseItem(
                        batch_id=batch_dir.name,
                        image_name=image_name,
                        image_path=image_path,
                        annotation=annotation,
                        annotation_index=index,
                        group=row.get("group") or "",
                        scene=row.get("scene") or "",
                        source_dataset=row.get("source_dataset") or "",
                    )
                )
    return items, skipped


def validate_annotation(annotation: dict) -> None:
    bbox = annotation.get("bbox") or {}
    for key in ("x", "y", "w", "h"):
        value = float(bbox.get(key, -1))
        if key in {"x", "y"} and not (0 <= value <= 1):
            raise ValueError(f"bad bbox {bbox}")
        if key in {"w", "h"} and not (0 < value <= 1):
            raise ValueError(f"bad bbox {bbox}")
    keypoints = annotation.get("keypoints") or []
    if len(keypoints) != KEYPOINT_COUNT:
        raise ValueError(f"expected {KEYPOINT_COUNT} keypoints, got {len(keypoints)}")
    for keypoint in keypoints:
        x = float(keypoint.get("x", 0))
        y = float(keypoint.get("y", 0))
        v = int(keypoint.get("v", 0))
        if v not in {0, 1, 2} or not (0 <= x <= 1) or not (0 <= y <= 1):
            raise ValueError(f"bad keypoint {keypoint}")


def to_yolo_pose_line(annotation: dict) -> str:
    bbox = annotation["bbox"]
    values = [0, bbox["x"], bbox["y"], bbox["w"], bbox["h"]]
    for keypoint in annotation["keypoints"]:
        values.extend([keypoint["x"], keypoint["y"], int(keypoint["v"])])
    return " ".join(str(round(float(value), 6)) if isinstance(value, float) else str(value) for value in values) + "\n"


def visible_keypoint_count(annotation: dict) -> int:
    return sum(1 for keypoint in annotation.get("keypoints", []) if int(keypoint.get("v", 0)) > 0)


def assign_splits(items: list[PoseItem], seed: int, train_ratio: float, val_ratio: float) -> dict[str, str]:
    rng = random.Random(seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    total = len(shuffled)
    train_count = round(total * train_ratio)
    val_count = round(total * val_ratio)
    split_by_stem = {}
    for index, item in enumerate(shuffled):
        if index < train_count:
            split = "train"
        elif index < train_count + val_count:
            split = "val"
        else:
            split = "test"
        split_by_stem[item.stem] = split
    return split_by_stem


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


def write_data_yaml(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                f"path: {DATASET.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "kpt_shape: [17, 3]",
                "flip_idx: [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]",
                "",
                "names:",
                "  0: person",
                "",
            ]
        ),
        encoding="utf-8",
    )


def read_frame_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_warnings(stats: dict[str, Counter[str]]) -> list[str]:
    warnings = []
    for split in ("train", "val", "test"):
        if stats[split]["persons"] == 0:
            warnings.append(f"{split} split has no persons")
    return warnings


if __name__ == "__main__":
    raise SystemExit(main())
