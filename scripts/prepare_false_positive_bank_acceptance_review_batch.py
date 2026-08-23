from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ACCEPTANCE = ROOT / "datasets" / "fall_false_positive_bank_202607" / "subsets" / "acceptance_only.csv"
DEFAULT_BATCH_ID = "batch_033_acceptance_only_preview"
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a small labeler batch from fall_false_positive_bank acceptance_only.csv")
    parser.add_argument("--acceptance-csv", type=Path, default=DEFAULT_ACCEPTANCE)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def main() -> int:
    args = parse_args()
    acceptance_csv = args.acceptance_csv.resolve()
    if not acceptance_csv.exists():
        raise SystemExit(f"missing acceptance csv: {acceptance_csv}")

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"batch already exists, pass --overwrite to rebuild: {batch_dir}")
        shutil.rmtree(batch_dir)

    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
    meta_dir = batch_dir / "meta"
    frames_dir.mkdir(parents=True, exist_ok=True)
    prelabels_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows = read_csv(acceptance_csv)
    frame_rows: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    category_counts: dict[str, int] = {}
    for idx, row in enumerate(rows, start=1):
        image_src = Path(row["bank_image_path"])
        label_src = Path(row["bank_label_path"])
        if not image_src.exists() or not label_src.exists():
            missing_rows.append(
                {
                    "bank_id": row.get("bank_id", ""),
                    "category": row.get("category", ""),
                    "image_exists": image_src.exists(),
                    "label_exists": label_src.exists(),
                    "bank_image_path": str(image_src),
                    "bank_label_path": str(label_src),
                }
            )
            continue

        image_dst = frames_dir / image_src.name
        label_dst = prelabels_dir / f"{image_src.stem}.txt"
        shutil.copy2(image_src, image_dst)
        shutil.copy2(label_src, label_dst)
        category = row.get("category", "uncertain")
        category_counts[category] = category_counts.get(category, 0) + 1
        frame_rows.append(
            {
                "image": image_dst.name,
                "video_id": row.get("bank_id", ""),
                "scene": category,
                "group": "acceptance_only",
                "source_batch_id": row.get("source_batch", ""),
                "source_reviewed_image": row.get("source_image_path", ""),
                "source_reviewed_label": row.get("source_label_path", ""),
                "source_original_image": Path(row.get("source_image_path", "")).name,
                "source_video": row.get("source_file", ""),
                "source_manifest_index": idx,
                "second_review_status": "draft",
                "reason": row.get("reason", ""),
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
            "reason",
        ],
    )
    write_csv(
        meta_dir / "missing_items.csv",
        missing_rows,
        ["bank_id", "category", "image_exists", "label_exists", "bank_image_path", "bank_label_path"],
    )

    summary = {
        "batch_id": args.batch_id,
        "batch_dir": str(batch_dir),
        "acceptance_csv": str(acceptance_csv),
        "prepared_images": len(frame_rows),
        "missing_items": len(missing_rows),
        "category_counts": category_counts,
    }
    (meta_dir / "prepare_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (batch_dir / "classes.txt").write_text("falling\nfallen\nlying\nsitting\nbending\nkneeling\nstanding\n", encoding="utf-8")
    (batch_dir / "README.md").write_text(
        "Acceptance-only preview batch built from fall_false_positive_bank_202607/subsets/acceptance_only.csv\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
