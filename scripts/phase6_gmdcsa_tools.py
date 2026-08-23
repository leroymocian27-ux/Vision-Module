from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"
MANIFEST_PATH = DATASETS_DIR / "dataset_manifest.json"
LABELS_PATH = ROOT / "data" / "phase6_labels" / "phase6_labels.jsonl"
ZENODO_RECORD_API = "https://zenodo.org/api/records/10889217"
DATASET_NAME = "gmdcsa24"

ADL_SUBTYPE_KEYWORDS = {
    "sitting": ["sit", "sitting", "chair"],
    "bending": ["bend", "bending"],
    "squatting": ["squat", "squatting"],
    "picking_object": ["pick", "picking", "object"],
    "lying_down_normal": ["lie", "lying", "lay", "sleep", "bed"],
    "walking": ["walk", "walking"],
    "standing": ["stand", "standing"],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and register GMDCSA-24 for Phase 6D.")
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser("download")
    download.add_argument("--force", action="store_true")

    register = sub.add_parser("register")
    register.add_argument("--min-fall", type=int, default=80)
    register.add_argument("--max-unknown-ratio", type=float, default=0.1)

    args = parser.parse_args()
    if args.command == "download":
        download_dataset(force=args.force)
    elif args.command == "register":
        register_dataset(min_fall=args.min_fall, max_unknown_ratio=args.max_unknown_ratio)
    return 0


def download_dataset(*, force: bool = False) -> None:
    record = fetch_record()
    files = record.get("files") or []
    if not files:
        raise SystemExit("Zenodo record has no files")
    file_info = files[0]
    download_url = file_info["links"]["self"]
    raw_dir = DATASETS_DIR / DATASET_NAME / "raw"
    extract_dir = DATASETS_DIR / DATASET_NAME / "source"
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive_path = raw_dir / safe_filename(file_info["key"])

    if force and archive_path.exists():
        archive_path.unlink()
    if not archive_path.exists():
        download_file(download_url, archive_path)

    if force and extract_dir.exists():
        shutil.rmtree(extract_dir)
    if not extract_dir.exists() or not any(extract_dir.rglob("*.mp4")):
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)

    videos_dir = DATASETS_DIR / DATASET_NAME / "videos"
    if videos_dir.exists():
        shutil.rmtree(videos_dir)
    videos_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(extract_dir.rglob("*.mp4")):
        dst = videos_dir / canonical_video_name(src)
        if not dst.exists():
            shutil.copy2(src, dst)
            copied += 1
    print(json.dumps({"archive": str(archive_path), "videos": len(list(videos_dir.glob('*.mp4'))), "copied": copied}))


def register_dataset(*, min_fall: int, max_unknown_ratio: float) -> None:
    videos_dir = DATASETS_DIR / DATASET_NAME / "videos"
    videos = sorted(videos_dir.glob("*.mp4"))
    if not videos:
        raise SystemExit("no GMDCSA videos found; run download first")

    label_by_video = build_label_index()
    labels = {}
    phase6_rows = [row for row in load_existing_labels() if not str(row.get("video_id", "")).startswith(f"{DATASET_NAME}/")]
    existing_ids = {row["video_id"] for row in phase6_rows}
    subtype_counts = Counter()
    fall_count = 0
    unknown_count = 0
    non_fall_count = 0

    for video_path in videos:
        meta = label_by_video.get(video_path.name)
        if not meta:
            binary, subtype, description = "non_fall", "unknown_adl", "missing csv metadata"
        else:
            binary, subtype, description = meta["binary_label"], meta["non_fall_subtype"], meta["description"]
        labels[video_path.name] = "fall" if binary == "fall" else "adl"
        if binary == "fall":
            fall_count += 1
        else:
            non_fall_count += 1
            subtype_counts[subtype] += 1
            if subtype == "unknown_adl":
                unknown_count += 1
        video_id = f"{DATASET_NAME}/{video_path.name}"
        if video_id not in existing_ids:
            phase6_rows.append(
                {
                    "video_id": video_id,
                    "source_dataset": DATASET_NAME,
                    "license": "CC BY 4.0",
                    "split_group": f"{DATASET_NAME}_{video_path.stem}",
                    "binary_label": binary,
                    "non_fall_subtype": subtype if binary == "non_fall" else None,
                    "event_start_frame": 0,
                    "event_end_frame": None,
                    "usable_for_training": binary == "fall" or subtype != "unknown_adl",
                    "split": "unassigned",
                    "notes": f"GMDCSA CSV description: {description}",
                }
            )

    update_manifest(videos, labels)
    write_labels(phase6_rows)
    unknown_ratio = unknown_count / non_fall_count if non_fall_count else 0.0
    summary = {
        "dataset": DATASET_NAME,
        "videos": len(videos),
        "fall_count": fall_count,
        "non_fall_count": non_fall_count,
        "subtype_counts": dict(subtype_counts),
        "unknown_adl_count": unknown_count,
        "unknown_adl_ratio": round(unknown_ratio, 4),
        "meets_min_fall_target": fall_count >= min_fall,
        "meets_unknown_ratio_target": unknown_ratio < max_unknown_ratio,
    }
    out = ROOT / "evaluations" / "phase6d_gmdcsa_register_001.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def fetch_record() -> dict:
    with urlopen(ZENODO_RECORD_API, timeout=60) as response:
        return json.load(response)


def download_file(url: str, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        result = subprocess.run([curl, "-L", "--fail", "--retry", "3", "-o", str(tmp), url], check=False)
        if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(path)
            return
        if tmp.exists():
            tmp.unlink()
        print(f"curl failed ({result.returncode}); falling back to urllib")
    with urlopen(url, timeout=3600) as response, tmp.open("wb") as output:
        shutil.copyfileobj(response, output)
    tmp.replace(path)


def safe_filename(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_")


def canonical_video_name(src: Path) -> str:
    category = src.parent.name.lower()
    actor = src.parent.parent.name.lower().replace(" ", "_")
    return f"{actor}_{category}_{src.stem.lower()}{src.suffix.lower()}"


def build_label_index() -> dict[str, dict]:
    source_root = DATASETS_DIR / DATASET_NAME / "source"
    label_by_video = {}
    for csv_path in sorted(source_root.rglob("*.csv")):
        category = "fall" if csv_path.stem.lower() == "fall" else "adl"
        actor = csv_path.parent.name.lower().replace(" ", "_")
        with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                file_name = (row.get("File Name") or "").strip()
                if not file_name:
                    continue
                description = (row.get("Description") or "").strip()
                video_name = f"{actor}_{category}_{Path(file_name).stem.lower()}{Path(file_name).suffix.lower()}"
                if category == "fall":
                    binary, subtype = "fall", None
                else:
                    binary, subtype = "non_fall", infer_subtype(description)
                label_by_video[video_name] = {
                    "binary_label": binary,
                    "non_fall_subtype": subtype,
                    "description": description,
                }
    return label_by_video


def infer_label(path: Path) -> tuple[str, str | None]:
    text = " ".join(part.lower() for part in path.parts)
    name = path.stem.lower()
    if "fall" in text and "nonfall" not in text and "non_fall" not in text and "not_fall" not in text:
        return "fall", None
    for subtype, keywords in ADL_SUBTYPE_KEYWORDS.items():
        if any(keyword in name or keyword in text for keyword in keywords):
            return "non_fall", subtype
    return "non_fall", "unknown_adl"


def infer_subtype(description: str) -> str:
    text = description.lower()
    if "walking" in text or "walk" in text:
        return "walking"
    if "standing" in text or "stand" in text:
        return "standing"
    if "sitting" in text or "sit" in text or "chair" in text:
        if "sleep" in text or "bed" in text or "lying" in text:
            return "lying_down_normal"
        return "sitting"
    if "sleep" in text or "lying" in text or "bed" in text:
        return "lying_down_normal"
    if "pick" in text or "object" in text:
        return "picking_object"
    if "bend" in text:
        return "bending"
    if "squat" in text:
        return "squatting"
    return "unknown_adl"


def load_existing_labels() -> list[dict]:
    rows = []
    if not LABELS_PATH.exists():
        return rows
    with LABELS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_labels(rows: list[dict]) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def update_manifest(videos: list[Path], labels: dict[str, str]) -> None:
    manifest = {}
    if MANIFEST_PATH.exists():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest[DATASET_NAME] = {
        "available": True,
        "videos": [path.name for path in videos],
        "labels": labels,
        "failed_reason": None,
        "source_url": "https://zenodo.org/records/10889217",
        "notes": "GMDCSA-24 v2.1, Zenodo record 10889217, CC BY 4.0. Labels inferred from file paths and filenames.",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
