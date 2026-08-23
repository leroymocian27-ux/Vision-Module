from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PERSON_RAW_ROOT = ROOT / "datasets" / "person_yolo_raw"
POSE_RAW_ROOT = ROOT / "datasets" / "pose_yolo_raw"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

DEFAULT_QUOTAS = {
    "falling": 20,
    "fallen": 16,
    "lying": 18,
    "kneeling": 20,
    "bending": 16,
    "sitting": 10,
    "standing": 8,
    "walking": 4,
    "multi_occlusion_complex": 4,
    "hard_negative_object": 4,
}

PROFILE_QUOTAS = {
    "balanced": DEFAULT_QUOTAS,
    "fall_floor": {
        "falling": 28,
        "fallen": 24,
        "lying": 28,
        "kneeling": 16,
        "bending": 12,
        "sitting": 6,
        "multi_occlusion_complex": 3,
        "hard_negative_object": 3,
    },
    "final_train": {
        "falling": 48,
        "lying": 48,
        "kneeling": 42,
        "fallen": 26,
        "bending": 29,
        "sitting": 18,
        "standing": 12,
        "walking": 10,
        "hard_negative_object": 7,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a manually reviewed YOLO pose keypoint batch.")
    parser.add_argument("--batch-id", default="batch_001")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--source-batches", nargs="*", default=[f"batch_{i:03d}" for i in range(3, 9)])
    parser.add_argument("--profile", choices=sorted(PROFILE_QUOTAS), default="balanced")
    args = parser.parse_args()

    excluded_sources = collect_existing_source_images(except_batch=args.batch_id)
    candidates = collect_candidates(args.source_batches, excluded_sources=excluded_sources)
    selected = select_candidates(candidates, PROFILE_QUOTAS[args.profile], args.limit)
    if not selected:
        raise SystemExit("No pose candidates found.")

    out_root = POSE_RAW_ROOT / args.batch_id
    frames_dir = out_root / "frames"
    prelabels_dir = out_root / "prelabels"
    meta_dir = out_root / "meta"
    frames_dir.mkdir(parents=True, exist_ok=True)
    prelabels_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []
    for index, item in enumerate(selected, start=1):
        group = item["group"] or "unknown"
        image_name = f"{args.batch_id}_{group}_{index:03d}{Path(item['image']).suffix.lower()}"
        shutil.copy2(item["image_path"], frames_dir / image_name)
        prelabel = {
            "image": image_name,
            "source_image": str(Path(item["image_path"]).relative_to(ROOT)).replace("\\", "/"),
            "annotations": [
                {
                    "bbox": box,
                    "keypoints": [
                        {"name": name, "x": 0.0, "y": 0.0, "v": 0}
                        for name in KEYPOINT_NAMES
                    ],
                }
                for box in item["boxes"]
            ],
        }
        (prelabels_dir / f"{Path(image_name).stem}.json").write_text(
            json.dumps(prelabel, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows.append(
            {
                "image": image_name,
                "source_image": str(Path(item["image_path"]).relative_to(ROOT)).replace("\\", "/"),
                "source_batch": item["batch"],
                "source_name": item["image"],
                "group": group,
                "scene": item["scene"],
                "source_dataset": item["source_dataset"],
                "video_id": item["video_id"],
                "person_boxes": str(len(item["boxes"])),
                "note": "Mark COCO-17 keypoints for every preloaded person bbox; use missing for invisible keypoints.",
            }
        )

    write_csv(meta_dir / "frame_manifest.csv", rows)
    summary = {
        "batch_id": args.batch_id,
        "item_count": len(rows),
        "source_batches": args.source_batches,
        "profile": args.profile,
        "excluded_existing_sources": len(excluded_sources),
        "groups": count_groups(rows),
        "keypoints": KEYPOINT_NAMES,
    }
    (meta_dir / "prepare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (meta_dir / "labeling_guide.md").write_text(labeling_guide(), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def collect_existing_source_images(*, except_batch: str) -> set[str]:
    used: set[str] = set()
    for batch_dir in sorted(POSE_RAW_ROOT.glob("batch_*")):
        if batch_dir.name == except_batch:
            continue
        manifest_path = batch_dir / "meta" / "frame_manifest.csv"
        if not manifest_path.exists():
            continue
        for row in read_manifest(manifest_path).values():
            source = row.get("source_image")
            if source:
                used.add(source.replace("\\", "/"))
    return used


def collect_candidates(source_batches: list[str], *, excluded_sources: set[str]) -> list[dict]:
    items: list[dict] = []
    seen_hashes: set[str] = set()
    for batch_id in source_batches:
        batch_dir = PERSON_RAW_ROOT / batch_id
        manifest = read_manifest(batch_dir / "meta" / "frame_manifest.csv")
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        meta_dir = batch_dir / "human_review" / "meta"
        if not frames_dir.exists() or not labels_dir.exists():
            continue
        for image_path in sorted(frames_dir.iterdir()):
            if image_path.suffix.lower() not in IMAGE_EXTS:
                continue
            meta_path = meta_dir / f"{image_path.stem}.json"
            if not meta_path.exists():
                continue
            try:
                if json.loads(meta_path.read_text(encoding="utf-8")).get("status") != "reviewed":
                    continue
            except json.JSONDecodeError:
                continue
            labels = read_yolo_person_labels(labels_dir / f"{image_path.stem}.txt")
            if not labels:
                continue
            digest = sha256_file(image_path)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            row = manifest.get(image_path.name, {})
            rel_source = str(image_path.relative_to(ROOT)).replace("\\", "/")
            if rel_source in excluded_sources:
                continue
            items.append(
                {
                    "batch": batch_id,
                    "image": image_path.name,
                    "image_path": image_path,
                    "boxes": labels,
                    "group": row.get("group") or "",
                    "scene": row.get("scene") or "",
                    "source_dataset": row.get("source_dataset") or "",
                    "video_id": row.get("video_id") or "",
                }
            )
    return items


def select_candidates(candidates: list[dict], quotas: dict[str, int], limit: int) -> list[dict]:
    by_group: dict[str, list[dict]] = defaultdict(list)
    for item in candidates:
        by_group[item["group"]].append(item)

    selected: list[dict] = []
    for group, quota in quotas.items():
        selected.extend(by_group.get(group, [])[:quota])

    if len(selected) < limit:
        selected_ids = {str(item["image_path"]) for item in selected}
        for item in candidates:
            if len(selected) >= limit:
                break
            if str(item["image_path"]) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(str(item["image_path"]))
    return selected[:limit]


def read_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as fh:
        return {row.get("image", ""): row for row in csv.DictReader(fh) if row.get("image")}


def read_yolo_person_labels(path: Path) -> list[dict[str, float]]:
    boxes = []
    if not path.exists():
        return boxes
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5 or parts[0] != "0":
            continue
        x, y, w, h = map(float, parts[1:])
        if w <= 0 or h <= 0:
            continue
        boxes.append({"x": x, "y": y, "w": w, "h": h})
    return boxes


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def count_groups(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["group"]] += 1
    return dict(sorted(counts.items()))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def labeling_guide() -> str:
    return "\n".join(
        [
            "# YOLO Pose Labeling Guide",
            "",
            "- Mark COCO-17 keypoints for each preloaded person bbox.",
            "- Click visible keypoints precisely on the body joint.",
            "- Use Missing for keypoints that are outside frame or impossible to locate.",
            "- Do not drag keypoints onto guessed locations outside the body.",
            "- If the bbox is a false person, mark every keypoint Missing and save.",
            "- The image is the raw frame, not overlay or skeleton output.",
            "",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
