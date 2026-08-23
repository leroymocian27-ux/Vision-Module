from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Sample:
    timestamp: float
    connected: bool
    stream_state: str | None
    frame_seq: int | None
    frame_width: int | None
    frame_height: int | None
    frame_age_ms: float | None
    capture_fps: float
    last_error: str | None
    reconnect_count: int
    detection_fps: float
    tracked_objects_count: int
    pose_fps: float
    temporal_active_tracks: int
    result_publish_fps: float


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate camera input and staged detection pipeline readiness.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--duration-sec", type=float, default=600.0)
    parser.add_argument("--interval-sec", type=float, default=2.0)
    parser.add_argument("--min-capture-fps", type=float, default=8.0)
    parser.add_argument("--max-frame-age-ms", type=float, default=1000.0)
    parser.add_argument("--min-detection-fps", type=float, default=2.0)
    parser.add_argument("--require-detection", action="store_true")
    parser.add_argument("--require-person", action="store_true")
    parser.add_argument("--require-pose", action="store_true")
    parser.add_argument("--require-temporal-track", action="store_true")
    parser.add_argument("--output", default="logs/camera_acceptance_latest.json")
    args = parser.parse_args()

    samples: list[Sample] = []
    deadline = time.monotonic() + args.duration_sec
    while time.monotonic() < deadline:
        sample = fetch_sample(args.base_url, args.camera_id)
        samples.append(sample)
        print(json.dumps(asdict(sample), ensure_ascii=False), flush=True)
        time.sleep(args.interval_sec)

    result = evaluate(samples, args)
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


def fetch_sample(base_url: str, camera_id: str) -> Sample:
    url = f"{base_url.rstrip('/')}/status?camera_id={camera_id}"
    with urlopen(url, timeout=5) as response:
        status = json.loads(response.read().decode("utf-8"))
    camera = status["cameras"][0]
    detection = status["detection"][0] if status.get("detection") else {}
    tracking = status.get("tracking") or {}
    pose = status.get("pose") or {}
    temporal = status.get("temporal") or {}
    pipeline = status.get("pipeline") or {}
    return Sample(
        timestamp=time.time(),
        connected=bool(camera.get("connected")),
        stream_state=camera.get("stream_state"),
        frame_seq=camera.get("frame_seq"),
        frame_width=camera.get("frame_width"),
        frame_height=camera.get("frame_height"),
        frame_age_ms=camera.get("frame_age_ms"),
        capture_fps=float(camera.get("capture_fps") or 0.0),
        last_error=camera.get("last_error"),
        reconnect_count=int(camera.get("reconnect_count") or 0),
        detection_fps=float(detection.get("detection_fps") or 0.0),
        tracked_objects_count=int(tracking.get("tracked_objects_count") or 0),
        pose_fps=float(pose.get("pose_fps") or 0.0),
        temporal_active_tracks=int(temporal.get("active_tracks") or 0),
        result_publish_fps=float(pipeline.get("result_publish_fps") or 0.0),
    )


def evaluate(samples: list[Sample], args: argparse.Namespace) -> dict[str, object]:
    if not samples:
        return {"passed": False, "reason": "no_samples", "samples": []}
    first = samples[0]
    last = samples[-1]
    frame_seq_delta = (last.frame_seq or 0) - (first.frame_seq or 0)
    reconnect_delta = last.reconnect_count - first.reconnect_count
    connected_samples = [item for item in samples if item.connected and item.stream_state == "connected"]
    fresh_samples = [
        item
        for item in connected_samples
        if item.frame_width
        and item.frame_height
        and item.capture_fps >= args.min_capture_fps
        and item.frame_age_ms is not None
        and item.frame_age_ms <= args.max_frame_age_ms
        and item.last_error is None
    ]
    capture_passed = bool(fresh_samples) and frame_seq_delta > 0 and reconnect_delta == 0
    detection_passed = not args.require_detection or max(item.detection_fps for item in samples) >= args.min_detection_fps
    person_passed = not args.require_person or max(item.tracked_objects_count for item in samples) > 0
    pose_passed = not args.require_pose or max(item.pose_fps for item in samples) > 0
    temporal_passed = not args.require_temporal_track or max(item.temporal_active_tracks for item in samples) > 0
    passed = capture_passed and detection_passed and person_passed and pose_passed and temporal_passed
    return {
        "passed": passed,
        "capture_gate_passed": capture_passed,
        "detection_gate_passed": detection_passed,
        "person_gate_passed": person_passed,
        "pose_gate_passed": pose_passed,
        "temporal_gate_passed": temporal_passed,
        "sample_count": len(samples),
        "frame_seq_delta": frame_seq_delta,
        "reconnect_delta": reconnect_delta,
        "max_capture_fps": max(item.capture_fps for item in samples),
        "max_detection_fps": max(item.detection_fps for item in samples),
        "max_tracked_objects_count": max(item.tracked_objects_count for item in samples),
        "max_pose_fps": max(item.pose_fps for item in samples),
        "max_temporal_active_tracks": max(item.temporal_active_tracks for item in samples),
        "last_sample": asdict(last),
        "samples": [asdict(item) for item in samples],
    }


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"camera_acceptance_gate_error: {exc}", file=sys.stderr)
        raise
