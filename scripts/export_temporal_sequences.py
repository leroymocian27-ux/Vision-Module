from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export per-frame temporal feature vectors for Phase 6 training.")
    parser.add_argument("--video", required=True, help="Video file to process.")
    parser.add_argument("--output", required=True, help="JSONL output path.")
    parser.add_argument("--camera-id", default="export_camera")
    parser.add_argument("--video-id", default=None)
    parser.add_argument("--source-dataset", default=None)
    parser.add_argument("--license", default=None)
    parser.add_argument("--split-group", default=None)
    parser.add_argument("--split", default="unassigned")
    parser.add_argument("--usable-for-training", default="true")
    parser.add_argument("--label", choices=["fall", "non_fall"], required=True)
    parser.add_argument("--non-fall-subtype", default=None)
    parser.add_argument("--event-id", default=None)
    parser.add_argument("--event-start-frame", type=int, default=None)
    parser.add_argument("--event-end-frame", type=int, default=None)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--enable-pose", action="store_true")
    parser.add_argument("--device", default=None, help="Optional detector/pose device override, for example cpu or cuda:0.")
    args = parser.parse_args()

    os.environ.setdefault("ENABLE_TRACKING", "true")
    os.environ.setdefault("ENABLE_POSE", "true" if args.enable_pose else "false")
    os.environ.setdefault("ENABLE_BEHAVIOR", "false")
    os.environ.setdefault("ENABLE_TEMPORAL", "false")

    from app.core.config import get_settings
    from app.detection.object_detector import YoloPersonDetector
    from app.services.pose_service import PoseService
    from app.services.tracking_service import TrackingService
    from app.temporal.feature_vectorizer import FeatureVectorizer
    from app.temporal.target_feature_extractor import TargetFeatureExtractor

    settings = get_settings()
    if args.device:
        settings = replace_settings_device(settings, args.device)
    pose_runtime = build_pose_runtime_metadata(settings, enable_pose=args.enable_pose)
    detector = YoloPersonDetector(settings)
    tracking = TrackingService(settings)
    pose = PoseService(settings)
    extractor = TargetFeatureExtractor()
    vectorizer = FeatureVectorizer(window_size=settings.temporal_model_window_size)
    schema = vectorizer.schema().model_dump()
    previous_by_key = {}

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
            frame_height, frame_width = frame.shape[:2]
            objects = detector.detect(frame)
            objects = tracking.enrich(args.camera_id, objects, frame=frame)
            if args.enable_pose:
                objects = pose.enrich(args.camera_id, frame, objects)
            for obj in objects:
                if obj.label != "person" or obj.track_id is None:
                    continue
                sequence_key = f"track:{args.camera_id}:{obj.track_id}"
                previous = previous_by_key.get(sequence_key)
                feature = extractor.extract(
                    camera_id=args.camera_id,
                    target_object=obj,
                    timestamp=time.monotonic(),
                    previous_feature=previous,
                )
                previous_by_key[sequence_key] = feature
                vector = vectorizer.vectorize(
                    feature,
                    frame_width=frame_width,
                    frame_height=frame_height,
                )
                row = {
                    "schema_version": schema["schema_version"],
                    "schema_hash": schema["schema_hash"],
                    "feature_names": schema["feature_names"],
                    "camera_id": args.camera_id,
                    "video_id": args.video_id or video_path.name,
                    "source_dataset": args.source_dataset,
                    "license": args.license,
                    "split_group": args.split_group or sequence_key,
                    "split": args.split,
                    "usable_for_training": args.usable_for_training.strip().lower() in {"1", "true", "yes", "on"},
                    "track_id": obj.track_id,
                    "person_id": obj.person_id,
                    "sequence_key": sequence_key,
                    "frame_seq": frame_index,
                    "timestamp": feature.timestamp,
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                    "target_feature": feature.model_dump(exclude={"monotonic_time"}),
                    "pose_runtime": pose_runtime,
                    "vector": vector,
                    "label": args.label,
                    "non_fall_subtype": args.non_fall_subtype,
                    "event_id": args.event_id,
                    "event_start_frame": args.event_start_frame,
                    "event_end_frame": args.event_end_frame,
                    "track_quality": {
                        "track_switch": False,
                        "pose_available": feature.pose_available,
                        "pose_quality_level": feature.pose_quality_level,
                        "pose_rejected_reason": feature.pose_rejected_reason,
                        "occlusion_level": "unknown",
                    },
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows += 1
            frame_index += 1
    cap.release()
    print(json.dumps({"output": str(output_path), "rows": rows, "schema": schema}, ensure_ascii=False, indent=2))
    return 0


def replace_settings_device(settings, device: str):
    from dataclasses import replace

    return replace(
        settings,
        yolo_device=device,
        yolo_fall_device=device,
        yolo_pose_device=device,
        yolo11_pose_device=device,
        rtmpose_device=device,
    )


def build_pose_runtime_metadata(settings, *, enable_pose: bool) -> dict:
    provider = getattr(settings, "pose_provider", "disabled_placeholder") if enable_pose else "disabled_placeholder"
    return {
        "pose_enabled": bool(enable_pose),
        "pose_provider": provider,
        "pose_model_path": active_pose_model_path(settings, provider) if enable_pose else None,
        "pose_device": active_pose_device(settings, provider) if enable_pose else None,
    }


def active_pose_model_path(settings, provider: str) -> str | None:
    normalized = str(provider or "").strip().lower()
    if normalized in {"yolo11_legacy", "branch4_legacy"}:
        return getattr(settings, "yolo11_pose_model_path", None)
    if normalized == "yolo":
        return getattr(settings, "yolo_pose_model_path", None)
    if normalized == "rtmpose_onnx":
        return getattr(settings, "rtmpose_onnx_model_path", None)
    if normalized == "mmpose":
        return getattr(settings, "rtmpose_checkpoint_path", None)
    return (
        getattr(settings, "yolo11_pose_model_path", None)
        or getattr(settings, "yolo_pose_model_path", None)
        or getattr(settings, "rtmpose_onnx_model_path", None)
    )


def active_pose_device(settings, provider: str) -> str | None:
    normalized = str(provider or "").strip().lower()
    if normalized in {"yolo11_legacy", "branch4_legacy"}:
        return getattr(settings, "yolo11_pose_device", None) or getattr(settings, "yolo_pose_device", None)
    if normalized == "yolo":
        return getattr(settings, "yolo_pose_device", None)
    if normalized in {"rtmpose_onnx", "mmpose"}:
        return getattr(settings, "rtmpose_device", None)
    return (
        getattr(settings, "yolo11_pose_device", None)
        or getattr(settings, "yolo_pose_device", None)
        or getattr(settings, "rtmpose_device", None)
    )


if __name__ == "__main__":
    raise SystemExit(main())
