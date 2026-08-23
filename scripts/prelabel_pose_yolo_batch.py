from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
POSE_RAW_ROOT = ROOT / "datasets" / "pose_yolo_raw"

KEYPOINT_NAMES = [
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Prelabel a YOLO pose manual review batch.")
    parser.add_argument("--batch-id", default="batch_001")
    parser.add_argument("--model", default="yolo11n-pose.pt")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.15)
    parser.add_argument("--kp-conf", type=float, default=0.20)
    parser.add_argument("--padding", type=float, default=0.14)
    parser.add_argument("--device", default="")
    args = parser.parse_args()

    batch_dir = POSE_RAW_ROOT / args.batch_id
    frames_dir = batch_dir / "frames"
    prelabels_dir = batch_dir / "prelabels"
    if not frames_dir.exists():
        raise SystemExit(f"frames not found: {frames_dir}")
    if not prelabels_dir.exists():
        raise SystemExit(f"prelabels not found: {prelabels_dir}")

    model = YOLO(args.model)
    total_images = 0
    total_persons = 0
    total_visible = 0
    missing_pose_persons = 0

    for prelabel_path in sorted(prelabels_dir.glob("*.json")):
        payload = json.loads(prelabel_path.read_text(encoding="utf-8"))
        image_name = str(payload["image"])
        image_path = frames_dir / image_name
        frame = cv2.imread(str(image_path))
        if frame is None:
            continue
        frame_h, frame_w = frame.shape[:2]
        total_images += 1
        new_annotations = []
        for ann in payload.get("annotations", []):
            bbox = ann.get("bbox") or {}
            total_persons += 1
            crop_info = crop_person(frame, bbox, args.padding)
            if crop_info is None:
                new_annotations.append(with_missing_keypoints(bbox))
                missing_pose_persons += 1
                continue
            crop, left, top = crop_info
            result = model.predict(
                source=crop,
                imgsz=args.imgsz,
                conf=args.conf,
                device=args.device or None,
                verbose=False,
            )[0]
            candidate = best_candidate(result, bbox, left, top, frame_w, frame_h)
            if candidate is None:
                new_annotations.append(with_missing_keypoints(bbox))
                missing_pose_persons += 1
                continue
            keypoints = []
            for name, x, y, score in candidate:
                visible = 2 if score >= args.kp_conf else 0
                if visible:
                    total_visible += 1
                keypoints.append(
                    {
                        "name": name,
                        "x": round(float(x), 6) if visible else 0.0,
                        "y": round(float(y), 6) if visible else 0.0,
                        "v": visible,
                    }
                )
            new_annotations.append({"bbox": bbox, "keypoints": keypoints})
        payload["annotations"] = new_annotations
        payload["status"] = "draft"
        payload["prelabel_model"] = args.model
        payload["prelabel_note"] = "Machine prelabel only. Human review is required before training."
        prelabel_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "batch_id": args.batch_id,
        "model": args.model,
        "images": total_images,
        "persons": total_persons,
        "visible_keypoints": total_visible,
        "missing_pose_persons": missing_pose_persons,
        "human_review_required": True,
    }
    (batch_dir / "meta" / "prelabel_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def crop_person(frame: np.ndarray, bbox: dict, padding: float) -> tuple[np.ndarray, int, int] | None:
    h, w = frame.shape[:2]
    x = float(bbox.get("x", 0.5))
    y = float(bbox.get("y", 0.5))
    bw = float(bbox.get("w", 0.0))
    bh = float(bbox.get("h", 0.0))
    if bw <= 0 or bh <= 0:
        return None
    x1 = (x - bw / 2) * w
    y1 = (y - bh / 2) * h
    x2 = (x + bw / 2) * w
    y2 = (y + bh / 2) * h
    pad_x = (x2 - x1) * padding
    pad_y = (y2 - y1) * padding
    left = max(0, int(round(x1 - pad_x)))
    top = max(0, int(round(y1 - pad_y)))
    right = min(w, int(round(x2 + pad_x)))
    bottom = min(h, int(round(y2 + pad_y)))
    if right <= left or bottom <= top:
        return None
    return frame[top:bottom, left:right].copy(), left, top


def best_candidate(result, bbox: dict, left: int, top: int, frame_w: int, frame_h: int):
    keypoints = getattr(result, "keypoints", None)
    if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
        return None
    xy_all = keypoints.xy.cpu().numpy()
    conf_all = keypoints.conf.cpu().numpy() if keypoints.conf is not None else np.ones(xy_all.shape[:2])
    target = yolo_bbox_to_xyxy(bbox)
    best = None
    best_score = -1.0
    for xy, conf in zip(xy_all, conf_all):
        global_points = []
        visible_scores = []
        for point, score in zip(xy, conf):
            if float(score) <= 0.01:
                continue
            gx = (float(point[0]) + left) / frame_w
            gy = (float(point[1]) + top) / frame_h
            if 0 <= gx <= 1 and 0 <= gy <= 1:
                global_points.append([gx, gy])
                visible_scores.append(float(score))
        if len(global_points) < 4:
            continue
        points = np.array(global_points, dtype=np.float32)
        point_box = [float(points[:, 0].min()), float(points[:, 1].min()), float(points[:, 0].max()), float(points[:, 1].max())]
        score = iou(point_box, target) + float(np.mean(visible_scores))
        if score > best_score:
            best_score = score
            best = [
                (
                    KEYPOINT_NAMES[index],
                    (float(point[0]) + left) / frame_w,
                    (float(point[1]) + top) / frame_h,
                    float(conf[index]),
                )
                for index, point in enumerate(xy[: len(KEYPOINT_NAMES)])
            ]
    return best


def with_missing_keypoints(bbox: dict) -> dict:
    return {
        "bbox": bbox,
        "keypoints": [{"name": name, "x": 0.0, "y": 0.0, "v": 0} for name in KEYPOINT_NAMES],
    }


def yolo_bbox_to_xyxy(bbox: dict) -> list[float]:
    x = float(bbox.get("x", 0.5))
    y = float(bbox.get("y", 0.5))
    w = float(bbox.get("w", 0.0))
    h = float(bbox.get("h", 0.0))
    return [x - w / 2, y - h / 2, x + w / 2, y + h / 2]


def iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


if __name__ == "__main__":
    raise SystemExit(main())
