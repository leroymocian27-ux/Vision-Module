from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import cycle
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_ROOT = ROOT.parent / "_uploaded_binary_model_audit_20260810_01" / "dog" / "data_processed"
DEFAULT_OUTPUT_ROOT = ROOT / "demo_assets" / "data_augmentation"
DEFAULT_TARGET_TOTAL = 1000
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")
PREFERRED_CLASSES = ("Fall", "noFall")
MANIFEST_FIELDS = [
    "generated_image",
    "source_image",
    "class_name",
    "rotation_deg",
    "horizontal_flip",
    "brightness_factor",
    "contrast_factor",
    "blur",
    "noise",
    "seed",
    "created_at",
]


def main() -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(
        description="Offline Post-Fall V2 EfficientNet-B0 training data augmentation demo."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--target-total", type=int, default=DEFAULT_TARGET_TOTAL)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--augmented-long-side",
        type=int,
        default=640,
        help="Resize generated augmented images to this max side before augmentation; 0 keeps source resolution.",
    )
    parser.add_argument("--count-only", action="store_true", help="Only print current demo/source training counts.")
    parser.add_argument("--prepare-only", action="store_true", help="Create the demo split copy without augmentation.")
    parser.add_argument("--clean-generated", action="store_true", help="Delete only generated files listed in manifest.")
    parser.add_argument(
        "--clean-orphaned-generated",
        action="store_true",
        help="Also clean interrupted *_aug_*.jpg files in the demo train folder when no manifest entry exists.",
    )
    args = parser.parse_args()

    if args.target_total <= 0:
        parser.error("--target-total must be positive")

    paths = DemoPaths(args.output_root.resolve())
    print_header()

    if args.clean_generated:
        clean_generated(paths, allow_orphaned=args.clean_orphaned_generated)

    source_root = args.source_root.resolve()
    classes = detect_classes(source_root)

    if args.count_only:
        dataset_root = paths.dataset_root if paths.dataset_root.exists() else source_root
        print_counts(dataset_root, classes, args.target_total)
        return 0

    print("[1/4] Scanning training dataset...")
    source_snapshot = snapshot_split_hashes(source_root, classes, splits=("val", "test"))
    source_counts = count_training_images(source_root, classes)
    print_dataset_block(source_counts, args.target_total)

    prepare_demo_copy(source_root, paths.dataset_root, classes)
    demo_counts_before = count_training_images(paths.dataset_root, classes)
    if demo_counts_before["total"] < source_counts["total"]:
        raise RuntimeError("Demo copy is missing source training images.")

    if args.prepare_only:
        print("[INFO] Demo training copy prepared; no augmentation requested.")
        print_summary(
            before=demo_counts_before,
            added=Counter(),
            after=demo_counts_before,
            target_total=args.target_total,
            paths=paths,
            generated_now=0,
        )
        return 0

    existing_generated = read_manifest_rows(paths.manifest_path)
    current_counts = count_training_images(paths.dataset_root, classes)
    if current_counts["total"] >= args.target_total:
        print(f"[INFO] Dataset already contains {current_counts['total']} training images.")
        print("[INFO] No additional augmentation required.")
        verify_dataset(paths, source_root, classes, source_snapshot, existing_generated)
        write_report(paths, source_root, source_counts, Counter(), current_counts, classes, args.seed)
        print_summary(
            before=source_counts,
            added=Counter(),
            after=current_counts,
            target_total=args.target_total,
            paths=paths,
            generated_now=0,
        )
        return 0

    print("[2/4] Generating augmented images...")
    rng = random.Random(args.seed)
    plan = build_generation_plan(current_counts, args.target_total, classes)
    generated_rows = generate_augmented_images(
        paths.dataset_root,
        classes,
        plan,
        rng,
        args.seed,
        len(existing_generated),
        args.augmented_long_side,
    )

    print("[3/4] Verifying generated images...")
    all_rows = existing_generated + generated_rows
    verify_dataset(paths, source_root, classes, source_snapshot, all_rows)

    print("[4/4] Writing augmentation manifest...")
    write_manifest(paths.manifest_path, all_rows)
    make_preview(paths.dataset_root, paths.preview_root, classes, random.Random(args.seed + 2026))
    final_counts = count_training_images(paths.dataset_root, classes)
    added_counts = Counter(row["class_name"] for row in generated_rows)
    write_report(paths, source_root, source_counts, added_counts, final_counts, classes, args.seed)
    print_summary(
        before=source_counts,
        added=added_counts,
        after=final_counts,
        target_total=args.target_total,
        paths=paths,
        generated_now=len(generated_rows),
    )
    return 0


class DemoPaths:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.dataset_root = output_root / "demo_training_dataset"
        self.preview_root = output_root / "preview"
        self.manifest_path = output_root / "augmentation_manifest.csv"
        self.report_path = output_root / "augmentation_report.json"


def configure_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def print_header() -> None:
    print("============================================")
    print("Post-Fall V2 Training Data Augmentation Demo")
    print("EfficientNet-B0 FALL / NON_FALL")
    print("===============================")


def detect_classes(dataset_root: Path) -> list[str]:
    train_root = dataset_root / "train"
    if not train_root.is_dir():
        raise FileNotFoundError(f"Missing train split: {train_root}")
    available = {path.name for path in train_root.iterdir() if path.is_dir()}
    classes = [name for name in PREFERRED_CLASSES if name in available]
    if len(classes) == 2:
        return classes
    classes = sorted(available)
    if len(classes) < 2:
        raise FileNotFoundError(f"Expected at least two class folders under {train_root}")
    return classes


def iter_images(folder: Path) -> Iterable[Path]:
    if not folder.is_dir():
        return []
    return (
        path
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def is_generated(path: Path) -> bool:
    return "_aug_" in path.stem


def count_training_images(dataset_root: Path, classes: Iterable[str]) -> Counter:
    counts: Counter = Counter()
    for class_name in classes:
        class_count = sum(1 for _ in iter_images(dataset_root / "train" / class_name))
        counts[class_name] = class_count
        counts["total"] += class_count
    return counts


def count_generated_images(dataset_root: Path, classes: Iterable[str]) -> Counter:
    counts: Counter = Counter()
    for class_name in classes:
        class_count = sum(1 for path in iter_images(dataset_root / "train" / class_name) if is_generated(path))
        counts[class_name] = class_count
        counts["total"] += class_count
    return counts


def print_counts(dataset_root: Path, classes: list[str], target_total: int) -> None:
    counts = count_training_images(dataset_root, classes)
    generated = count_generated_images(dataset_root, classes)
    originals = Counter({class_name: counts[class_name] - generated[class_name] for class_name in classes})
    originals["total"] = counts["total"] - generated["total"]
    print_dataset_block(counts, target_total)
    print("Original images:")
    for class_name in classes:
        print(f"{display_class(class_name):10}: {originals[class_name]}")
    print(f"{'TOTAL':10}: {originals['total']}")
    print("Augmented images:")
    for class_name in classes:
        print(f"{display_class(class_name):10}: {generated[class_name]}")
    print(f"{'TOTAL':10}: {generated['total']}")
    print(f"Training Folder: {dataset_root / 'train'}")


def print_dataset_block(counts: Counter, target_total: int) -> None:
    print()
    print("Dataset:")
    for class_name, count in class_items(counts):
        print(f"{display_class(class_name):10}: {count}")
    print(f"{'TOTAL':10}: {counts['total']}")
    print()
    print("Target:")
    print(f"{'TOTAL':10}: {target_total}")
    print()


def prepare_demo_copy(source_root: Path, dataset_root: Path, classes: list[str]) -> None:
    for split in SPLITS:
        for class_name in classes:
            source_dir = source_root / split / class_name
            if not source_dir.is_dir():
                raise FileNotFoundError(f"Missing source class folder: {source_dir}")
            target_dir = dataset_root / split / class_name
            target_dir.mkdir(parents=True, exist_ok=True)
            for source_image in iter_images(source_dir):
                target_image = target_dir / source_image.name
                if target_image.exists():
                    if sha256(target_image) != sha256(source_image):
                        raise FileExistsError(f"Refusing to overwrite different existing file: {target_image}")
                    continue
                shutil.copy2(source_image, target_image)


def build_generation_plan(current_counts: Counter, target_total: int, classes: list[str]) -> Counter:
    needed = target_total - current_counts["total"]
    desired = balanced_target_counts(target_total, classes, current_counts)
    plan: Counter = Counter()
    for class_name in classes:
        plan[class_name] = max(0, desired[class_name] - current_counts[class_name])
    while sum(plan.values()) < needed:
        class_name = min(classes, key=lambda name: current_counts[name] + plan[name])
        plan[class_name] += 1
    while sum(plan.values()) > needed:
        class_name = max(classes, key=lambda name: plan[name])
        plan[class_name] -= 1
    return plan


def balanced_target_counts(target_total: int, classes: list[str], current_counts: Counter) -> Counter:
    base = target_total // len(classes)
    remainder = target_total % len(classes)
    desired = Counter({class_name: base for class_name in classes})
    for class_name in sorted(classes, key=lambda name: (current_counts[name], name))[:remainder]:
        desired[class_name] += 1
    return desired


def generate_augmented_images(
    dataset_root: Path,
    classes: list[str],
    plan: Counter,
    rng: random.Random,
    seed: int,
    starting_index: int,
    augmented_long_side: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    total_to_generate = sum(plan.values())
    generated = 0
    for class_name in classes:
        source_images = [path for path in iter_images(dataset_root / "train" / class_name) if not is_generated(path)]
        if not source_images:
            raise RuntimeError(f"No original source images available for class {class_name}")
        for source_image in cycle(source_images):
            if plan[class_name] <= 0:
                break
            index = starting_index + len(rows) + 1
            augmented, params = augment_image(source_image, rng, augmented_long_side)
            target_name = build_augmented_name(source_image, index, params)
            target_path = source_image.with_name(target_name)
            if target_path.exists():
                raise FileExistsError(f"Refusing to overwrite existing augmented image: {target_path}")
            augmented.save(target_path, format="JPEG", quality=92)
            rows.append(
                {
                    "generated_image": str(target_path),
                    "source_image": str(source_image),
                    "class_name": class_name,
                    "rotation_deg": f"{params['rotation_deg']:.2f}",
                    "horizontal_flip": str(params["horizontal_flip"]).lower(),
                    "brightness_factor": f"{params['brightness_factor']:.3f}",
                    "contrast_factor": f"{params['contrast_factor']:.3f}",
                    "blur": str(params["blur"]).lower(),
                    "noise": str(params["noise"]).lower(),
                    "seed": str(seed),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            generated += 1
            plan[class_name] -= 1
            if generated % 50 == 0 or generated == total_to_generate:
                print(f"Generated: {generated} / {total_to_generate}", flush=True)
    return rows


def augment_image(source_image: Path, rng: random.Random, augmented_long_side: int = 640) -> tuple[Image.Image, dict[str, object]]:
    with Image.open(source_image) as image:
        result = image.convert("RGB")
    if augmented_long_side > 0:
        result = ImageOps.contain(result, (augmented_long_side, augmented_long_side), Image.Resampling.LANCZOS)

    rotation = rng.uniform(-12.0, 12.0)
    horizontal_flip = rng.random() < 0.5
    brightness = rng.uniform(0.75, 1.25)
    contrast = rng.uniform(0.80, 1.20)
    zoom = rng.uniform(1.0, 1.07)
    blur = rng.random() < 0.15
    noise = rng.random() < 0.15

    if horizontal_flip:
        result = ImageOps.mirror(result)
    result = apply_zoom(result, zoom, rng)
    result = result.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=corner_average(result))
    result = ImageEnhance.Brightness(result).enhance(brightness)
    result = ImageEnhance.Contrast(result).enhance(contrast)
    if blur:
        result = result.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.25, 0.9)))
    if noise:
        array = np.asarray(result).astype(np.int16)
        array += rng_np_noise(rng, array.shape)
        result = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8), mode="RGB")

    return result, {
        "rotation_deg": rotation,
        "horizontal_flip": horizontal_flip,
        "brightness_factor": brightness,
        "contrast_factor": contrast,
        "blur": blur,
        "noise": noise,
    }


def apply_zoom(image: Image.Image, zoom: float, rng: random.Random) -> Image.Image:
    if zoom <= 1.001:
        return image
    width, height = image.size
    resized = image.resize((math.ceil(width * zoom), math.ceil(height * zoom)), Image.Resampling.BICUBIC)
    max_left = resized.width - width
    max_top = resized.height - height
    left = rng.randint(0, max_left) if max_left > 0 else 0
    top = rng.randint(0, max_top) if max_top > 0 else 0
    return resized.crop((left, top, left + width, top + height))


def rng_np_noise(rng: random.Random, shape: tuple[int, ...]) -> np.ndarray:
    np_rng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    return np_rng.normal(loc=0, scale=rng.uniform(2.0, 6.0), size=shape).astype(np.int16)


def corner_average(image: Image.Image) -> tuple[int, int, int]:
    width, height = image.size
    points = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    values = [image.getpixel(point) for point in points]
    return tuple(sum(pixel[channel] for pixel in values) // len(values) for channel in range(3))


def build_augmented_name(source_image: Path, index: int, params: dict[str, object]) -> str:
    angle = int(round(float(params["rotation_deg"])))
    brightness = int(round(float(params["brightness_factor"]) * 100))
    contrast = int(round(float(params["contrast_factor"]) * 100))
    flags = []
    if params["horizontal_flip"]:
        flags.append("flip")
    if params["blur"]:
        flags.append("blur")
    if params["noise"]:
        flags.append("noise")
    suffix = "_".join(flags) if flags else "clean"
    stem = source_image.stem[:90]
    return f"{stem}_aug_{index:06d}_rot_{angle:+03d}_bri_{brightness:03d}_con_{contrast:03d}_{suffix}.jpg"


def verify_dataset(
    paths: DemoPaths,
    source_root: Path,
    classes: list[str],
    source_snapshot: dict[str, str],
    manifest_rows: list[dict[str, str]],
) -> None:
    generated_paths = [Path(row["generated_image"]) for row in manifest_rows]
    for path in generated_paths:
        if not path.exists():
            raise FileNotFoundError(f"Manifest generated image is missing: {path}")
        if "_aug_" not in path.stem:
            raise RuntimeError(f"Generated image name does not contain _aug_: {path}")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width <= 0 or image.height <= 0:
                raise RuntimeError(f"Invalid generated image dimensions: {path}")

    actual_generated = count_generated_images(paths.dataset_root, classes)["total"]
    if len(generated_paths) != actual_generated:
        raise RuntimeError(
            f"Manifest/generated file mismatch: manifest={len(generated_paths)}, actual={actual_generated}"
        )

    for split in ("val", "test"):
        for class_name in classes:
            for path in iter_images(paths.dataset_root / split / class_name):
                if is_generated(path):
                    raise RuntimeError(f"Validation/test split contains augmented image: {path}")

    demo_snapshot = snapshot_split_hashes(paths.dataset_root, classes, splits=("val", "test"))
    expected_demo_snapshot = {
        str((paths.dataset_root / Path(key).relative_to(source_root)).resolve()): value
        for key, value in source_snapshot.items()
    }
    if demo_snapshot != expected_demo_snapshot:
        raise RuntimeError("Validation/test hashes changed during augmentation demo.")


def make_preview(dataset_root: Path, preview_root: Path, classes: list[str], rng: random.Random) -> None:
    preview_root.mkdir(parents=True, exist_ok=True)
    originals: list[Path] = []
    for class_name in classes:
        originals.extend([path for path in iter_images(dataset_root / "train" / class_name) if not is_generated(path)][:4])
    originals = originals[:8]
    if not originals:
        return

    labels = ["Original", "Rotation", "Brightness", "Flip", "Combined"]
    cell_w, cell_h = 260, 180
    label_h = 24
    sheet = Image.new("RGB", (cell_w * len(labels), (cell_h + label_h) * len(originals)), "white")
    draw = ImageDraw.Draw(sheet)
    for row_index, original in enumerate(originals):
        variants = build_preview_variants(original, rng)
        for col_index, label in enumerate(labels):
            x = col_index * cell_w
            y = row_index * (cell_h + label_h)
            draw.rectangle((x, y, x + cell_w, y + label_h), fill=(245, 245, 245))
            draw.text((x + 8, y + 5), label, fill=(20, 20, 20))
            thumb = ImageOps.contain(variants[label], (cell_w, cell_h), Image.Resampling.LANCZOS)
            paste_x = x + (cell_w - thumb.width) // 2
            paste_y = y + label_h + (cell_h - thumb.height) // 2
            sheet.paste(thumb, (paste_x, paste_y))
    sheet.save(preview_root / "before_after_contact_sheet.jpg", format="JPEG", quality=92)


def build_preview_variants(source_image: Path, rng: random.Random) -> dict[str, Image.Image]:
    with Image.open(source_image) as image:
        original = image.convert("RGB")
    return {
        "Original": original,
        "Rotation": original.rotate(10, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=corner_average(original)),
        "Brightness": ImageEnhance.Brightness(original).enhance(1.22),
        "Flip": ImageOps.mirror(original),
        "Combined": augment_image(source_image, rng)[0],
    }


def read_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    if not manifest_path.exists():
        return []
    with manifest_path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_manifest(manifest_path: Path, rows: list[dict[str, str]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    paths: DemoPaths,
    source_root: Path,
    original_counts: Counter,
    added_counts: Counter,
    final_counts: Counter,
    classes: list[str],
    seed: int,
) -> None:
    generated_total = count_generated_images(paths.dataset_root, classes)["total"]
    report = {
        "status": "PASS",
        "model_target": "EfficientNet-B0",
        "task": "FALL_NON_FALL_BINARY_CLASSIFICATION",
        "source_dataset": str(source_root),
        "demo_dataset": str(paths.dataset_root),
        "original_total": int(original_counts["total"]),
        "generated_total": int(generated_total),
        "generated_this_run": int(sum(added_counts.values())),
        "final_total": int(final_counts["total"]),
        "class_counts_before": {display_class(name): int(original_counts[name]) for name in classes},
        "class_counts_after": {display_class(name): int(final_counts[name]) for name in classes},
        "augmentation_methods": {
            "rotation_degrees": [-12, 12],
            "horizontal_flip": True,
            "brightness_factor": [0.75, 1.25],
            "contrast_factor": [0.80, 1.20],
            "light_zoom_crop": True,
            "gaussian_blur_low_probability": True,
            "gaussian_noise_low_probability": True,
        },
        "seed": seed,
        "validation_augmented": False,
        "test_augmented": False,
        "data_leakage_guard": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_generated(paths: DemoPaths, *, allow_orphaned: bool = False) -> None:
    print("[INFO] Cleaning generated augmentation files listed in manifest...")
    rows = read_manifest_rows(paths.manifest_path)
    if not rows:
        print("[INFO] No manifest found; nothing to clean.")
        if allow_orphaned:
            deleted = clean_orphaned_generated(paths)
            print(f"[INFO] Deleted orphaned generated images: {deleted}")
        return
    deleted = 0
    for row in rows:
        path = Path(row.get("generated_image", ""))
        if not path.exists():
            continue
        resolved = path.resolve()
        if paths.dataset_root.resolve() not in resolved.parents or "_aug_" not in resolved.stem:
            raise RuntimeError(f"Refusing to delete a file outside generated demo scope: {resolved}")
        resolved.unlink()
        deleted += 1
    for extra in (paths.manifest_path, paths.report_path, paths.preview_root / "before_after_contact_sheet.jpg"):
        if extra.exists():
            extra.unlink()
    print(f"[INFO] Deleted generated images: {deleted}")
    if allow_orphaned:
        orphaned = clean_orphaned_generated(paths)
        print(f"[INFO] Deleted orphaned generated images: {orphaned}")


def clean_orphaned_generated(paths: DemoPaths) -> int:
    train_root = paths.dataset_root / "train"
    if not train_root.exists():
        return 0
    deleted = 0
    for path in train_root.rglob("*_aug_*.jpg"):
        resolved = path.resolve()
        if paths.dataset_root.resolve() not in resolved.parents or "_aug_" not in resolved.stem:
            raise RuntimeError(f"Refusing to delete a file outside generated demo scope: {resolved}")
        resolved.unlink()
        deleted += 1
    return deleted


def snapshot_split_hashes(dataset_root: Path, classes: list[str], splits: tuple[str, ...]) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for split in splits:
        for class_name in classes:
            for path in iter_images(dataset_root / split / class_name):
                snapshot[str(path.resolve())] = sha256(path)
    return snapshot


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def class_items(counts: Counter) -> list[tuple[str, int]]:
    return [(key, counts[key]) for key in counts if key != "total"]


def display_class(class_name: str) -> str:
    return "NON_FALL" if class_name.lower() == "nofall" else class_name.upper()


def print_summary(
    *,
    before: Counter,
    added: Counter,
    after: Counter,
    target_total: int,
    paths: DemoPaths,
    generated_now: int,
) -> None:
    print()
    print("============================================")
    print("DATA AUGMENTATION PASS")
    print("======================")
    print()
    print(f"Before : {before['total']} images")
    print(f"Added  : {generated_now} images")
    print(f"After  : {after['total']} images")
    print(f"Target : {target_total} images")
    print()
    class_names = [name for name in before.keys() if name != "total"]
    for class_name in class_names:
        print(f"{display_class(class_name):8}: {before[class_name]} -> {after[class_name]}")
    print()
    print("Rotation        : ENABLED")
    print("Lighting        : ENABLED")
    print("Horizontal Flip : ENABLED")
    print("Contrast        : ENABLED")
    print()
    print("Validation/Test : UNCHANGED")
    print(f"Manifest        : {paths.manifest_path}")
    print(f"Report          : {paths.report_path}")
    print(f"Preview         : {paths.preview_root / 'before_after_contact_sheet.jpg'}")
    print(f"Output Folder   : {paths.dataset_root / 'train'}")
    print("========================")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[ERROR] Interrupted by user.", file=sys.stderr)
        raise SystemExit(130)
