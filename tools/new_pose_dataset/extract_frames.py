from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np


ACTION_CATEGORY = {
    "no_person": "negative",
    "no_person_retake": "negative",
    "standing_front": "static",
    "standing_side": "static",
    "standing_back": "static",
    "sitting_normal": "static",
    "sitting_normal_retake": "static",
    "sitting_side": "static",
    "sitting_side_retake": "static",
    "lying_side": "static",
    "lying_back": "static",
    "lying_back_retake": "static",
    "lying_prone": "static",
    "lying_prone_retake": "static",
    "fallen_hold": "static",
    "walking_slow": "dynamic",
    "bending_pickup": "dynamic",
    "bending_pickup_retake": "dynamic",
    "squat": "dynamic",
    "squat_retake": "dynamic",
    "recovery_standing": "dynamic",
    "recovery_standing_retake": "dynamic",
    "fall_simulated_side": "fall_simulated",
    "fall_simulated_back": "fall_simulated",
    "fall_simulated_back_retake": "fall_simulated",
}

STRATEGY_TARGETS = {
    "sparse": {
        "negative": 12,
        "static": 20,
        "dynamic": 36,
        "fall_simulated": 70,
    },
    "balanced": {
        "negative": 16,
        "static": 30,
        "dynamic": 50,
        "fall_simulated": 90,
    },
    "dense": {
        "negative": 20,
        "static": 40,
        "dynamic": 60,
        "fall_simulated": 100,
    },
}

HARD_CASE_ACTIONS = {
    "walking_slow",
    "bending_pickup",
    "bending_pickup_retake",
    "squat",
    "squat_retake",
    "recovery_standing",
    "recovery_standing_retake",
    "fall_simulated_side",
    "fall_simulated_back",
    "fall_simulated_back_retake",
}

VAL_ACTIONS = {
    "standing_back",
    "sitting_side",
    "sitting_side_retake",
    "lying_prone",
    "lying_prone_retake",
    "fall_simulated_back",
    "fall_simulated_back_retake",
    "fallen_hold",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def repo_relative(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def select_uniform_indices(start: int, end: int, count: int) -> list[int]:
    if end <= start:
        return [start]
    available = end - start
    count = max(1, min(count, available))
    if count == 1:
        return [start + available // 2]
    values = np.linspace(start, end - 1, num=count, dtype=int).tolist()
    deduped: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    cursor = start
    while len(deduped) < count and cursor < end:
        if cursor not in seen:
            deduped.append(cursor)
            seen.add(cursor)
        cursor += 1
    return sorted(deduped)


def select_weighted_segment_indices(total_frames: int, segment_specs: list[tuple[float, float, int]]) -> list[int]:
    selected: list[int] = []
    for start_ratio, end_ratio, count in segment_specs:
        start = min(total_frames - 1, max(0, int(math.floor(total_frames * start_ratio))))
        end = min(total_frames, max(start + 1, int(math.ceil(total_frames * end_ratio))))
        selected.extend(select_uniform_indices(start, end, count))
    seen: set[int] = set()
    deduped = []
    for index in sorted(selected):
        if index in seen:
            continue
        deduped.append(index)
        seen.add(index)
    return deduped


def get_target_count(action_label: str, strategy: str, total_frames: int) -> int:
    category = ACTION_CATEGORY.get(action_label, "static")
    base_count = STRATEGY_TARGETS[strategy][category]
    return max(1, min(base_count, total_frames))


def estimate_action_phase(action_label: str, progress: float) -> tuple[str, bool]:
    if action_label in {"no_person", "no_person_retake"}:
        return "empty_scene", False
    if action_label in {
        "standing_front",
        "standing_side",
        "standing_back",
        "sitting_normal",
        "sitting_normal_retake",
        "sitting_side",
        "sitting_side_retake",
        "lying_side",
        "lying_back",
        "lying_back_retake",
        "lying_prone",
        "lying_prone_retake",
        "fallen_hold",
    }:
        return "static_pose", False
    if action_label in {"walking_slow", "bending_pickup", "bending_pickup_retake", "squat", "squat_retake"}:
        if progress < 0.25:
            return "motion_start", True
        if progress < 0.75:
            return "motion_mid", True
        return "motion_end", True
    if action_label in {"recovery_standing", "recovery_standing_retake"}:
        if progress < 0.2:
            return "low_posture_start", True
        if progress < 0.7:
            return "recovery_transition", True
        return "upright_recovery", True
    if action_label in {"fall_simulated_side", "fall_simulated_back", "fall_simulated_back_retake"}:
        if progress < 0.15:
            return "pre_fall_standing", True
        if progress < 0.5:
            return "falling_transition", True
        if progress < 0.85:
            return "fallen_hold", True
        return "recovery_if_present", True
    return "unknown", False


def choose_indices(action_label: str, strategy: str, total_frames: int) -> list[int]:
    count = get_target_count(action_label, strategy, total_frames)
    if action_label in {"no_person", "no_person_retake"}:
        return select_uniform_indices(0, total_frames, count)
    if action_label in {
        "standing_front",
        "standing_side",
        "standing_back",
        "sitting_normal",
        "sitting_normal_retake",
        "sitting_side",
        "sitting_side_retake",
        "lying_side",
        "lying_back",
        "lying_back_retake",
        "lying_prone",
        "lying_prone_retake",
        "fallen_hold",
    }:
        return select_uniform_indices(0, total_frames, count)
    if action_label in {
        "walking_slow",
        "bending_pickup",
        "bending_pickup_retake",
        "squat",
        "squat_retake",
        "recovery_standing",
        "recovery_standing_retake",
    }:
        start_count = max(1, round(count * 0.25))
        mid_count = max(1, round(count * 0.5))
        end_count = max(1, count - start_count - mid_count)
        return select_weighted_segment_indices(
            total_frames,
            [
                (0.0, 0.25, start_count),
                (0.25, 0.75, mid_count),
                (0.75, 1.0, end_count),
            ],
        )
    if action_label in {"fall_simulated_side", "fall_simulated_back", "fall_simulated_back_retake"}:
        pre_count = max(1, round(count * 0.15))
        fall_count = max(1, round(count * 0.35))
        hold_count = max(1, count - pre_count - fall_count)
        return select_weighted_segment_indices(
            total_frames,
            [
                (0.0, 0.15, pre_count),
                (0.15, 0.5, fall_count),
                (0.5, 1.0, hold_count),
            ],
        )
    return select_uniform_indices(0, total_frames, count)


def compute_frame_quality(frame: np.ndarray) -> tuple[dict[str, Any], list[str], bool]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    brightness_mean = float(np.mean(gray))
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    black_frame = brightness_mean <= 5.0
    quality_warnings: list[str] = []
    excluded = False
    if black_frame:
        quality_warnings.append("black_frame")
        excluded = True
    if brightness_mean < 35.0 and not black_frame:
        quality_warnings.append("low_brightness")
    if blur_score < 20.0:
        quality_warnings.append("blurred")
    if width < 320 or height < 180:
        quality_warnings.append("bad_resolution")
    payload = {
        "read_ok": True,
        "width": int(width),
        "height": int(height),
        "blur_score": round(blur_score, 4),
        "brightness_mean": round(brightness_mean, 4),
        "black_frame": bool(black_frame),
    }
    return payload, quality_warnings, excluded


def build_session_report(
    *,
    session_id: str,
    action_label: str,
    strategy: str,
    selected_frames: int,
    extracted_frames: int,
    excluded_frames: int,
    warnings: Counter[str],
    needs_review: bool,
    output_dir: Path,
) -> str:
    lines = [
        "# Frame QA Report",
        "",
        f"- session_id: `{session_id}`",
        f"- action_label: `{action_label}`",
        f"- strategy: `{strategy}`",
        f"- selected_frames: `{selected_frames}`",
        f"- extracted_frames: `{extracted_frames}`",
        f"- excluded_frames: `{excluded_frames}`",
        f"- session_need_review: `{needs_review}`",
        f"- images_dir: `{output_dir.as_posix()}`",
        "",
        "## Quality Warnings",
        "",
    ]
    if warnings:
        for name, count in sorted(warnings.items()):
            lines.append(f"- `{name}`: `{count}`")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def process_session(
    *,
    session_dir: Path,
    output_root: Path,
    strategy: str,
    repo_root: Path,
    dry_run: bool,
    overwrite: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    metadata_path = session_dir / "metadata.json"
    metadata = read_json(metadata_path)
    session_id = str(metadata.get("session_id") or session_dir.name)
    action_label = str(metadata.get("primary_action") or (metadata.get("action_labels") or ["unknown"])[0])
    video_path = session_dir / "video.mp4"
    status_path = session_dir / "status_samples.jsonl"
    integration_path = session_dir / "integration_latest_samples.jsonl"

    output_session_dir = output_root / session_id
    images_dir = output_session_dir / "images"
    manifest_path = output_session_dir / "frame_manifest.jsonl"
    qa_path = output_session_dir / "frame_qa_report.md"
    if output_session_dir.exists() and not overwrite and not dry_run:
        raise FileExistsError(f"output already exists: {output_session_dir}")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"failed_to_open_video: {video_path}")
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = float(metadata.get("fps") or 4.0)
    if frame_count <= 0:
        frame_count = max(1, int(round(float(metadata.get("duration_sec") or 1.0) * fps)))

    selected_indices = choose_indices(action_label, strategy, frame_count)
    progress_divisor = max(1, frame_count - 1)
    manifests: list[dict[str, Any]] = []
    warnings = Counter()
    excluded_frames = 0

    if not dry_run:
        output_session_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)
        if manifest_path.exists():
            manifest_path.unlink()

    for frame_index in selected_indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            excluded_frames += 1
            continue

        frame_quality, quality_warnings, excluded = compute_frame_quality(frame)
        warnings.update(quality_warnings)
        if excluded:
            excluded_frames += 1
            continue

        progress = frame_index / progress_divisor
        action_phase, auto_estimated = estimate_action_phase(action_label, progress)
        negative_sample = action_label in {"no_person", "no_person_retake"}
        needs_pose_annotation = not negative_sample
        split_hint = "eval" if negative_sample else ("val" if action_label in VAL_ACTIONS else "train")
        hard_case_candidate = action_label in HARD_CASE_ACTIONS
        selection_reason = f"{strategy}_{ACTION_CATEGORY.get(action_label, 'static')}_sampling"
        if auto_estimated:
            selection_reason = f"{selection_reason}_phase_estimated"
        annotation_priority = (
            "low"
            if negative_sample
            else "high"
            if action_phase == "falling_transition" or hard_case_candidate
            else "normal"
        )
        image_name = f"frame_{frame_index:06d}.jpg"
        image_path = images_dir / image_name
        if not dry_run:
            cv2.imwrite(str(image_path), frame)
        manifest = {
            "schema_version": "new_pose_frame_manifest_v1",
            "camera_id": str(metadata.get("camera_id") or "camera_01"),
            "session_id": session_id,
            "raw_video_path": repo_relative(video_path, repo_root),
            "image_path": repo_relative(image_path, repo_root),
            "frame_index": int(frame_index),
            "timestamp_sec": round(frame_index / max(fps, 0.0001), 4),
            "action_label": action_label,
            "action_phase": action_phase,
            "phase_auto_estimated": auto_estimated,
            "negative_sample": negative_sample,
            "needs_pose_annotation": needs_pose_annotation,
            "hard_case_candidate": hard_case_candidate,
            "split_hint": split_hint,
            "person_count_hint": int(metadata.get("person_count") or 0),
            "pose_provider_at_collection": str(metadata.get("pose_provider") or "disabled_placeholder"),
            "pose_enabled_at_collection": bool(metadata.get("pose_enabled", False)),
            "source_metadata_path": repo_relative(metadata_path, repo_root),
            "source_status_samples_path": repo_relative(status_path, repo_root),
            "source_integration_samples_path": repo_relative(integration_path, repo_root),
            "frame_quality": frame_quality,
            "quality_warnings": quality_warnings,
            "selection_reason": selection_reason,
            "annotation_priority": annotation_priority,
            "notes": "",
        }
        manifests.append(manifest)
        if not dry_run:
            append_jsonl(manifest_path, manifest)

    capture.release()
    needs_review = excluded_frames > 0 or warnings.get("bad_resolution", 0) > 0
    if not dry_run:
        qa_path.write_text(
            build_session_report(
                session_id=session_id,
                action_label=action_label,
                strategy=strategy,
                selected_frames=len(selected_indices),
                extracted_frames=len(manifests),
                excluded_frames=excluded_frames,
                warnings=warnings,
                needs_review=needs_review,
                output_dir=images_dir,
            ),
            encoding="utf-8",
        )
    summary = {
        "session_id": session_id,
        "action_label": action_label,
        "target_frames": len(selected_indices),
        "extracted_frames": len(manifests),
        "excluded_frames": excluded_frames,
        "quality_warnings": dict(warnings),
        "needs_review": needs_review,
    }
    return manifests, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract balanced frame samples from raw new-pose videos.")
    parser.add_argument("--raw-root", default="datasets/new_pose_raw", help="Root directory for raw dataset.")
    parser.add_argument("--frames-root", default="datasets/new_pose_frames", help="Root directory for extracted frames.")
    parser.add_argument("--camera-id", default="camera_01", help="Camera id to process.")
    parser.add_argument("--session-id", action="append", default=[], help="Specific session id to process. Repeatable.")
    parser.add_argument("--session-glob", default="", help="Optional glob pattern such as '*retake_b*'.")
    parser.add_argument("--all", action="store_true", help="Process all sessions under the selected camera.")
    parser.add_argument(
        "--strategy",
        choices=sorted(STRATEGY_TARGETS.keys()),
        default="balanced",
        help="Extraction density strategy.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview extraction plan without writing files.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing extracted frame outputs.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.all and not args.session_id and not args.session_glob:
        parser.error("use --all or provide --session-id / --session-glob")

    repo_root = Path(__file__).resolve().parents[2]
    raw_camera_root = (repo_root / args.raw_root / args.camera_id).resolve()
    frames_camera_root = (repo_root / args.frames_root / args.camera_id).resolve()
    if not raw_camera_root.exists():
        raise FileNotFoundError(f"missing raw camera root: {raw_camera_root}")

    if args.all:
        session_dirs = sorted(path for path in raw_camera_root.iterdir() if path.is_dir())
    elif args.session_glob:
        session_dirs = sorted(path for path in raw_camera_root.glob(args.session_glob) if path.is_dir())
    else:
        session_dirs = [raw_camera_root / session_id for session_id in args.session_id]

    summaries = []
    all_manifests: list[dict[str, Any]] = []
    for session_dir in session_dirs:
        manifests, summary = process_session(
            session_dir=session_dir,
            output_root=frames_camera_root,
            strategy=args.strategy,
            repo_root=repo_root,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
        )
        summaries.append(summary)
        all_manifests.extend(manifests)

    manifest_all_path = frames_camera_root / "frame_manifest_all.jsonl"
    if not args.dry_run:
        frames_camera_root.mkdir(parents=True, exist_ok=True)
        if manifest_all_path.exists():
            manifest_all_path.unlink()
        combined_manifests: list[dict[str, Any]] = []
        for session_manifest in sorted(frames_camera_root.glob("*/frame_manifest.jsonl")):
            combined_manifests.extend(read_jsonl(session_manifest))
        for item in combined_manifests:
            append_jsonl(manifest_all_path, item)
        all_manifests = combined_manifests

    payload = {
        "camera_id": args.camera_id,
        "strategy": args.strategy,
        "dry_run": args.dry_run,
        "sessions": summaries,
        "total_frames": len(all_manifests),
        "manifest_all_path": repo_relative(manifest_all_path, repo_root),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
