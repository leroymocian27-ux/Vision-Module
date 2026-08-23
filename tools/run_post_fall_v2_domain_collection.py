from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.post_fall_v2.domain_evidence import (
    DOMAIN_ACCEPTANCE,
    DOMAIN_CALIBRATION,
    GROUND_TRUTH_FALL,
    SOURCE_TARGET_CAMERA_REPLAY,
    build_split_manifest,
    build_domain_frame_record,
    load_session_manifest,
    validate_session_splits,
    write_json,
)
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.schemas import FULL_FRAME_TRAIN_MATCHED, SampledFrame, monotonic_to_utc_iso, utc_now_iso


DEFAULT_MODEL = "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"
DEFAULT_SHA256 = "e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc"
DEFAULT_THRESHOLD = 0.3979087471961975
DEFAULT_OUTPUT_DIR = "artifacts/post_fall_v2/domain_evidence"


def sampled_from_frame(frame, *, camera_id: str, session_id: str, source_seq: int, sample_index: int) -> SampledFrame:
    now = time.monotonic()
    height, width = frame.shape[:2]
    return SampledFrame(
        camera_id=camera_id,
        frame_id=f"{session_id}_{sample_index:08d}",
        frame_seq=source_seq,
        captured_at=monotonic_to_utc_iso(now),
        sampled_at=monotonic_to_utc_iso(now),
        captured_monotonic=now,
        sampled_monotonic=now,
        source_width=int(width),
        source_height=int(height),
        source_generation=0,
        frame=frame,
    )


def resolve_source_path(raw_path: str, *, manifest_path: Path) -> Path:
    source = Path(raw_path)
    if source.is_absolute():
        return source
    return (manifest_path.parent / source).resolve()


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_capture_for_session(
    session,
    *,
    manifest_path: Path,
    classifier: FallBinaryClassifierService,
    output_dir: Path,
    max_seconds: float | None,
    max_frames: int | None,
) -> dict:
    if session.source_type == SOURCE_TARGET_CAMERA_REPLAY or session.source_path:
        if not session.source_path:
            raise ValueError(f"{session.session_id}: missing source_path")
        source = str(resolve_source_path(session.source_path, manifest_path=manifest_path))
    else:
        if not session.source_url:
            raise ValueError(f"{session.session_id}: missing source_url")
        source = session.source_url

    capture = cv2.VideoCapture(source)
    if not capture.isOpened():
        raise RuntimeError(f"{session.session_id}: cannot open source: {source}")

    native_fps = capture.get(cv2.CAP_PROP_FPS) or session.sample_fps
    frame_interval = max(1, round(native_fps / max(session.sample_fps, 0.01)))
    started = time.monotonic()
    source_seq = 0
    sample_index = 0
    candidate_count = 0
    invalid_count = 0
    global_jsonl = output_dir / "domain_frame_results.jsonl"
    session_jsonl = output_dir / "sessions" / session.session_id / "frame_results.jsonl"
    session_dir = output_dir / "sessions" / session.session_id
    write_json(session_dir / "session_metadata.json", session.to_record())

    try:
        while True:
            if max_seconds is not None and time.monotonic() - started >= max_seconds:
                break
            ok, frame = capture.read()
            if not ok:
                break
            source_seq += 1
            if source_seq % frame_interval != 0:
                continue
            sample_index += 1
            sampled = sampled_from_frame(
                frame,
                camera_id=session.camera_id,
                session_id=session.session_id,
                source_seq=source_seq,
                sample_index=sample_index,
            )
            result = classifier.infer(sampled)
            result_record = result.to_record()
            result_record["scenario_label"] = session.scenario_label
            result_record["human_label"] = session.binary_ground_truth
            record = build_domain_frame_record(session, result_record)
            append_jsonl(global_jsonl, record)
            append_jsonl(session_jsonl, record)
            candidate_count += int(bool(result.shadow_candidate_hint))
            invalid_count += int(not result.valid)
            if max_frames is not None and sample_index >= max_frames:
                break
    finally:
        capture.release()

    return {
        "session_id": session.session_id,
        "source_type": session.source_type,
        "scenario_label": session.scenario_label,
        "binary_ground_truth": session.binary_ground_truth,
        "split": session.split,
        "sampled_frames": sample_index,
        "shadow_candidate_hints": candidate_count,
        "invalid_frames": invalid_count,
        "output": str(session_jsonl),
    }


def write_manifest_template(path: Path) -> None:
    template = {
        "sessions": [
            {
                "session_id": "target_cam_session_001",
                "camera_id": "camera_01",
                "camera_position_version": "CAM_POS_V1",
                "room_id": "room_01",
                "actor_id": "actor_01",
                "scenario_label": "standing",
                "binary_ground_truth": "noFall",
                "recorded_at": "2026-08-11T00:00:00+08:00",
                "lighting": "normal_light",
                "distance_category": "medium",
                "occlusion_level": "no_occlusion",
                "resolution": "2304x1296",
                "source_width": 2304,
                "source_height": 1296,
                "source_type": SOURCE_TARGET_CAMERA_REPLAY,
                "source_path": "recordings/target_cam_session_001.mp4",
                "split": DOMAIN_CALIBRATION,
                "sample_fps": 2.0,
                "input_policy": FULL_FRAME_TRAIN_MATCHED,
                "special_scenarios": [],
            },
            {
                "session_id": "target_cam_session_002",
                "camera_id": "camera_01",
                "camera_position_version": "CAM_POS_V1",
                "room_id": "room_01",
                "actor_id": "actor_01",
                "scenario_label": "fallen_floor_supine",
                "binary_ground_truth": GROUND_TRUTH_FALL,
                "recorded_at": "2026-08-11T00:00:00+08:00",
                "lighting": "normal_light",
                "distance_category": "medium",
                "occlusion_level": "no_occlusion",
                "resolution": "2304x1296",
                "source_width": 2304,
                "source_height": 1296,
                "source_type": SOURCE_TARGET_CAMERA_REPLAY,
                "source_path": "recordings/target_cam_session_002.mp4",
                "split": DOMAIN_ACCEPTANCE,
                "sample_fps": 2.0,
                "input_policy": FULL_FRAME_TRAIN_MATCHED,
                "special_scenarios": ["POST_FALL_BOOTSTRAP_SCENARIO"],
            }
        ]
    }
    write_json(path, template)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect Post-Fall V2 current-camera domain evidence from target RTSP or target-camera replay."
    )
    parser.add_argument("--manifest", type=Path, help="JSON/CSV session manifest.")
    parser.add_argument("--write-template", type=Path, help="Write a manifest template and exit.")
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--model", type=Path, default=Path(DEFAULT_MODEL))
    parser.add_argument("--model-sha256", default=DEFAULT_SHA256)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--max-seconds-per-live-session", type=float, default=30.0)
    parser.add_argument("--max-frames-per-session", type=int, default=None)
    parser.add_argument("--allow-non-domain-smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Validate manifest and write run metadata without inference.")
    args = parser.parse_args()

    if args.write_template:
        write_manifest_template(args.write_template)
        print({"template_written": str(args.write_template)})
        return
    if not args.manifest:
        raise SystemExit("--manifest is required unless --write-template is used")

    sessions = load_session_manifest(args.manifest, allow_non_domain_smoke=args.allow_non_domain_smoke)
    validate_session_splits(sessions)
    split_manifest = build_split_manifest(sessions)
    run_dir = args.output_dir / time.strftime("%Y%m%d_%H%M%S")
    run_metadata = {
        "phase": "P2.5_CURRENT_CAMERA_DOMAIN_EVIDENCE_COLLECTION",
        "created_at": utc_now_iso(),
        "manifest": str(args.manifest),
        "model": str(args.model),
        "model_sha256": args.model_sha256,
        "threshold": args.threshold,
        "input_policy": FULL_FRAME_TRAIN_MATCHED,
        "allow_non_domain_smoke": bool(args.allow_non_domain_smoke),
        "dry_run": bool(args.dry_run),
        "sessions": [session.to_record() for session in sessions],
        "domain_split_manifest_sha256": split_manifest["sha256"],
        "forbidden_runtime_side_effects": {
            "env_modified": False,
            "vlm_called": False,
            "external_system_post_called": False,
            "alert_delivery_called": False,
            "fall_candidate_service_created": False,
        },
    }
    write_json(run_dir / "run_manifest.json", run_metadata)
    write_json(run_dir / "domain_split_manifest.json", split_manifest)

    if args.dry_run:
        print(
            {
                "dry_run": True,
                "sessions": len(sessions),
                "calibration_sessions": len(split_manifest["calibration_sessions"]),
                "acceptance_sessions": len(split_manifest["acceptance_sessions"]),
                "domain_split_manifest_sha256": split_manifest["sha256"],
                "output_dir": str(run_dir),
            }
        )
        return

    classifier = FallBinaryClassifierService(
        model_path=args.model,
        expected_sha256=args.model_sha256,
        threshold=args.threshold,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
    )
    session_summaries = []
    for session in sessions:
        max_seconds = args.max_seconds_per_live_session if session.source_type != SOURCE_TARGET_CAMERA_REPLAY else None
        summary = run_capture_for_session(
            session,
            manifest_path=args.manifest,
            classifier=classifier,
            output_dir=run_dir,
            max_seconds=max_seconds,
            max_frames=args.max_frames_per_session,
        )
        session_summaries.append(summary)

    collection_summary = {
        "provider": classifier.provider,
        "model_hash_verified": classifier.model_sha256 == args.model_sha256.lower(),
        "records_written": sum(item["sampled_frames"] for item in session_summaries),
        "sessions": session_summaries,
        "output_dir": str(run_dir),
    }
    write_json(run_dir / "collection_summary.json", collection_summary)
    print(collection_summary)


if __name__ == "__main__":
    main()
