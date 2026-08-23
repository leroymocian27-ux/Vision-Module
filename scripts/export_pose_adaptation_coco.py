from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COCO_KEYPOINT_NAMES = [
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
]

COCO_SKELETON = [
    [16, 14],
    [14, 12],
    [17, 15],
    [15, 13],
    [12, 13],
    [6, 12],
    [7, 13],
    [6, 7],
    [6, 8],
    [7, 9],
    [8, 10],
    [9, 11],
    [2, 3],
    [1, 2],
    [1, 3],
    [2, 4],
    [3, 5],
    [4, 6],
    [5, 7],
]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export RTMPose pseudo-labels as COCO keypoint annotations for project adaptation."
    )
    parser.add_argument(
        "--manifest",
        default="data/phase7_labels/phase7_video_labels.jsonl",
        help="Video manifest JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/pose_adaptation_dataset",
        help="Output dataset directory.",
    )
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--max-videos", type=int, default=0)
    parser.add_argument("--max-frames-per-video", type=int, default=0)
    parser.add_argument("--min-person-confidence", type=float, default=0.2)
    parser.add_argument("--min-skeleton-confidence", type=float, default=0.7)
    parser.add_argument("--min-keypoint-confidence", type=float, default=0.2)
    parser.add_argument("--camera-prefix", default="pose_adapt")
    args = parser.parse_args()

    os.environ.setdefault("ENABLE_TRACKING", "true")
    os.environ.setdefault("ENABLE_POSE", "true")
    os.environ.setdefault("POSE_PROVIDER", "rtmpose_onnx")
    os.environ.setdefault("ENABLE_BEHAVIOR", "false")
    os.environ.setdefault("ENABLE_TEMPORAL", "false")

    from app.core.config import get_settings
    from app.detection.object_detector import YoloPersonDetector
    from app.pose.rtmpose_onnx_estimator import RTMPoseOnnxEstimator
    from app.services.tracking_service import TrackingService

    settings = get_settings()
    detector = YoloPersonDetector(settings)
    tracker = TrackingService(settings)
    estimator = RTMPoseOnnxEstimator(settings)

    manifest_path = ROOT / args.manifest
    output_dir = ROOT / args.output_dir
    images_dir = output_dir / "images"
    ann_dir = output_dir / "annotations"
    images_dir.mkdir(parents=True, exist_ok=True)
    ann_dir.mkdir(parents=True, exist_ok=True)

    rows = _read_jsonl(manifest_path)
    rows = [
        row
        for row in rows
        if bool(row.get("usable_for_training", True))
    ]
    if args.max_videos > 0:
        rows = rows[: args.max_videos]

    coco_by_split: dict[str, dict] = {}
    image_id_counter = 1
    annotation_id_counter = 1
    summary = defaultdict(int)

    for split in ["train", "val", "test"]:
        coco_by_split[split] = {
            "info": {
                "description": "Vision Service RTMPose pseudo-label adaptation dataset",
                "version": "2026-06-14",
            },
            "licenses": [],
            "images": [],
            "annotations": [],
            "categories": [
                {
                    "id": 1,
                    "name": "person",
                    "supercategory": "person",
                    "keypoints": COCO_KEYPOINT_NAMES,
                    "skeleton": COCO_SKELETON,
                }
            ],
        }

    for video_index, row in enumerate(rows, start=1):
        split = str(row.get("split") or "train")
        if split not in coco_by_split:
            split = "train"

        video_path = _resolve_video_path(row)
        if video_path is None or not video_path.exists():
            continue

        camera_id = f"{args.camera_prefix}_{video_index:04d}"
        tracker.reset(camera_id)
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            continue

        frame_index = 0
        exported_frames = 0
        while True:
            if args.max_frames_per_video and exported_frames >= args.max_frames_per_video:
                break
            ok, frame = cap.read()
            if not ok:
                break
            if frame_index % max(1, args.frame_stride) != 0:
                frame_index += 1
                continue

            objects = detector.detect(frame)
            objects = [
                item
                for item in objects
                if item.label == "person" and float(item.confidence) >= args.min_person_confidence
            ]
            if not objects:
                frame_index += 1
                continue
            objects = tracker.enrich(camera_id, objects, frame=frame)
            objects = [item for item in objects if item.track_id is not None]
            if not objects:
                frame_index += 1
                continue

            pose_by_track = estimator.estimate(frame, objects)
            valid_annotations = []
            for item in objects:
                pose = pose_by_track.get(item.track_id)
                if pose is None:
                    continue
                if float(pose.skeleton_confidence) < args.min_skeleton_confidence:
                    continue
                valid_annotations.append((item, pose))

            if not valid_annotations:
                frame_index += 1
                continue

            rel_image = Path(split) / f"{video_path.stem}_f{frame_index:06d}.jpg"
            abs_image = images_dir / rel_image
            abs_image.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(abs_image), frame)
            height, width = frame.shape[:2]
            coco_by_split[split]["images"].append(
                {
                    "id": image_id_counter,
                    "file_name": rel_image.as_posix(),
                    "width": width,
                    "height": height,
                    "video_id": row.get("video_id"),
                    "frame_index": frame_index,
                    "source_dataset": row.get("source_dataset") or row.get("source"),
                    "binary_label": row.get("binary_label"),
                    "non_fall_subtype": row.get("non_fall_subtype"),
                }
            )

            for item, pose in valid_annotations:
                keypoints, num_keypoints = _to_coco_keypoints(
                    pose.model_dump()["keypoints"],
                    min_confidence=args.min_keypoint_confidence,
                )
                bbox_xywh = _xyxy_to_xywh(item.bbox)
                coco_by_split[split]["annotations"].append(
                    {
                        "id": annotation_id_counter,
                        "image_id": image_id_counter,
                        "category_id": 1,
                        "bbox": bbox_xywh,
                        "area": round(float(bbox_xywh[2] * bbox_xywh[3]), 4),
                        "iscrowd": 0,
                        "num_keypoints": num_keypoints,
                        "keypoints": keypoints,
                        "track_id": item.track_id,
                        "person_confidence": float(item.confidence),
                        "skeleton_confidence": float(pose.skeleton_confidence),
                    }
                )
                annotation_id_counter += 1
                summary[f"{split}_annotations"] += 1

            image_id_counter += 1
            exported_frames += 1
            summary[f"{split}_images"] += 1
            frame_index += 1

        cap.release()

    for split, payload in coco_by_split.items():
        out = ann_dir / f"pose_pseudolabels_{split}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    (output_dir / "summary.json").write_text(
        json.dumps({"summary": dict(summary), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": str(output_dir),
                "summary": dict(summary),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _resolve_video_path(row: dict) -> Path | None:
    absolute = row.get("absolute_path")
    if absolute:
        return Path(absolute)
    video_id = row.get("video_id")
    if not video_id:
        return None
    video_id = str(video_id).replace("\\", "/")
    if video_id.startswith("ur_fall/"):
        return ROOT / "datasets" / "ur_fall" / "videos" / Path(video_id).name
    if video_id.startswith("gmdcsa24/"):
        return ROOT / "datasets" / "gmdcsa24" / "videos" / Path(video_id).name
    if video_id.startswith("vision_service_datasets/"):
        payload = video_id.split("/", 1)[1]
        return ROOT / "datasets" / Path(payload)
    candidate = ROOT / video_id
    return candidate


def _xyxy_to_xywh(bbox: list[float]) -> list[float]:
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return [round(x1, 4), round(y1, 4), round(max(0.0, x2 - x1), 4), round(max(0.0, y2 - y1), 4)]


def _to_coco_keypoints(keypoints: list[dict], min_confidence: float) -> tuple[list[float], int]:
    flat: list[float] = []
    count = 0
    for item in keypoints:
        conf = float(item.get("confidence") or 0.0)
        visible = 2 if conf >= min_confidence else 0
        if visible > 0:
            count += 1
        flat.extend([round(float(item["x"]), 4), round(float(item["y"]), 4), visible])
    return flat, count


if __name__ == "__main__":
    raise SystemExit(main())
