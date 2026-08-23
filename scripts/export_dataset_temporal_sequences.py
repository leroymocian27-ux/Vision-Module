from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASETS_DIR = ROOT / "datasets"
MANIFEST_PATH = DATASETS_DIR / "dataset_manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Phase 6 temporal vectors for videos in dataset_manifest.json.")
    parser.add_argument("--manifest", default=str(MANIFEST_PATH))
    parser.add_argument("--dataset", default="ur_fall")
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "temporal_sequences"))
    parser.add_argument("--labels", default=None, help="Optional Phase 6 labels JSONL.")
    parser.add_argument("--split", default=None, help="Optional split filter: train, val, test, or unassigned.")
    parser.add_argument(
        "--split-override",
        default=None,
        help="Override exported row split while still using label metadata such as subtype and event boundaries.",
    )
    parser.add_argument(
        "--label-filter",
        choices=["all", "fall", "non_fall"],
        default="all",
        help="Optional binary label filter for balanced pose-aware exports.",
    )
    parser.add_argument(
        "--video-id",
        action="append",
        default=None,
        help="Optional video id/name to export. Can be repeated, e.g. ur_fall/fall-01.mp4.",
    )
    parser.add_argument("--frame-stride", type=int, default=2)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--enable-pose", action="store_true")
    parser.add_argument("--device", default=None, help="Optional detector/pose device override, for example cpu or cuda:0.")
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    entry = manifest.get(args.dataset)
    if not entry or not entry.get("available"):
        raise SystemExit(f"dataset unavailable in manifest: {args.dataset}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    label_rows = load_label_rows(Path(args.labels), args.dataset) if args.labels else {}
    videos = select_videos(
        entry=entry,
        label_rows=label_rows,
        dataset=args.dataset,
        split=args.split,
        label_filter=args.label_filter,
        video_ids=args.video_id or [],
    )
    if args.limit:
        videos = videos[: args.limit]

    outputs = []
    for video_name in videos:
        label_row = label_rows.get(f"{args.dataset}/{video_name}") if label_rows else None
        output_path = output_dir / args.dataset / f"{Path(video_name).stem}.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = export_command_for_video(
            dataset=args.dataset,
            video_name=video_name,
            entry=entry,
            label_row=label_row,
            output_dir=output_dir,
            frame_stride=args.frame_stride,
            enable_pose=args.enable_pose,
            device=args.device,
            max_frames=args.max_frames,
            split_override=args.split_override,
        )
        print("Exporting", video_name, "->", output_path)
        subprocess.run(cmd, check=True)
        outputs.append(str(output_path))

    summary = {"dataset": args.dataset, "outputs": outputs}
    summary_path = output_dir / args.dataset / "export_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def load_label_rows(path: Path, dataset: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            video_id = row.get("video_id")
            if not video_id or not video_id.startswith(f"{dataset}/"):
                continue
            rows[video_id] = row
    return rows


def select_videos(
    *,
    entry: dict,
    label_rows: dict[str, dict],
    dataset: str,
    split: str | None,
    label_filter: str,
    video_ids: list[str],
) -> list[str]:
    requested = normalize_requested_video_ids(video_ids, dataset)
    if label_rows:
        videos = []
        for video_id, row in label_rows.items():
            video_name = Path(video_id.split("/", 1)[1]).name
            if requested and video_id not in requested and video_name not in requested:
                continue
            if not row.get("usable_for_training", True):
                continue
            if split is not None and row.get("split", "unassigned") != split:
                continue
            if label_filter != "all" and row.get("binary_label") != label_filter:
                continue
            videos.append(video_name)
        return videos

    labels = entry.get("labels", {}) if isinstance(entry.get("labels"), dict) else {}
    videos = []
    for item in entry.get("videos", []):
        video_name = Path(str(item)).name
        full_id = f"{dataset}/{video_name}"
        if requested and full_id not in requested and video_name not in requested:
            continue
        raw_label = labels.get(video_name, "adl")
        binary_label = "fall" if raw_label == "fall" else "non_fall"
        if label_filter != "all" and binary_label != label_filter:
            continue
        videos.append(video_name)
    return videos


def normalize_requested_video_ids(video_ids: list[str], dataset: str) -> set[str]:
    requested: set[str] = set()
    for item in video_ids:
        value = str(item).replace("\\", "/").strip()
        if not value:
            continue
        requested.add(value)
        if "/" not in value:
            requested.add(f"{dataset}/{Path(value).name}")
            requested.add(Path(value).name)
    return requested


def build_export_command(
    *,
    video_path: Path,
    output_path: Path,
    camera_id: str,
    video_id: str,
    label: str,
    frame_stride: int,
    enable_pose: bool,
    device: str | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "export_temporal_sequences.py"),
        "--video",
        str(video_path),
        "--output",
        str(output_path),
        "--camera-id",
        camera_id,
        "--video-id",
        video_id,
        "--label",
        label,
        "--frame-stride",
        str(frame_stride),
    ]
    if enable_pose:
        cmd += ["--enable-pose"]
    if device:
        cmd += ["--device", device]
    return cmd


def export_command_for_video(
    *,
    dataset: str,
    video_name: str,
    entry: dict,
    label_row: dict | None,
    output_dir: Path,
    frame_stride: int,
    enable_pose: bool,
    device: str | None,
    max_frames: int,
    split_override: str | None,
) -> list[str]:
    raw_label = entry.get("labels", {}).get(video_name, "adl")
    label = label_row.get("binary_label") if label_row else ("fall" if raw_label == "fall" else "non_fall")
    subtype = label_row.get("non_fall_subtype") if label_row else (None if label == "fall" else "unknown_adl")
    output_path = output_dir / dataset / f"{Path(video_name).stem}.jsonl"
    cmd = build_export_command(
        video_path=DATASETS_DIR / dataset / "videos" / video_name,
        output_path=output_path,
        camera_id=f"{dataset}_{Path(video_name).stem}",
        video_id=f"{dataset}/{video_name}",
        label=label,
        frame_stride=frame_stride,
        enable_pose=enable_pose,
        device=device,
    )
    if subtype:
        cmd += ["--non-fall-subtype", subtype]
    if label_row:
        if label_row.get("event_id"):
            cmd += ["--event-id", str(label_row["event_id"])]
        if label_row.get("event_start_frame") is not None:
            cmd += ["--event-start-frame", str(label_row["event_start_frame"])]
        if label_row.get("event_end_frame") is not None:
            cmd += ["--event-end-frame", str(label_row["event_end_frame"])]
        for arg_name, row_key in [
            ("--source-dataset", "source_dataset"),
            ("--license", "license"),
            ("--split-group", "split_group"),
            ("--split", "split"),
        ]:
            value = split_override if row_key == "split" and split_override is not None else label_row.get(row_key)
            if value is not None:
                cmd += [arg_name, str(value)]
        cmd += ["--usable-for-training", str(bool(label_row.get("usable_for_training", True))).lower()]
    if max_frames:
        cmd += ["--max-frames", str(max_frames)]
    return cmd


if __name__ == "__main__":
    raise SystemExit(main())
