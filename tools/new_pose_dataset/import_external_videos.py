from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sanitize_token(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "external"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gather_video_info(video_path: Path) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"failed_to_open_video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_sec = 0.0
    if fps > 0 and frame_count > 0:
        duration_sec = frame_count / fps
    capture.release()
    return {
        "fps": round(fps, 6),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_sec": round(duration_sec, 3),
    }


def build_contact_sheet(video_path: Path, output_path: Path, columns: int = 4, sample_count: int = 8) -> None:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"failed_to_open_video: {video_path}")
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
    indices = sorted(set(int((total_frames - 1) * idx / max(sample_count - 1, 1)) for idx in range(sample_count)))
    frames: list[np.ndarray] = []
    for frame_index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            continue
        height, width = frame.shape[:2]
        scale = min(1.0, 320 / max(width, 1))
        if scale != 1.0:
            frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
        label = f"{video_path.name} | frame {frame_index}"
        cv2.putText(frame, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(frame, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA)
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError(f"no_preview_frames: {video_path}")

    rows: list[np.ndarray] = []
    row_frames: list[np.ndarray] = []
    for frame in frames:
        row_frames.append(frame)
        if len(row_frames) == columns:
            rows.append(_concat_row(row_frames))
            row_frames = []
    if row_frames:
        rows.append(_concat_row(row_frames))
    sheet = cv2.vconcat(rows) if len(rows) > 1 else rows[0]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), sheet)


def _concat_row(frames: list[np.ndarray]) -> np.ndarray:
    max_height = max(frame.shape[0] for frame in frames)
    padded: list[np.ndarray] = []
    for frame in frames:
        height, width = frame.shape[:2]
        canvas = np.full((max_height, width, 3), 255, dtype=np.uint8)
        canvas[:height, :width] = frame
        padded.append(canvas)
    return cv2.hconcat(padded)


def build_notes(args: argparse.Namespace, source_path: Path) -> str:
    phases = "\n".join(f"- {phase}" for phase in args.visual_phase) if args.visual_phase else "- pending_manual_review"
    return "\n".join(
        [
            "# External MP4 Intake Notes",
            "",
            f"- source_video: `{source_path}`",
            f"- primary_hypothesis: `{args.action_hypothesis}`",
            f"- standard_action_candidate: `{args.standard_action_candidate}`",
            f"- recommended_split: `{args.recommended_split}`",
            f"- ready_for_frame_extraction: `{args.ready_for_frame_extraction}`",
            f"- review_decision: `{args.review_decision}`",
            f"- operator_notes: `{args.operator_notes}`",
            "",
            "## Visual Phases",
            "",
            phases,
            "",
        ]
    ) + "\n"


def build_qa(args: argparse.Namespace, video_info: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# External MP4 Intake QA",
            "",
            "- import_status: `IMPORTED`",
            f"- review_decision: `{args.review_decision}`",
            f"- recommended_split: `{args.recommended_split}`",
            f"- ready_for_frame_extraction: `{args.ready_for_frame_extraction}`",
            f"- standard_action_candidate: `{args.standard_action_candidate}`",
            f"- action_hypothesis: `{args.action_hypothesis}`",
            f"- duration_sec: `{video_info['duration_sec']}`",
            f"- resolution: `{video_info['width']}x{video_info['height']}`",
            f"- fps: `{video_info['fps']}`",
            "",
            "This session is an external import for manual triage.",
            "It is not automatically part of `datasets/new_pose_raw` curated training input.",
            "",
        ]
    ) + "\n"


def build_metadata(
    *,
    session_id: str,
    source_path: Path,
    video_info: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "schema_version": "new_pose_external_import_v1",
        "session_id": session_id,
        "camera_id": args.camera_id,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "import_mode": "reference" if not args.copy_video else "copy",
        "source_video_path": str(source_path),
        "source_video_name": source_path.name,
        "source_video_sha256": sha256_file(source_path),
        "action_hypothesis": args.action_hypothesis,
        "standard_action_candidate": args.standard_action_candidate,
        "visual_phases": args.visual_phase,
        "review_decision": args.review_decision,
        "recommended_split": args.recommended_split,
        "ready_for_frame_extraction": args.ready_for_frame_extraction,
        "operator_notes": args.operator_notes,
        "collection_context": args.collection_context,
        "recorded_by": args.recorded_by,
        "pose_provider_at_collection": "disabled_placeholder",
        "pose_enabled_at_collection": False,
        "usable_for_training": False,
        "usable_for_eval": False,
        "needs_manual_segmentation": args.recommended_split != "direct_reuse",
        "video_info": video_info,
    }


def import_video(args: argparse.Namespace) -> Path:
    source_path = Path(args.source_video).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"missing source video: {source_path}")

    root = (repo_root() / args.root / args.camera_id).resolve()
    timestamp = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"session_{timestamp}_{sanitize_token(args.action_hypothesis)}"
    if args.session_suffix:
        session_id = f"{session_id}_{sanitize_token(args.session_suffix)}"
    session_dir = root / session_id
    session_dir.mkdir(parents=True, exist_ok=False)

    video_info = gather_video_info(source_path)
    metadata = build_metadata(session_id=session_id, source_path=source_path, video_info=video_info, args=args)

    (session_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (session_dir / "source_video.txt").write_text(str(source_path) + "\n", encoding="utf-8")
    (session_dir / "notes.md").write_text(build_notes(args, source_path), encoding="utf-8")
    (session_dir / "qa_report.md").write_text(build_qa(args, video_info), encoding="utf-8")
    build_contact_sheet(source_path, session_dir / "contact_sheet.jpg")

    if args.copy_video:
        shutil.copy2(source_path, session_dir / "video.mp4")

    return session_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register an external MP4 as a manually triaged new-pose import session.")
    parser.add_argument("--camera-id", required=True, help="Camera id such as camera_01.")
    parser.add_argument("--source-video", required=True, help="Absolute or relative path to the MP4 file.")
    parser.add_argument("--action-hypothesis", required=True, help="Human-readable action hypothesis, e.g. standing_front or mixed_floor_sit.")
    parser.add_argument("--standard-action-candidate", default="", help="Optional standardized action label candidate.")
    parser.add_argument("--visual-phase", action="append", default=[], help="Repeatable visual phase note such as standing or fallen_hold.")
    parser.add_argument("--review-decision", choices=["candidate", "review", "exclude"], default="review", help="Manual intake decision.")
    parser.add_argument(
        "--recommended-split",
        choices=["direct_reuse", "trim_needed", "review_only"],
        default="review_only",
        help="Whether this clip can be reused directly or needs manual trimming first.",
    )
    parser.add_argument("--ready-for-frame-extraction", action="store_true", help="Mark true only if the clip can directly enter extraction.")
    parser.add_argument("--copy-video", action="store_true", help="Copy the MP4 into the import session folder instead of keeping a reference only.")
    parser.add_argument("--root", default="datasets/new_pose_imports", help="Root directory for imported sessions.")
    parser.add_argument("--timestamp", default=None, help="Optional fixed timestamp in YYYYMMDD_HHMMSS.")
    parser.add_argument("--session-suffix", default="", help="Optional suffix appended to the generated session id.")
    parser.add_argument("--collection-context", default="external_manual_upload", help="Collection context label.")
    parser.add_argument("--recorded-by", default="", help="Optional operator name.")
    parser.add_argument("--operator-notes", default="", help="Optional freeform intake note.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    session_dir = import_video(args)
    print(session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
