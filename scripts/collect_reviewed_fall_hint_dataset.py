from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
DEFAULT_OUTPUT = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"

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
class ReviewedSample:
    batch_id: str
    original_image_name: str
    image_path: Path
    label_path: Path
    meta_path: Path
    video_id: str
    scene: str
    group: str
    source_video: str
    frame_index: str
    class_counts: Counter[int]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect only confirmed human-reviewed fall_hint_v2 samples into a single "
            "numbered image/label archive."
        )
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--start-batch", type=int, default=1)
    parser.add_argument("--end-batch", type=int, default=29)
    parser.add_argument("--prefix", default="fhv2_reviewed")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output

    samples, skipped = collect_samples(args.start_batch, args.end_batch)
    if not samples:
        raise SystemExit("No valid human-reviewed samples found.")

    prepare_output(output, overwrite=args.overwrite)
    rows = write_archive(output, samples, prefix=args.prefix)
    write_metadata(output, rows, samples, skipped, args)
    print(json.dumps(build_summary(rows, samples, skipped, output), ensure_ascii=False, indent=2))
    return 0


def collect_samples(start_batch: int, end_batch: int) -> tuple[list[ReviewedSample], list[dict[str, str]]]:
    samples: list[ReviewedSample] = []
    skipped: list[dict[str, str]] = []

    for batch_index in range(start_batch, end_batch + 1):
        batch_id = f"batch_{batch_index:03d}"
        batch_dir = RAW_ROOT / batch_id
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        meta_dir = batch_dir / "human_review" / "meta"
        frame_manifest = read_frame_manifest(batch_dir / "meta" / "frame_manifest.csv")

        if not frames_dir.exists() or not labels_dir.exists() or not meta_dir.exists():
            skipped.append(
                {
                    "batch_id": batch_id,
                    "image": "",
                    "reason": "missing_required_batch_directory",
                    "path": str(batch_dir),
                }
            )
            continue

        for meta_path in sorted(meta_dir.glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": meta_path.stem,
                        "reason": f"bad_meta_json: {exc}",
                        "path": str(meta_path),
                    }
                )
                continue

            if meta.get("status") != "reviewed":
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": str(meta.get("image") or meta_path.stem),
                        "reason": "meta_status_not_reviewed",
                        "path": str(meta_path),
                    }
                )
                continue

            image_name = str(meta.get("image") or f"{meta_path.stem}.jpg")
            image_path = frames_dir / image_name
            label_path = labels_dir / f"{Path(image_name).stem}.txt"

            if image_path.suffix.lower() not in IMAGE_EXTS or not image_path.exists():
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": image_name,
                        "reason": "missing_or_unsupported_image",
                        "path": str(image_path),
                    }
                )
                continue

            if not label_path.exists():
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": image_name,
                        "reason": "missing_label",
                        "path": str(label_path),
                    }
                )
                continue

            try:
                class_counts = validate_label_file(label_path)
            except ValueError as exc:
                skipped.append(
                    {
                        "batch_id": batch_id,
                        "image": image_name,
                        "reason": f"invalid_label: {exc}",
                        "path": str(label_path),
                    }
                )
                continue

            frame_row = frame_manifest.get(image_name, {})
            samples.append(
                ReviewedSample(
                    batch_id=batch_id,
                    original_image_name=image_name,
                    image_path=image_path,
                    label_path=label_path,
                    meta_path=meta_path,
                    video_id=frame_row.get("video_id") or str(meta.get("video_id") or Path(image_name).stem),
                    scene=frame_row.get("scene") or str(meta.get("scene") or ""),
                    group=frame_row.get("group") or str(meta.get("group") or ""),
                    source_video=frame_row.get("source_video") or str(meta.get("source_video") or ""),
                    frame_index=frame_row.get("frame_index") or str(meta.get("frame_index") or ""),
                    class_counts=class_counts,
                )
            )

    return samples, skipped


def prepare_output(output: Path, *, overwrite: bool) -> None:
    if output.exists():
        if not overwrite:
            raise SystemExit(f"{output} already exists; pass --overwrite only when rebuilding this archive")
        shutil.rmtree(output)
    for subdir in ["images", "labels", "meta"]:
        (output / subdir).mkdir(parents=True, exist_ok=True)


def write_archive(output: Path, samples: list[ReviewedSample], *, prefix: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, sample in enumerate(samples, start=1):
        new_stem = f"{prefix}_{index:06d}"
        new_image_name = f"{new_stem}{sample.image_path.suffix.lower()}"
        new_label_name = f"{new_stem}.txt"
        out_image = output / "images" / new_image_name
        out_label = output / "labels" / new_label_name
        shutil.copy2(sample.image_path, out_image)
        shutil.copy2(sample.label_path, out_label)

        rows.append(
            {
                "index": f"{index:06d}",
                "new_stem": new_stem,
                "new_image": f"images/{new_image_name}",
                "new_label": f"labels/{new_label_name}",
                "batch_id": sample.batch_id,
                "original_image": sample.original_image_name,
                "original_image_path": str(sample.image_path),
                "original_label_path": str(sample.label_path),
                "original_meta_path": str(sample.meta_path),
                "video_id": sample.video_id,
                "scene": sample.scene,
                "group": sample.group,
                "source_video": sample.source_video,
                "frame_index": sample.frame_index,
                "box_count": str(sum(sample.class_counts.values())),
                "is_empty_label": "true" if not sample.class_counts else "false",
                "class_counts": json.dumps(
                    {CLASS_NAMES[class_id]: count for class_id, count in sorted(sample.class_counts.items())},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return rows


def write_metadata(
    output: Path,
    rows: list[dict[str, str]],
    samples: list[ReviewedSample],
    skipped: list[dict[str, str]],
    args: argparse.Namespace,
) -> None:
    write_csv(output / "meta" / "manifest.csv", rows)
    with (output / "meta" / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_csv(output / "meta" / "skipped.csv", skipped)
    (output / "meta" / "classes.json").write_text(
        json.dumps(CLASS_NAMES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "classes.txt").write_text(
        "\n".join(CLASS_NAMES[index] for index in sorted(CLASS_NAMES)) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(build_readme(output, rows, skipped), encoding="utf-8")
    (output / "meta" / "build_summary.json").write_text(
        json.dumps(build_summary(rows, samples, skipped, output, args=args), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_summary(
    rows: list[dict[str, str]],
    samples: list[ReviewedSample],
    skipped: list[dict[str, str]],
    output: Path,
    *,
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    batch_counts: Counter[str] = Counter(row["batch_id"] for row in rows)
    class_counts: Counter[str] = Counter()
    empty_count = 0
    box_count = 0
    for sample in samples:
        if not sample.class_counts:
            empty_count += 1
        for class_id, count in sample.class_counts.items():
            class_counts[CLASS_NAMES[class_id]] += count
            box_count += count

    summary: dict[str, Any] = {
        "output": str(output),
        "image_dir": str(output / "images"),
        "label_dir": str(output / "labels"),
        "manifest": str(output / "meta" / "manifest.csv"),
        "total_valid_reviewed_samples": len(rows),
        "total_empty_label_samples": empty_count,
        "total_boxes": box_count,
        "skipped_count": len(skipped),
        "batch_counts": dict(sorted(batch_counts.items())),
        "class_counts": dict(sorted(class_counts.items())),
        "guardrail": "Only samples with human_review/meta status=reviewed and valid YOLO labels are included.",
    }
    if args is not None:
        summary["source_batch_range"] = [f"batch_{args.start_batch:03d}", f"batch_{args.end_batch:03d}"]
        summary["output_prefix"] = args.prefix
    return summary


def build_readme(output: Path, rows: list[dict[str, str]], skipped: list[dict[str, str]]) -> str:
    return "\n".join(
        [
            "# fall_hint_v2 Reviewed Archive",
            "",
            "This folder contains only samples confirmed by `human_review/meta/*.json` with `status=reviewed`.",
            "Images and labels are renamed with the same numeric stem so they remain one-to-one.",
            "",
            "Important files:",
            "",
            "- `images/`: reviewed images, named in stable sequential order.",
            "- `labels/`: matching YOLO label files with the same stem as each image.",
            "- `meta/manifest.csv`: authoritative mapping from new names back to original batch/image/label/meta.",
            "- `meta/skipped.csv`: reviewed or candidate samples that were not included, with reasons.",
            "- `classes.txt`: class names in YOLO class-id order.",
            "",
            f"Included samples: {len(rows)}",
            f"Skipped samples: {len(skipped)}",
            "",
            "Class order:",
            "",
            *[f"- `{index}`: `{name}`" for index, name in CLASS_NAMES.items()],
            "",
            "Do not manually add files here without updating `meta/manifest.csv`.",
        ]
    )


def read_frame_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def validate_label_file(path: Path) -> Counter[int]:
    counts: Counter[int] = Counter()
    for line_index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
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
        counts[class_id] += 1
    return counts


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        if not fieldnames:
            fh.write("")
            return
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
