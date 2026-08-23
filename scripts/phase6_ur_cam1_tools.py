from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.download_fall_datasets import DATASETS_DIR, download_file, convert_zip_to_video


MANIFEST_PATH = DATASETS_DIR / "dataset_manifest.json"
LABELS_PATH = ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl"
BASE_URL = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
DATASET = "ur_fall_cam1"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Download a small UR Fall cam1 supplement for Phase 6D.")
    parser.add_argument("--fall-count", type=int, default=2)
    args = parser.parse_args()
    download_and_register(fall_count=args.fall_count)
    return 0


def download_and_register(*, fall_count: int) -> None:
    raw_dir = DATASETS_DIR / DATASET / "raw"
    videos_dir = DATASETS_DIR / DATASET / "videos"
    raw_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    videos = []
    labels = {}
    for idx in range(1, fall_count + 1):
        archive = f"fall-{idx:02d}-cam1-rgb.zip"
        video_name = f"fall-{idx:02d}-cam1.mp4"
        zip_path = raw_dir / archive
        video_path = videos_dir / video_name
        if not zip_path.exists():
            download_file(f"{BASE_URL}{archive}", zip_path)
        if not video_path.exists():
            convert_zip_to_video(zip_path, video_path)
        videos.append(video_name)
        labels[video_name] = "fall"

    update_manifest(videos, labels)
    append_labels(videos)
    summary = {"dataset": DATASET, "fall_videos": len(videos), "videos": videos}
    out = ROOT / "evaluations" / "phase6d_ur_cam1_supplement_001.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def update_manifest(videos: list[str], labels: dict[str, str]) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else {}
    manifest[DATASET] = {
        "available": True,
        "videos": videos,
        "labels": labels,
        "failed_reason": None,
        "source_url": "https://fenix.ur.edu.pl/~mkepski/ds/uf.html",
        "notes": "UR Fall cam1 RGB supplement used only to reach Phase 6D fall-count gate.",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def append_labels(videos: list[str]) -> None:
    rows = []
    if LABELS_PATH.exists():
        rows = [json.loads(line) for line in LABELS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    existing = {row["video_id"] for row in rows}
    for video in videos:
        video_id = f"{DATASET}/{video}"
        if video_id in existing:
            continue
        stem = Path(video).stem.replace("-", "_")
        rows.append(
            {
                "video_id": video_id,
                "source_dataset": DATASET,
                "license": "CC BY-NC-SA 4.0",
                "split_group": f"{DATASET}_{stem}",
                "binary_label": "fall",
                "non_fall_subtype": None,
                "event_start_frame": 0,
                "event_end_frame": None,
                "usable_for_training": True,
                "split": "unassigned",
                "notes": "UR Fall cam1 fall supplement; same source event different camera view",
            }
        )
    LABELS_PATH.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
