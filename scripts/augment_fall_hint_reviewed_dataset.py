from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_augmented_only_b001_b029"

CLASS_NAMES = {
    0: "falling",
    1: "fallen",
    2: "lying",
    3: "sitting",
    4: "bending",
    5: "kneeling",
    6: "standing",
}
PRIORITY_CLASSES = {0, 1, 2, 4, 5}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


@dataclass(frozen=True)
class YoloBox:
    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float


@dataclass(frozen=True)
class SourceSample:
    manifest_index: str
    image_path: Path
    label_path: Path
    batch_id: str
    original_image: str
    boxes: list[YoloBox]
    manifest_row: dict[str, str]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a bbox-aware augmented-only Fall Hint dataset from reviewed samples."
    )
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--seed", type=int, default=20260702)
    parser.add_argument("--max-aug-per-image", type=int, default=2)
    parser.add_argument("--standing-ratio", type=float, default=0.25)
    parser.add_argument("--empty-ratio", type=float, default=0.25)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source = resolve_path(args.source)
    output = resolve_path(args.output)
    if not source.exists():
        raise SystemExit(f"Source dataset does not exist: {source}")
    prepare_output(output, overwrite=args.overwrite)

    rng = random.Random(args.seed)
    samples, load_skipped = load_source_samples(source)
    rows, run_skipped = augment_samples(
        samples,
        source=source,
        output=output,
        rng=rng,
        max_aug_per_image=max(args.max_aug_per_image, 0),
        standing_ratio=clamp(args.standing_ratio, 0.0, 1.0),
        empty_ratio=clamp(args.empty_ratio, 0.0, 1.0),
    )
    skipped = load_skipped + run_skipped

    copy_classes(source, output)
    write_csv(output / "meta" / "augment_manifest.csv", rows)
    write_csv(output / "meta" / "skipped.csv", skipped)
    summary = validate_augmented_dataset(output, rows, skipped, args=args, source=source)
    (output / "meta" / "augment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "README.md").write_text(build_readme(source, output, summary), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


def prepare_output(output: Path, *, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"{output} already exists; pass --overwrite only when intentionally rebuilding")
        shutil.rmtree(output)
    for subdir in ["images", "labels", "meta"]:
        (output / subdir).mkdir(parents=True, exist_ok=True)


def load_source_samples(source: Path) -> tuple[list[SourceSample], list[dict[str, str]]]:
    manifest_path = source / "meta" / "manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"Missing source manifest: {manifest_path}")

    samples: list[SourceSample] = []
    skipped: list[dict[str, str]] = []
    with manifest_path.open("r", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            manifest_index = row.get("index") or row.get("new_stem") or ""
            image_rel = row.get("new_image", "")
            label_rel = row.get("new_label", "")
            image_path = source / image_rel
            label_path = source / label_rel
            if image_path.suffix.lower() not in IMAGE_EXTS or not image_path.exists():
                skipped.append(skip_row(row, "missing_or_unsupported_source_image", str(image_path)))
                continue
            if not label_path.exists():
                skipped.append(skip_row(row, "missing_source_label", str(label_path)))
                continue
            try:
                boxes = read_yolo_label(label_path)
            except ValueError as exc:
                skipped.append(skip_row(row, f"invalid_source_label: {exc}", str(label_path)))
                continue
            samples.append(
                SourceSample(
                    manifest_index=manifest_index,
                    image_path=image_path,
                    label_path=label_path,
                    batch_id=row.get("batch_id", ""),
                    original_image=row.get("original_image", ""),
                    boxes=boxes,
                    manifest_row=row,
                )
            )
    return samples, skipped


def augment_samples(
    samples: list[SourceSample],
    *,
    source: Path,
    output: Path,
    rng: random.Random,
    max_aug_per_image: int,
    standing_ratio: float,
    empty_ratio: float,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    next_index = 1

    for sample in samples:
        plan = choose_plan(sample, rng, max_aug_per_image, standing_ratio, empty_ratio)
        if not plan:
            continue

        image = read_image(sample.image_path)
        if image is None:
            skipped.append(skip_sample(sample, "source_image_decode_failed", str(sample.image_path)))
            continue

        for aug_name in plan:
            params = make_params(aug_name, rng)
            try:
                aug_image, aug_boxes = apply_augmentation(image, sample.boxes, aug_name, params)
            except ValueError as exc:
                skipped.append(skip_sample(sample, f"augmentation_failed: {exc}", aug_name))
                continue

            if sample.boxes and not aug_boxes:
                skipped.append(skip_sample(sample, "all_boxes_lost_after_augmentation", aug_name))
                continue

            new_stem = f"fhv2_aug_{next_index:06d}"
            image_ext = sample.image_path.suffix.lower()
            if image_ext not in IMAGE_EXTS:
                image_ext = ".jpg"
            out_image = output / "images" / f"{new_stem}{image_ext}"
            out_label = output / "labels" / f"{new_stem}.txt"
            write_image(out_image, aug_image)
            write_yolo_label(out_label, aug_boxes)

            source_classes = sorted({box.class_id for box in sample.boxes})
            rows.append(
                {
                    "augmented_index": f"{next_index:06d}",
                    "augmented_image": str(out_image.relative_to(output)).replace("\\", "/"),
                    "augmented_label": str(out_label.relative_to(output)).replace("\\", "/"),
                    "source_image": str(sample.image_path.relative_to(source)).replace("\\", "/"),
                    "source_label": str(sample.label_path.relative_to(source)).replace("\\", "/"),
                    "source_manifest_index": sample.manifest_index,
                    "source_batch_id": sample.batch_id,
                    "source_original_image": sample.original_image,
                    "source_classes": json.dumps(source_classes, ensure_ascii=False),
                    "augmentation_name": aug_name,
                    "augmentation_params": json.dumps(params, ensure_ascii=False, sort_keys=True),
                    "box_count_before": str(len(sample.boxes)),
                    "box_count_after": str(len(aug_boxes)),
                    "source_new_stem": sample.manifest_row.get("new_stem", ""),
                    "source_box_count": sample.manifest_row.get("box_count", ""),
                    "source_is_empty_label": sample.manifest_row.get("is_empty_label", ""),
                }
            )
            next_index += 1

    return rows, skipped


def choose_plan(
    sample: SourceSample,
    rng: random.Random,
    max_aug_per_image: int,
    standing_ratio: float,
    empty_ratio: float,
) -> list[str]:
    if max_aug_per_image <= 0:
        return []

    classes = {box.class_id for box in sample.boxes}
    if not classes:
        if rng.random() >= empty_ratio:
            return []
        return ["empty_photo"][:max_aug_per_image]

    if classes & PRIORITY_CLASSES:
        candidates = ["affine_photo", "flip_photo"]
        return candidates[: min(max_aug_per_image, 2)]

    if classes == {3}:
        return ["mild_photo"][: min(max_aug_per_image, 1)]

    if classes == {6}:
        if rng.random() >= standing_ratio:
            return []
        return ["mild_photo"][: min(max_aug_per_image, 1)]

    return ["mild_photo"][: min(max_aug_per_image, 1)]


def make_params(aug_name: str, rng: random.Random) -> dict[str, Any]:
    params: dict[str, Any] = {
        "brightness": round(rng.uniform(-22, 22), 3),
        "contrast": round(rng.uniform(0.88, 1.14), 4),
        "saturation": round(rng.uniform(0.92, 1.10), 4),
        "hue_shift": round(rng.uniform(-4, 4), 3),
        "noise_std": round(rng.choice([0.0, rng.uniform(2.0, 7.0)]), 3),
        "blur": rng.choice(["none", "gaussian", "motion"]),
        "blur_kernel": rng.choice([3, 3, 5]),
        "jpeg_quality": rng.randint(60, 92),
    }
    if aug_name == "flip_photo":
        params["horizontal_flip"] = True
    if aug_name == "affine_photo":
        params.update(
            {
                "angle": round(rng.uniform(-5.0, 5.0), 3),
                "scale": round(rng.uniform(0.92, 1.08), 4),
                "shift_x": round(rng.uniform(-0.04, 0.04), 4),
                "shift_y": round(rng.uniform(-0.04, 0.04), 4),
            }
        )
    return params


def apply_augmentation(
    image: np.ndarray,
    boxes: list[YoloBox],
    aug_name: str,
    params: dict[str, Any],
) -> tuple[np.ndarray, list[YoloBox]]:
    aug_image = image.copy()
    aug_boxes = list(boxes)
    height, width = image.shape[:2]

    if aug_name == "flip_photo" and params.get("horizontal_flip"):
        aug_image = cv2.flip(aug_image, 1)
        aug_boxes = [
            YoloBox(
                class_id=box.class_id,
                x_center=1.0 - box.x_center,
                y_center=box.y_center,
                width=box.width,
                height=box.height,
            )
            for box in aug_boxes
        ]

    if aug_name == "affine_photo":
        aug_image, aug_boxes = apply_affine(
            aug_image,
            aug_boxes,
            angle=float(params["angle"]),
            scale=float(params["scale"]),
            shift_x=float(params["shift_x"]),
            shift_y=float(params["shift_y"]),
        )

    aug_image = apply_photometric(aug_image, params)
    if aug_image.shape[:2] != (height, width):
        raise ValueError("augmentation changed image size unexpectedly")
    validate_boxes(aug_boxes)
    return aug_image, aug_boxes


def apply_affine(
    image: np.ndarray,
    boxes: list[YoloBox],
    *,
    angle: float,
    scale: float,
    shift_x: float,
    shift_y: float,
) -> tuple[np.ndarray, list[YoloBox]]:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, scale)
    matrix[0, 2] += shift_x * width
    matrix[1, 2] += shift_y * height
    border_value = tuple(float(v) for v in np.median(image.reshape(-1, image.shape[2]), axis=0))
    warped = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border_value,
    )
    transformed_boxes = transform_boxes_affine(boxes, matrix, width, height)
    return warped, transformed_boxes


def transform_boxes_affine(
    boxes: list[YoloBox],
    matrix: np.ndarray,
    width: int,
    height: int,
) -> list[YoloBox]:
    transformed: list[YoloBox] = []
    min_size_px = 2.0
    min_area_ratio = 0.08
    for box in boxes:
        x1 = (box.x_center - box.width / 2.0) * width
        y1 = (box.y_center - box.height / 2.0) * height
        x2 = (box.x_center + box.width / 2.0) * width
        y2 = (box.y_center + box.height / 2.0) * height
        corners = np.array(
            [
                [x1, y1, 1.0],
                [x2, y1, 1.0],
                [x2, y2, 1.0],
                [x1, y2, 1.0],
            ],
            dtype=np.float32,
        )
        mapped = corners @ matrix.T
        nx1 = float(np.clip(mapped[:, 0].min(), 0, width))
        ny1 = float(np.clip(mapped[:, 1].min(), 0, height))
        nx2 = float(np.clip(mapped[:, 0].max(), 0, width))
        ny2 = float(np.clip(mapped[:, 1].max(), 0, height))
        new_w = nx2 - nx1
        new_h = ny2 - ny1
        old_area = max((x2 - x1) * (y2 - y1), 1.0)
        new_area = new_w * new_h
        if new_w < min_size_px or new_h < min_size_px or new_area / old_area < min_area_ratio:
            continue
        transformed.append(
            YoloBox(
                class_id=box.class_id,
                x_center=((nx1 + nx2) / 2.0) / width,
                y_center=((ny1 + ny2) / 2.0) / height,
                width=new_w / width,
                height=new_h / height,
            )
        )
    return transformed


def apply_photometric(image: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    out = image.astype(np.float32)
    out = out * float(params.get("contrast", 1.0)) + float(params.get("brightness", 0.0))
    out = np.clip(out, 0, 255).astype(np.uint8)

    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 0] = (hsv[:, :, 0] + float(params.get("hue_shift", 0.0))) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * float(params.get("saturation", 1.0)), 0, 255)
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    noise_std = float(params.get("noise_std", 0.0))
    if noise_std > 0:
        noise = np.random.default_rng(int(noise_std * 1000 + out.shape[0] + out.shape[1])).normal(
            0,
            noise_std,
            out.shape,
        )
        out = np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    blur = str(params.get("blur", "none"))
    kernel = int(params.get("blur_kernel", 3))
    kernel = kernel if kernel % 2 == 1 else kernel + 1
    if blur == "gaussian":
        out = cv2.GaussianBlur(out, (kernel, kernel), 0)
    elif blur == "motion":
        motion_kernel = np.zeros((kernel, kernel), dtype=np.float32)
        motion_kernel[kernel // 2, :] = 1.0 / kernel
        out = cv2.filter2D(out, -1, motion_kernel)

    quality = int(params.get("jpeg_quality", 85))
    ok, encoded = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if ok:
        decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if decoded is not None:
            out = decoded
    return out


def read_yolo_label(path: Path) -> list[YoloBox]:
    boxes: list[YoloBox] = []
    for line_index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"{path}:{line_index}: expected 5 columns")
        class_id = int(float(parts[0]))
        x_center, y_center, width, height = map(float, parts[1:])
        box = YoloBox(class_id, x_center, y_center, width, height)
        validate_boxes([box])
        boxes.append(box)
    return boxes


def write_yolo_label(path: Path, boxes: list[YoloBox]) -> None:
    lines = [
        f"{box.class_id} {box.x_center:.6f} {box.y_center:.6f} {box.width:.6f} {box.height:.6f}"
        for box in boxes
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def validate_boxes(boxes: list[YoloBox]) -> None:
    for box in boxes:
        if box.class_id not in CLASS_NAMES:
            raise ValueError(f"bad class id {box.class_id}")
        values = [box.x_center, box.y_center, box.width, box.height]
        if any(math.isnan(value) or math.isinf(value) for value in values):
            raise ValueError("bbox contains NaN/Inf")
        if not (0 <= box.x_center <= 1 and 0 <= box.y_center <= 1 and 0 < box.width <= 1 and 0 < box.height <= 1):
            raise ValueError(f"bad bbox values {box}")


def validate_augmented_dataset(
    output: Path,
    rows: list[dict[str, str]],
    skipped: list[dict[str, str]],
    *,
    args: argparse.Namespace,
    source: Path,
) -> dict[str, Any]:
    images = sorted(path for path in (output / "images").glob("*") if path.suffix.lower() in IMAGE_EXTS)
    labels = sorted((output / "labels").glob("*.txt"))
    errors: list[str] = []
    if len(images) != len(labels):
        errors.append(f"image_label_count_mismatch: {len(images)} != {len(labels)}")
    if len(images) != len(rows):
        errors.append(f"image_manifest_count_mismatch: {len(images)} != {len(rows)}")

    image_stems = [path.stem for path in images]
    label_stems = [path.stem for path in labels]
    if image_stems != label_stems:
        errors.append("image_label_stem_order_mismatch")

    class_counts: Counter[str] = Counter()
    empty_count = 0
    for image_path in images:
        label_path = output / "labels" / f"{image_path.stem}.txt"
        if not label_path.exists():
            errors.append(f"missing_label_for_image: {image_path.name}")
            continue
        try:
            boxes = read_yolo_label(label_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not boxes:
            empty_count += 1
        for box in boxes:
            class_counts[CLASS_NAMES[box.class_id]] += 1

    skipped_reasons = Counter(row.get("reason", "unknown") for row in skipped)
    summary = {
        "source": str(source),
        "output": str(output),
        "seed": args.seed,
        "max_aug_per_image": args.max_aug_per_image,
        "standing_ratio": args.standing_ratio,
        "empty_ratio": args.empty_ratio,
        "augmented_images": len(images),
        "augmented_labels": len(labels),
        "manifest_rows": len(rows),
        "empty_label_augmented": empty_count,
        "class_box_counts": dict(sorted(class_counts.items())),
        "skipped_count": len(skipped),
        "skipped_reasons": dict(sorted(skipped_reasons.items())),
        "validation_error_count": len(errors),
        "validation_errors": errors[:50],
        "guardrail": "Augmented files are stored separately; source reviewed dataset is not modified.",
    }
    if errors:
        raise SystemExit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def read_image(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write_image(path: Path, image: np.ndarray) -> None:
    ext = path.suffix.lower() or ".jpg"
    encode_ext = ".jpg" if ext in {".jpg", ".jpeg"} else ext
    params = [int(cv2.IMWRITE_JPEG_QUALITY), 92] if encode_ext == ".jpg" else []
    ok, encoded = cv2.imencode(encode_ext, image, params)
    if not ok:
        raise ValueError(f"failed to encode image: {path}")
    encoded.tofile(str(path))


def copy_classes(source: Path, output: Path) -> None:
    source_classes = source / "classes.txt"
    if source_classes.exists():
        shutil.copy2(source_classes, output / "classes.txt")
    else:
        (output / "classes.txt").write_text(
            "\n".join(CLASS_NAMES[index] for index in sorted(CLASS_NAMES)) + "\n",
            encoding="utf-8",
        )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        if not fieldnames:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_readme(source: Path, output: Path, summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# fall_hint_v2 Augmented Only Dataset",
            "",
            "This directory contains augmented copies only. It intentionally does not contain the original reviewed images.",
            "",
            f"Source reviewed dataset: `{source}`",
            f"Augmented-only dataset: `{output}`",
            "",
            "Files:",
            "",
            "- `images/`: augmented images.",
            "- `labels/`: YOLO labels transformed together with the augmented images.",
            "- `meta/augment_manifest.csv`: mapping from each augmented file back to its source reviewed sample.",
            "- `meta/skipped.csv`: skipped samples or failed augmentation attempts.",
            "- `meta/augment_summary.json`: generation and validation summary.",
            "- `classes.txt`: YOLO class order.",
            "",
            f"Augmented images: `{summary['augmented_images']}`",
            f"Augmented labels: `{summary['augmented_labels']}`",
            f"Validation errors: `{summary['validation_error_count']}`",
            "",
            "Use this directory only as a training supplement. Validation and test splits should be built from original reviewed data only.",
            "",
        ]
    )


def skip_row(row: dict[str, str], reason: str, path: str) -> dict[str, str]:
    return {
        "source_manifest_index": row.get("index", ""),
        "source_image": row.get("new_image", ""),
        "source_label": row.get("new_label", ""),
        "source_batch_id": row.get("batch_id", ""),
        "reason": reason,
        "path": path,
    }


def skip_sample(sample: SourceSample, reason: str, path: str) -> dict[str, str]:
    return {
        "source_manifest_index": sample.manifest_index,
        "source_image": str(sample.image_path),
        "source_label": str(sample.label_path),
        "source_batch_id": sample.batch_id,
        "reason": reason,
        "path": path,
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


if __name__ == "__main__":
    raise SystemExit(main())
