from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "datasets" / "fall_hint_v2_reviewed_all_b001_b029"
DEFAULT_BATCH_ID = "batch_030_second_review_b001_b029"
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a non-destructive second-review labeler batch from reviewed Fall Hint batches 001-029."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    source_images = source / "images"
    source_labels = source / "labels"
    source_manifest = source / "meta" / "manifest.csv"
    if not source_images.exists():
        raise SystemExit(f"missing source images: {source_images}")
    if not source_labels.exists():
        raise SystemExit(f"missing source labels: {source_labels}")
    if not source_manifest.exists():
        raise SystemExit(f"missing source manifest: {source_manifest}")

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"output batch already exists, pass --overwrite to rebuild: {batch_dir}")
        shutil.rmtree(batch_dir)

    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    meta_dir = batch_dir / "meta"
    frames_dir.mkdir(parents=True, exist_ok=True)
    prelabels_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(source_manifest)
    frame_rows: list[dict[str, object]] = []
    missing: list[dict[str, str]] = []
    batch_counts: dict[str, int] = {}

    for row in rows:
        image_rel = row.get("new_image") or row.get("image") or ""
        label_rel = row.get("new_label") or row.get("label") or ""
        if not image_rel or not label_rel:
            missing.append({"reason": "missing_manifest_paths", **row})
            continue
        image_src = source / image_rel
        label_src = source / label_rel
        if not image_src.exists() or not label_src.exists():
            missing.append(
                {
                    "reason": "missing_source_file",
                    "image": str(image_src),
                    "label": str(label_src),
                    "batch_id": row.get("batch_id", ""),
                }
            )
            continue

        image_dst = frames_dir / image_src.name
        label_dst = prelabels_dir / f"{image_src.stem}.txt"
        shutil.copy2(image_src, image_dst)
        shutil.copy2(label_src, label_dst)

        source_batch = row.get("batch_id", "")
        batch_counts[source_batch] = batch_counts.get(source_batch, 0) + 1
        frame_rows.append(
            {
                "image": image_dst.name,
                "video_id": row.get("video_id", ""),
                "scene": row.get("scene", ""),
                "group": row.get("group", ""),
                "source_batch_id": source_batch,
                "source_reviewed_image": image_rel,
                "source_reviewed_label": label_rel,
                "source_original_image": row.get("original_image", ""),
                "source_video": row.get("source_video", ""),
                "source_manifest_index": row.get("index", ""),
                "second_review_status": "draft",
            }
        )

    write_csv(
        meta_dir / "frame_manifest.csv",
        frame_rows,
        [
            "image",
            "video_id",
            "scene",
            "group",
            "source_batch_id",
            "source_reviewed_image",
            "source_reviewed_label",
            "source_original_image",
            "source_video",
            "source_manifest_index",
            "second_review_status",
        ],
    )
    write_csv(meta_dir / "prepare_missing.csv", missing, list(missing[0].keys()) if missing else ["reason"])

    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "source": str(source),
        "source_manifest": str(source_manifest),
        "prepared_images": len(frame_rows),
        "prepared_labels": len(frame_rows),
        "missing_count": len(missing),
        "batch_counts": dict(sorted(batch_counts.items())),
        "review_policy": "Second-review labels are seeded from reviewed_all_b001_b029 prelabels. Human second-review saves go to human_review/labels and human_review/meta.",
        "source_dataset_unchanged": True,
    }
    (meta_dir / "prepare_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
