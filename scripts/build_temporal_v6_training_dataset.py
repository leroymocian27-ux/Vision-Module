from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_temporal_v6_review_seed import TRAINABLE_REVIEW_DECISIONS, validate_rows

DEFAULT_REVIEW = ROOT / "data" / "temporal_v6_review" / "residual_fn_review_seed.jsonl"
DEFAULT_SEQUENCES_DIR = ROOT / "data" / "temporal_sequences_phase6d"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "temporal_v6_training" / "residual_reviewed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build temporal v6 reviewed training JSONL from reviewed residual rows.")
    parser.add_argument("--review", default=str(DEFAULT_REVIEW), help="Reviewed residual FN JSONL.")
    parser.add_argument(
        "--sequences-dir",
        default=str(DEFAULT_SEQUENCES_DIR),
        help="Root directory containing exported frame-level temporal sequence JSONL files.",
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output dataset directory.")
    parser.add_argument("--summary", default=None, help="Optional summary JSON path.")
    parser.add_argument(
        "--fps",
        type=float,
        default=25.0,
        help="FPS used to convert reviewed event milliseconds to frame indexes.",
    )
    args = parser.parse_args()

    review_path = Path(args.review)
    sequence_root = Path(args.sequences_dir)
    output_dir = Path(args.output_dir)
    summary_path = Path(args.summary) if args.summary else output_dir / "dataset_summary.json"

    rows = read_jsonl(review_path)
    validation = validate_rows(rows, source=review_path)
    if validation["error_count"]:
        raise SystemExit("review JSONL failed validation; run scripts\\validate_temporal_v6_review_seed.py first")

    result = build_dataset(
        review_rows=rows,
        sequence_root=sequence_root,
        output_dir=output_dir,
        fps=args.fps,
        review_path=review_path,
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def build_dataset(
    *,
    review_rows: list[dict[str, Any]],
    sequence_root: Path,
    output_dir: Path,
    fps: float,
    review_path: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trainable_rows = [
        row
        for row in review_rows
        if row.get("usable_for_training") is True and row.get("review_decision") in TRAINABLE_REVIEW_DECISIONS
    ]

    outputs: list[dict[str, Any]] = []
    missing_sequences: list[dict[str, Any]] = []
    total_frame_rows = 0
    total_fall_frame_rows = 0

    for row in sorted(trainable_rows, key=lambda item: str(item.get("video_id") or "")):
        source_path = sequence_path_for(row, sequence_root)
        if not source_path.exists():
            missing_sequences.append({"video_id": row.get("video_id"), "expected_path": str(source_path)})
            continue

        event_frames = event_frames_for(row, fps=fps)
        relative_output = sequence_relative_path(row)
        output_path = output_dir / relative_output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stats = write_reviewed_sequence(
            source_path=source_path,
            output_path=output_path,
            review=row,
            event_frames=event_frames,
        )
        total_frame_rows += stats["frame_rows"]
        total_fall_frame_rows += stats["fall_frame_rows"]
        outputs.append(
            {
                "video_id": row.get("video_id"),
                "source": relative_path(source_path, output_dir),
                "output": relative_path(output_path, output_dir),
                "frame_rows": stats["frame_rows"],
                "fall_frame_rows": stats["fall_frame_rows"],
                "event_frames": event_frames,
                "review_decision": row.get("review_decision"),
                "fall_subtype": row.get("fall_subtype"),
            }
        )

    train_input_manifest = output_dir / "train_inputs.json"
    train_inputs = [item["output"] for item in outputs]
    train_input_manifest.write_text(
        json.dumps(
            {
                "source_review": str(review_path.resolve()) if review_path else None,
                "sequence_root": str(sequence_root.resolve()),
                "fps": fps,
                "input_files": train_inputs,
                "train_command_hint": train_command_hint(train_inputs),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "source_review": str(review_path.resolve()) if review_path else None,
        "sequence_root": str(sequence_root.resolve()),
        "output_dir": str(output_dir.resolve()),
        "fps": fps,
        "review_rows": len(review_rows),
        "trainable_review_rows": len(trainable_rows),
        "written_sequences": len(outputs),
        "missing_sequences": missing_sequences,
        "frame_rows": total_frame_rows,
        "fall_frame_rows": total_fall_frame_rows,
        "train_inputs_manifest": str(train_input_manifest.resolve()),
        "train_inputs": train_inputs,
        "outputs": outputs,
        "next_step": (
            "No reviewed training rows yet."
            if not outputs
            else "Append train_inputs to scripts\\train_fall_lstm.py input list and rerun temporal regression gates."
        ),
    }


def write_reviewed_sequence(
    *,
    source_path: Path,
    output_path: Path,
    review: dict[str, Any],
    event_frames: dict[str, int | None],
) -> dict[str, int]:
    frame_rows = 0
    fall_frame_rows = 0
    event_start_frame = event_frames["fall_start_frame"]
    event_end_frame = event_frames["motion_end_frame"]
    event_id = f"temporal_v6_review:{safe_id(str(review.get('video_id') or source_path.stem))}"
    label_mode = reviewed_label_mode(review)
    non_fall_subtype = reviewed_non_fall_subtype(review)

    with source_path.open("r", encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for line in src:
            if not line.strip():
                continue
            frame = json.loads(line)
            frame_seq = int(frame.get("frame_seq") or 0)
            is_fall_frame = label_mode == "fall_event" and is_event_frame(frame_seq, start=event_start_frame, end=event_end_frame)
            frame["label"] = "fall" if is_fall_frame else "non_fall"
            frame["usable_for_training"] = True
            frame["event_id"] = event_id
            frame["event_start_frame"] = event_start_frame
            frame["event_end_frame"] = event_end_frame
            frame["review_source"] = "temporal_v6_residual_review"
            frame["review_status"] = review.get("review_status")
            frame["review_decision"] = review.get("review_decision")
            frame["fall_subtype"] = review.get("fall_subtype")
            frame["non_fall_subtype"] = non_fall_subtype if not is_fall_frame else None
            frame["scene_type"] = review.get("scene_type")
            frame["support_surface"] = review.get("support_surface")
            frame["recovered_within_5s"] = review.get("recovered_within_5s")
            frame["review_event_times_ms"] = {
                "fall_start_ms": review.get("fall_start_ms"),
                "ground_contact_start_ms": review.get("ground_contact_start_ms"),
                "low_posture_start_ms": review.get("low_posture_start_ms"),
                "motion_end_ms": review.get("motion_end_ms"),
                "recovery_start_ms": review.get("recovery_start_ms"),
            }
            frame["review_event_frames"] = event_frames
            frame["reviewer"] = review.get("reviewer")
            frame["review_notes"] = review.get("review_notes")
            track_quality = frame.get("track_quality") if isinstance(frame.get("track_quality"), dict) else {}
            track_quality["occlusion_level"] = review.get("occlusion_level")
            track_quality["track_quality_issue"] = review.get("track_quality_issue")
            track_quality["pose_quality_issue"] = review.get("pose_quality_issue")
            frame["track_quality"] = track_quality
            dst.write(json.dumps(frame, ensure_ascii=False) + "\n")
            frame_rows += 1
            fall_frame_rows += 1 if is_fall_frame else 0

    return {"frame_rows": frame_rows, "fall_frame_rows": fall_frame_rows}


def is_event_frame(frame_seq: int, *, start: int | None, end: int | None) -> bool:
    if start is None:
        return False
    if frame_seq < start:
        return False
    return end is None or frame_seq <= end


def reviewed_label_mode(review: dict[str, Any]) -> str:
    decision = str(review.get("review_decision") or "")
    if decision == "hard_negative_train":
        return "hard_negative"
    return "fall_event"


def reviewed_non_fall_subtype(review: dict[str, Any]) -> str | None:
    decision = str(review.get("review_decision") or "")
    if decision != "hard_negative_train":
        return None
    note = str(review.get("review_notes") or "").strip()
    if note:
        return note
    return "hard_negative_train"


def event_frames_for(row: dict[str, Any], *, fps: float) -> dict[str, int | None]:
    return {
        "fall_start_frame": ms_to_frame(row.get("fall_start_ms"), fps=fps),
        "ground_contact_start_frame": ms_to_frame(row.get("ground_contact_start_ms"), fps=fps),
        "low_posture_start_frame": ms_to_frame(row.get("low_posture_start_ms"), fps=fps),
        "motion_end_frame": ms_to_frame(row.get("motion_end_ms"), fps=fps),
        "recovery_start_frame": ms_to_frame(row.get("recovery_start_ms"), fps=fps),
    }


def ms_to_frame(value: Any, *, fps: float) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * max(fps, 1.0) / 1000.0))


def sequence_path_for(row: dict[str, Any], sequence_root: Path) -> Path:
    video_id = str(row.get("video_id") or "")
    if "/" in video_id:
        dataset, filename = video_id.split("/", 1)
        return sequence_root / dataset / f"{Path(filename).stem}.jsonl"
    return sequence_root / f"{Path(video_id).stem}.jsonl"


def sequence_relative_path(row: dict[str, Any]) -> Path:
    video_id = str(row.get("video_id") or "")
    if "/" in video_id:
        dataset, filename = video_id.split("/", 1)
        return Path(dataset) / f"{Path(filename).stem}.jsonl"
    return Path(f"{Path(video_id).stem}.jsonl")


def train_command_hint(inputs: list[str]) -> str | None:
    if not inputs:
        return None
    joined = " ".join(f"data\\temporal_v6_training\\residual_reviewed\\{item.replace('/', os.sep)}" for item in inputs)
    return f"python scripts\\train_fall_lstm.py --input {joined} --model-version v6"


def relative_path(path: Path, start: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), start.resolve()).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


if __name__ == "__main__":
    raise SystemExit(main())
