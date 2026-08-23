from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import cv2


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"
MANIFEST_PATH = DATASETS_DIR / "dataset_manifest.json"

UR_BASE_URL = "https://fenix.ur.edu.pl/~mkepski/ds/data/"
UR_RGB_ARCHIVES = {
    "fall": [f"fall-{idx:02d}-cam0-rgb.zip" for idx in range(1, 31)],
    "adl": [f"adl-{idx:02d}-cam0-rgb.zip" for idx in range(1, 41)],
}


@dataclass
class DatasetManifestEntry:
    available: bool = False
    videos: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    failed_reason: str | None = None
    source_url: str | None = None
    notes: str | None = None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Download public fall datasets for Phase 5 evaluation.")
    parser.add_argument("--fall-count", type=int, default=5)
    parser.add_argument("--normal-count", type=int, default=5)
    args = parser.parse_args()

    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, DatasetManifestEntry] = {}

    manifest["ur_fall"] = download_ur_fall(fall_count=args.fall_count, normal_count=args.normal_count)
    manifest["le2i"] = DatasetManifestEntry(
        available=False,
        failed_reason="Le2i dataset is commonly distributed by request or via mirrors that are not stable public direct downloads.",
        source_url="https://www.google.com/search?q=Le2i+Fall+Detection+Dataset+download",
        notes="Manual request/download may be needed; not used by this automatic run.",
    )
    manifest["upfall"] = DatasetManifestEntry(
        available=False,
        failed_reason="UP-Fall RGB video direct download is not consistently exposed as simple public files; skipped after UR Fall succeeded.",
        source_url="https://sites.google.com/view/up-fall-detection-dataset",
        notes="Use as fallback if UR Fall becomes unavailable.",
    )

    write_manifest(manifest)
    print(f"Manifest written: {MANIFEST_PATH}")
    return 0 if any(entry.available for entry in manifest.values()) else 1


def download_ur_fall(fall_count: int, normal_count: int) -> DatasetManifestEntry:
    dataset_dir = DATASETS_DIR / "ur_fall"
    raw_dir = dataset_dir / "raw"
    videos_dir = dataset_dir / "videos"
    raw_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    videos: list[str] = []
    labels: dict[str, str] = {}
    failures: list[str] = []

    requested_archives = {
        "fall": UR_RGB_ARCHIVES["fall"][:fall_count],
        "adl": UR_RGB_ARCHIVES["adl"][:normal_count],
    }

    for label, archives in requested_archives.items():
        for archive_name in archives:
            url = f"{UR_BASE_URL}{archive_name}"
            zip_path = raw_dir / archive_name
            video_name = archive_name.replace("-cam0-rgb.zip", ".mp4")
            video_path = videos_dir / video_name
            try:
                if not zip_path.exists():
                    print(f"Downloading {url}")
                    download_file(url, zip_path)
                if not video_path.exists():
                    print(f"Converting {archive_name} -> {video_name}")
                    convert_zip_to_video(zip_path, video_path)
                if video_path.exists():
                    videos.append(video_name)
                    labels[video_name] = label
            except Exception as exc:
                failures.append(f"{archive_name}: {exc}")

    existing_videos = sorted(videos_dir.glob("*.mp4"))
    for video_path in existing_videos:
        if video_path.name not in labels:
            if video_path.name.startswith("fall-"):
                labels[video_path.name] = "fall"
            elif video_path.name.startswith("adl-"):
                labels[video_path.name] = "adl"
            else:
                continue
            videos.append(video_path.name)

    return DatasetManifestEntry(
        available=bool(videos),
        videos=sorted(set(videos)),
        labels=dict(sorted(labels.items())),
        failed_reason="; ".join(failures[:8]) if failures and not videos else None,
        source_url="https://fenix.ur.edu.pl/~mkepski/ds/uf.html",
        notes=f"Converted UR Fall cam0 RGB image sequences to mp4. failures={len(failures)}",
    )


def download_file(url: str, path: Path) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        result = subprocess.run(
            [curl, "-L", "--fail", "--retry", "3", "--connect-timeout", "30", "-o", str(tmp_path), url],
            check=False,
        )
        if result.returncode == 0 and tmp_path.exists() and tmp_path.stat().st_size > 0:
            tmp_path.replace(path)
            return
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(f"curl failed with exit code {result.returncode}")

    try:
        with urlopen(url, timeout=60) as response, tmp_path.open("wb") as output:
            shutil.copyfileobj(response, output)
        tmp_path.replace(path)
    except (HTTPError, URLError):
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def convert_zip_to_video(zip_path: Path, video_path: Path) -> None:
    frames_dir = zip_path.with_suffix("")
    if not frames_dir.exists():
        frames_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(frames_dir)

    frame_paths = sorted(
        path
        for path in frames_dir.rglob("*")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
    )
    if not frame_paths:
        raise RuntimeError(f"no image frames found in {zip_path.name}")

    first = cv2.imread(str(frame_paths[0]))
    if first is None:
        raise RuntimeError(f"could not decode first frame: {frame_paths[0]}")

    height, width = first.shape[:2]
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        25.0,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not create video: {video_path}")

    try:
        for frame_path in frame_paths:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                continue
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
    finally:
        writer.release()


def write_manifest(manifest: dict[str, DatasetManifestEntry]) -> None:
    payload = {name: asdict(entry) for name, entry in manifest.items()}
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
