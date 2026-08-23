from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2


ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "datasets" / "fall_hint_v2_raw"
FINAL_ROOT = ROOT / "datasets" / "fall_hint_v2"

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}

CLASS_NAMES = [
    "falling",
    "fallen",
    "lying",
    "sitting",
    "bending",
    "kneeling",
    "standing",
]


@dataclass(frozen=True)
class CandidateVideo:
    path: Path
    group: str
    scene: str
    source_dataset: str
    video_key: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a low-duplication fall_hint_v2 review batch from many unused videos."
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--frames-per-video", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--include-used", action="store_true")
    parser.add_argument("--reuse-fill", action="store_true")
    parser.add_argument("--seed", type=int, default=20260701)
    args = parser.parse_args()

    batch_dir = RAW_ROOT / args.batch_id
    if batch_dir.exists() and not args.overwrite:
        raise SystemExit(f"{batch_dir} already exists; pass --overwrite only if you intend to replace it")
    if batch_dir.exists() and args.overwrite:
        remove_batch_contents(batch_dir)

    create_structure(batch_dir)
    write_data_yaml(FINAL_ROOT / "data.yaml")

    used_paths = read_used_source_videos()
    if args.include_used:
        candidates = collect_candidates(used_paths=set())
        selected = select_diverse_candidates(candidates, count=args.count, seed=args.seed)
    elif args.reuse_fill:
        unused_candidates = collect_candidates(used_paths=used_paths)
        reused_candidates = [
            item for item in collect_candidates(used_paths=set()) if item.path.resolve() in used_paths
        ]
        selected = select_with_reuse_fill(
            unused_candidates=unused_candidates,
            reused_candidates=reused_candidates,
            count=args.count,
            seed=args.seed,
        )
        candidates = unused_candidates + reused_candidates
    else:
        candidates = collect_candidates(used_paths=used_paths)
        selected = select_diverse_candidates(candidates, count=args.count, seed=args.seed)
    rows = extract_frames(
        selected,
        frame_dir=batch_dir / "frames",
        frames_per_video=max(args.frames_per_video, 1),
        target_count=args.count,
        seed=args.seed,
    )

    write_source_videos(batch_dir / "meta" / "source_videos.csv", selected)
    write_frame_manifest(batch_dir / "meta" / "frame_manifest.csv", rows)
    write_labeling_guide(batch_dir / "meta" / "labeling_guide.md")
    write_summary(batch_dir / "meta" / "prepare_summary.json", selected, rows, len(candidates))

    print(f"[OK] batch_dir={batch_dir}")
    print(f"[OK] candidate_videos={len(candidates)}")
    print(f"[OK] selected_videos={len(selected)}")
    print(f"[OK] extracted_frames={len(rows)}")
    print("[NEXT] Run prelabeling, then human review in the local labeler.")
    return 0


def remove_batch_contents(batch_dir: Path) -> None:
    for child in batch_dir.iterdir():
        if child.is_dir():
            for nested in sorted(child.rglob("*"), reverse=True):
                if nested.is_file():
                    nested.unlink()
                elif nested.is_dir():
                    nested.rmdir()
            child.rmdir()
        else:
            child.unlink()


def create_structure(batch_dir: Path) -> None:
    for path in [
        batch_dir / "frames",
        batch_dir / "prelabels",
        batch_dir / "human_review" / "labels",
        batch_dir / "human_review" / "meta",
        batch_dir / "meta",
        FINAL_ROOT / "images" / "train",
        FINAL_ROOT / "images" / "val",
        FINAL_ROOT / "images" / "test",
        FINAL_ROOT / "labels" / "train",
        FINAL_ROOT / "labels" / "val",
        FINAL_ROOT / "labels" / "test",
        FINAL_ROOT / "meta",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def read_used_source_videos() -> set[Path]:
    used: set[Path] = set()
    for manifest in RAW_ROOT.glob("batch_*/meta/frame_manifest.csv"):
        with manifest.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                source_video = row.get("source_video")
                if source_video:
                    try:
                        used.add(Path(source_video).resolve())
                    except OSError:
                        continue
    return used


def collect_candidates(*, used_paths: set[Path]) -> list[CandidateVideo]:
    roots = [ROOT / "datasets", ROOT / "video"]
    candidates: list[CandidateVideo] = []
    for scan_root in roots:
        if not scan_root.exists():
            continue
        for path in scan_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            resolved = path.resolve()
            if resolved in used_paths:
                continue
            if "fall_hint_v2_raw" in {part.lower() for part in resolved.parts}:
                continue
            group, scene = infer_group_scene(path)
            candidates.append(
                CandidateVideo(
                    path=resolved,
                    group=group,
                    scene=scene,
                    source_dataset=infer_source_dataset(path),
                    video_key=stable_video_key(path),
                )
            )
    return sorted(candidates, key=lambda item: (item.group, item.source_dataset, str(item.path)))


def infer_group_scene(path: Path) -> tuple[str, str]:
    text = str(path).lower().replace("/", "\\")
    name = path.stem.lower()
    if "no_person" in text or "empty" in text:
        return "no_person", "no_person"
    if "sitting" in text or "sit" in name:
        return "hardneg", "sitting"
    if "bending" in text or "bend" in name or "pickup" in text:
        return "hardneg", "bending"
    if "squat" in text or "kneel" in text or "crouch" in text:
        return "hardneg", "kneeling"
    if "lying" in text or "lie" in name:
        return "lying", "lying"
    if "fall" in text or "chute" in text:
        return "fall", "fall"
    if "adl" in text:
        return "hardneg", "adl_unknown"
    return "hardneg", "unknown"


def infer_source_dataset(path: Path) -> str:
    rel = path.resolve()
    try:
        parts = rel.relative_to(ROOT).parts
    except ValueError:
        return "external"
    if len(parts) >= 2 and parts[0] == "datasets":
        return parts[1]
    return parts[0] if parts else "external"


def stable_video_key(path: Path) -> str:
    rel = str(path.resolve())
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    stem = "".join(ch if ch.isalnum() else "_" for ch in path.stem.lower()).strip("_")
    return f"{stem}_{digest}"


def select_diverse_candidates(
    candidates: list[CandidateVideo],
    *,
    count: int,
    seed: int,
) -> list[CandidateVideo]:
    buckets: dict[str, list[CandidateVideo]] = {
        "fall": [],
        "hardneg": [],
        "lying": [],
        "no_person": [],
    }
    for item in deterministic_shuffle(candidates, seed=seed):
        buckets.setdefault(item.group, []).append(item)

    targets = {
        "hardneg": int(count * 0.45),
        "fall": int(count * 0.35),
        "lying": int(count * 0.15),
        "no_person": count,
    }
    targets["no_person"] = count - targets["hardneg"] - targets["fall"] - targets["lying"]

    selected: list[CandidateVideo] = []
    for group in ["hardneg", "fall", "lying", "no_person"]:
        selected.extend(buckets.get(group, [])[: max(targets.get(group, 0), 0)])

    if len(selected) < count:
        selected_paths = {item.path for item in selected}
        for item in deterministic_shuffle(candidates, seed=seed + 17):
            if item.path not in selected_paths:
                selected.append(item)
                selected_paths.add(item.path)
            if len(selected) >= count:
                break

    return selected[:count]


def select_with_reuse_fill(
    *,
    unused_candidates: list[CandidateVideo],
    reused_candidates: list[CandidateVideo],
    count: int,
    seed: int,
) -> list[CandidateVideo]:
    selected = select_diverse_candidates(unused_candidates, count=count, seed=seed)
    if len(selected) >= count:
        return selected[:count]

    selected_paths = {item.path for item in selected}
    fill_candidates = [item for item in reused_candidates if item.path not in selected_paths]
    fill = select_diverse_candidates(fill_candidates, count=count - len(selected), seed=seed + 101)
    selected.extend(fill)
    return selected[:count]


def deterministic_shuffle(items: list[CandidateVideo], *, seed: int) -> list[CandidateVideo]:
    return sorted(
        items,
        key=lambda item: hashlib.sha1(f"{seed}|{item.path}".encode("utf-8")).hexdigest(),
    )


def extract_frames(
    selected: list[CandidateVideo],
    *,
    frame_dir: Path,
    frames_per_video: int,
    target_count: int,
    seed: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in selected:
        if len(rows) >= target_count:
            break
        cap = cv2.VideoCapture(str(item.path))
        if not cap.isOpened():
            print(f"[SKIP] could not open {item.path}")
            continue

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 0 or total_frames <= 0:
            cap.release()
            print(f"[SKIP] bad video metadata {item.path}")
            continue

        frame_indices = choose_frame_indices(total_frames, frames_per_video, seed, item.path)
        saved = 0
        for frame_index in frame_indices:
            if len(rows) >= target_count:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if not ok:
                continue
            out_name = f"{item.video_key}_{saved:06d}.jpg"
            out_path = frame_dir / out_name
            cv2.imwrite(str(out_path), frame)
            rows.append(
                {
                    "image": out_name,
                    "image_path": str(out_path.relative_to(ROOT)).replace("\\", "/"),
                    "video_id": item.video_key,
                    "source_video": str(item.path),
                    "group": item.group,
                    "scene": item.scene,
                    "source_dataset": item.source_dataset,
                    "license": "manual_confirm_required",
                    "source_frame_index": frame_index,
                    "timestamp_ms": int(round(frame_index * 1000 / fps)),
                    "target_fps": 0,
                    "start_ratio": 0.0,
                    "end_ratio": 1.0,
                    "annotation_status": "needs_human_review",
                    "sampling_policy": f"diverse_unused_videos_{frames_per_video}_frame_per_video",
                }
            )
            saved += 1
        cap.release()
        print(f"[OK] {item.video_key}: saved={saved} total_frames={total_frames}")
    return rows


def choose_frame_indices(total_frames: int, frames_per_video: int, seed: int, path: Path) -> list[int]:
    if frames_per_video <= 1:
        ratio = stable_ratio(seed, path)
        # Avoid exact start/end; those often contain blank lead-in or cut frames.
        return [min(total_frames - 1, max(0, int(total_frames * (0.20 + ratio * 0.60))))]

    indices: list[int] = []
    for index in range(frames_per_video):
        ratio = (index + 1) / (frames_per_video + 1)
        indices.append(min(total_frames - 1, max(0, int(total_frames * ratio))))
    return indices


def stable_ratio(seed: int, path: Path) -> float:
    digest = hashlib.sha1(f"{seed}|{path}".encode("utf-8")).hexdigest()[:8]
    return int(digest, 16) / 0xFFFFFFFF


def write_source_videos(path: Path, selected: list[CandidateVideo]) -> None:
    rows = [
        {
            "video_id": item.video_key,
            "path": str(item.path),
            "group": item.group,
            "scene": item.scene,
            "source_dataset": item.source_dataset,
            "privacy_ok": "manual_confirm_required",
            "note": "Selected by diverse unused-video sampler; human label is authoritative.",
        }
        for item in selected
    ]
    write_csv(path, rows)


def write_frame_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    write_csv(path, rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_data_yaml(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = "\n".join(f"  {index}: {name}" for index, name in enumerate(CLASS_NAMES))
    path.write_text(
        "\n".join(
            [
                f"path: {FINAL_ROOT.as_posix()}",
                "train: images/train",
                "val: images/val",
                "test: images/test",
                "",
                "names:",
                names,
                "",
            ]
        ),
        encoding="utf-8",
    )


def write_labeling_guide(path: Path) -> None:
    path.write_text(
        """# Low-Duplication fall_hint_v2 Human Labeling Guide

This batch intentionally uses many different source videos. Prelabels are only drafts.

Labels:

0. falling - active loss of balance or fast descent
1. fallen - abnormal fall result, body down after a fall
2. lying - normal lying/reclining, not necessarily a fall
3. sitting - seated on chair/bed/floor
4. bending - standing legs with upper body bent forward
5. kneeling - squat/kneel/low posture without fall impact
6. standing - standing or walking upright

Rules:

- Draw every visible person in the frame.
- Correct both class and bbox.
- If a public/video frame is not clear enough to judge, remove the box and do not use it later.
- Empty/no-person frames must be saved with empty labels.
- Human labels override source filename guesses.
""",
        encoding="utf-8",
    )


def write_summary(
    path: Path,
    selected: list[CandidateVideo],
    frame_rows: list[dict[str, Any]],
    candidate_count: int,
) -> None:
    scene_counts: dict[str, int] = {}
    dataset_counts: dict[str, int] = {}
    for row in frame_rows:
        scene_counts[str(row["scene"])] = scene_counts.get(str(row["scene"]), 0) + 1
        dataset_counts[str(row["source_dataset"])] = dataset_counts.get(str(row["source_dataset"]), 0) + 1
    payload = {
        "class_names": CLASS_NAMES,
        "candidate_video_count": candidate_count,
        "selected_video_count": len(selected),
        "frame_count": len(frame_rows),
        "unique_source_video_count": len({row["source_video"] for row in frame_rows}),
        "scene_frame_counts": scene_counts,
        "dataset_frame_counts": dataset_counts,
        "sampling_policy": "Prefer unused videos; default one frame per video; source filename is not trusted as final label.",
        "requires_human_stop": True,
        "next_step": "Run prelabeling, then perform human annotation/review before training.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
