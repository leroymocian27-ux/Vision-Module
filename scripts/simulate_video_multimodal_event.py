from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.event_api import _record_payload
from app.core.config import Settings
from app.events.delivery import build_main_system_payload
from app.events.pipeline import EventPipelineService
from app.schemas.vision_result import DetectedObject, VisionResult


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a clearly labelled local multimodal event simulation from a video file.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--camera-id", default="simulation_camera")
    parser.add_argument("--trigger-second", type=float, default=3.0)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not video_path.is_file():
        raise SystemExit("input video does not exist")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_dir = output_dir / "event_archive"
    settings = replace(
        Settings(),
        event_pipeline_enabled=True,
        event_ring_buffer_enabled=True,
        # Offline simulation retains the complete short source; realtime limits
        # remain unchanged in the application configuration.
        event_ring_buffer_seconds=15.0,
        event_ring_buffer_max_frames=1024,
        event_ring_buffer_max_bytes=512 * 1024 * 1024,
        event_worker_enabled=False,
        event_semantic_enabled=True,
        event_archive_enabled=True,
        event_archive_dir=str(archive_dir),
        event_archive_save_keyframes=True,
        event_archive_save_json=True,
        event_keyframe_serving_enabled=True,
        event_outbox_backend="sqlite",
        event_outbox_sqlite_path=str(output_dir / "event_outbox.sqlite3"),
        event_delivery_enabled=False,
        event_vlm_enabled=False,
        event_qwen_keyframe_analysis_enabled=True,
        event_qwen_keyframe_model=args.model,
        event_qwen_keyframe_timeout_seconds=max(1.0, args.timeout),
        qwen_media_input_enabled=True,
        qwen_media_privacy_approved=True,
        main_system_alert_enabled=False,
    )
    pipeline = EventPipelineService(settings)
    try:
        metadata = _load_video_into_ring(pipeline, video_path, args.camera_id, args.trigger_second)
        trigger_timestamp = metadata["trigger_timestamp"]
        event = VisionResult(
            camera_id=args.camera_id,
            timestamp=trigger_timestamp,
            frame_seq=metadata["trigger_frame_seq"],
            frame_width=metadata["width"],
            frame_height=metadata["height"],
            objects=[DetectedObject(
                label="person",
                confidence=0.9,
                bbox=[0.0, 0.0, float(metadata["width"]), float(metadata["height"])],
                track_id=1,
                fall_decision={
                    "fall_state": "fallen_confirmed",
                    "risk_level": "critical",
                    "fall_probability": 0.95,
                    "fall_evidence_score": 0.9,
                    "adl_suppression_score": 0.1,
                    "reason": "synthetic_confirmed_event_over_video",
                },
                features={
                    "motion": {"tracking_stable": True, "rapid_descent": True},
                    "fall_state_sequence": ["standing", "falling", "fallen_confirmed"],
                },
                temporal={"fall_probability": 0.95, "post_event_stillness_ms": 3000},
            )],
        )
        incident_id = pipeline.observe_result(event)[0].incident_id
        pipeline.process_once("video-simulation")
        record = _wait_for_qwen(pipeline, incident_id, timeout_seconds=max(5.0, args.timeout + 10.0))
        if record.evidence_package is None or record.trusted_result is None:
            raise RuntimeError("event simulation did not produce evidence and trusted result")

        main_payload = build_main_system_payload(
            record.trusted_result,
            record.evidence_package,
            record.event_semantics,
            delivery_mode="dry_run",
            dry_run=True,
            qwen_advisory=record.qwen_advisory,
        )
        public_event = _record_payload(record, pipeline)
        _write_json(output_dir / "main_system_payload_dry_run.json", main_payload)
        _write_json(output_dir / "public_event_payload.json", public_event)
        result = {
            "simulation_label": "SYNTHETIC_CONFIRMED_EVENT_OVER_USER_PROVIDED_VIDEO",
            "source_video": {"file_name": video_path.name, "sha256": _sha256(video_path)},
            "no_real_main_system_post": True,
            "no_real_fallfusion_confirmed_claim": True,
            "incident_id": incident_id,
            "video": metadata,
            "event_status": record.status,
            "trusted_result": record.trusted_result.model_dump(mode="json"),
            "qwen_advisory": record.qwen_advisory.model_dump(mode="json") if record.qwen_advisory else None,
            "archive_id": record.archive_path,
            "main_system_payload_file": "main_system_payload_dry_run.json",
            "public_event_payload_file": "public_event_payload.json",
        }
        _write_json(output_dir / "simulation_result.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if record.qwen_advisory and record.qwen_advisory.analysis_status == "completed" else 1
    finally:
        pipeline.stop()


def _load_video_into_ring(pipeline: EventPipelineService, video_path: Path, camera_id: str, trigger_second: float) -> dict:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("video could not be opened")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("video dimensions are invalid")
    start = datetime.now(timezone.utc)
    frame_index = 0
    trigger_frame = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        timestamp = start + timedelta(seconds=frame_index / fps)
        pipeline.ring_buffer.add_frame(camera_id, frame_index, timestamp.isoformat(), frame)
        if frame_index / fps <= trigger_second:
            trigger_frame = frame_index
        frame_index += 1
    capture.release()
    if frame_index == 0:
        raise RuntimeError("video has no readable frames")
    trigger_timestamp = (start + timedelta(seconds=trigger_frame / fps)).isoformat()
    return {
        "frame_count": frame_index,
        "fps": fps,
        "width": width,
        "height": height,
        "trigger_second": round(trigger_frame / fps, 3),
        "trigger_frame_seq": trigger_frame,
        "trigger_timestamp": trigger_timestamp,
    }


def _wait_for_qwen(pipeline: EventPipelineService, incident_id: str, *, timeout_seconds: float):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = pipeline.outbox.get_event(incident_id)
        if record and record.qwen_advisory and record.qwen_advisory.analysis_status not in {"pending", "processing"}:
            return record
        time.sleep(0.1)
    raise TimeoutError("Qwen keyframe worker did not complete before simulation timeout")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
