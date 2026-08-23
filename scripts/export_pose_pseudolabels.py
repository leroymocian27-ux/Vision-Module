from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export RTMPose pseudo-labels from project videos for targeted adaptation."
    )
    parser.add_argument("--video", required=True, help="Input video path.")
    parser.add_argument("--output", required=True, help="Output JSONL path.")
    parser.add_argument("--camera-id", default="pose_export_camera")
    parser.add_argument("--frame-stride", type=int, default=3)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--min-person-confidence", type=float, default=0.2)
    args = parser.parse_args()

    os.environ.setdefault("ENABLE_TRACKING", "true")
    os.environ.setdefault("ENABLE_POSE", "true")
    os.environ.setdefault("POSE_PROVIDER", "rtmpose_onnx")
    os.environ.setdefault("ENABLE_BEHAVIOR", "false")
    os.environ.setdefault("ENABLE_TEMPORAL", "false")

    from app.core.config import get_settings
    from app.detection.object_detector import YoloPersonDetector
    from app.services.pose_service import PoseService
    from app.services.tracking_service import TrackingService

    settings = get_settings()
    detector = YoloPersonDetector(settings)
    tracking = TrackingService(settings)
    pose = PoseService(settings)

    video_path = Path(args.video)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"could not open video: {video_path}")

    rows = 0
    frame_index = 0
    with output_path.open("w", encoding="utf-8") as fh:
        while True:
            if args.max_frames and frame_index >= args.max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % max(1, args.frame_stride) != 0:
                frame_index += 1
                continue

            objects = detector.detect(frame)
            objects = [item for item in objects if float(item.confidence) >= args.min_person_confidence]
            objects = tracking.enrich(args.camera_id, objects, frame=frame)
            objects = pose.enrich(args.camera_id, frame, objects, frame_seq=frame_index, tracking_frame_seq=frame_index)

            for item in objects:
                if item.label != "person" or item.track_id is None or item.pose is None:
                    continue
                row = {
                    "video": str(video_path),
                    "camera_id": args.camera_id,
                    "frame_index": frame_index,
                    "track_id": item.track_id,
                    "bbox": [float(v) for v in item.bbox],
                    "confidence": float(item.confidence),
                    "is_target": bool(item.is_target),
                    "identity_state": item.identity_state,
                    "pose": item.pose,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows += 1
            frame_index += 1

    cap.release()
    print(json.dumps({"ok": True, "output": str(output_path), "rows": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
