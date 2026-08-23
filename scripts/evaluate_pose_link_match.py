from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any

import cv2
import numpy as np
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "datasets" / "pose_yolo"
OUT_DIR = ROOT / "models"
KP_NAMES = [
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
TORSO_IDS = [5, 6, 11, 12]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate YOLO Pose models with tracking-bbox attachment metrics.")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.12)
    parser.add_argument("--device", default="0")
    parser.add_argument("--name", default="pose_yolo_link_match")
    args = parser.parse_args()

    items = load_items(args.split)
    if not items:
        raise SystemExit(f"no items for split: {args.split}")

    report = {
        "split": args.split,
        "items": len(items),
        "imgsz": args.imgsz,
        "conf": args.conf,
        "models": {},
    }
    for model_path in args.models:
        report["models"][model_path] = evaluate_model(
            model_path=model_path,
            items=items,
            imgsz=args.imgsz,
            conf=args.conf,
            device=args.device,
        )

    out_path = OUT_DIR / f"{args.name}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def load_items(split: str) -> list[dict[str, Any]]:
    manifest_rows = {}
    manifest_path = DATASET / "meta" / "manifest.csv"
    if manifest_path.exists():
        with manifest_path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                manifest_rows[row.get("output_label", "").replace("\\", "/")] = row

    items = []
    label_dir = DATASET / "labels" / split
    image_dir = DATASET / "images" / split
    for label_path in sorted(label_dir.glob("*.txt")):
        image_path = find_image(image_dir, label_path.stem)
        if image_path is None:
            continue
        line = label_path.read_text(encoding="utf-8").strip()
        if not line:
            continue
        rel_label = str(label_path.relative_to(ROOT)).replace("\\", "/")
        items.append(
            {
                "image_path": image_path,
                "label_path": label_path,
                "label": parse_label(line),
                "meta": manifest_rows.get(rel_label, {}),
            }
        )
    return items


def find_image(image_dir: Path, stem: str) -> Path | None:
    for suffix in (".jpg", ".jpeg", ".png"):
        path = image_dir / f"{stem}{suffix}"
        if path.exists():
            return path
    return None


def parse_label(line: str) -> dict[str, Any]:
    parts = [float(part) for part in line.split()]
    if len(parts) != 5 + 17 * 3:
        raise ValueError(f"bad yolo pose label length: {len(parts)}")
    bbox = parts[1:5]
    keypoints = []
    cursor = 5
    for index in range(17):
        keypoints.append(
            {
                "name": KP_NAMES[index],
                "x": parts[cursor],
                "y": parts[cursor + 1],
                "v": int(parts[cursor + 2]),
            }
        )
        cursor += 3
    return {"bbox": bbox, "keypoints": keypoints}


def evaluate_model(*, model_path: str, items: list[dict[str, Any]], imgsz: int, conf: float, device: str) -> dict[str, Any]:
    model = YOLO(model_path)
    rows = []
    for item in items:
        image = cv2.imread(str(item["image_path"]))
        if image is None:
            continue
        h, w = image.shape[:2]
        gt_bbox_px = yolo_bbox_to_xyxy(item["label"]["bbox"], w, h)
        gt_kps_px = keypoints_to_pixels(item["label"]["keypoints"], w, h)
        result = model.predict(source=image, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
        candidates = collect_candidates(result)
        best = select_best_candidate(candidates, gt_bbox_px)
        row = {
            "image": item["image_path"].name,
            "group": item["meta"].get("group", ""),
            "matched": best is not None,
        }
        if best is None:
            row.update(
                {
                    "candidate_iou": 0.0,
                    "inside_ratio": 0.0,
                    "torso_inside_ratio": 0.0,
                    "skeleton_confidence": 0.0,
                    "keypoint_recall": 0.0,
                    "mean_kp_distance_ratio": 1.0,
                    "detached": True,
                }
            )
        else:
            inside = points_inside_ratio(best["xy"], best["conf"], expand_bbox(gt_bbox_px, 0.08))
            torso_inside = torso_inside_ratio(best["xy"], best["conf"], expand_bbox(gt_bbox_px, 0.08))
            kp_recall, distance = keypoint_alignment(best["xy"], best["conf"], gt_kps_px, gt_bbox_px)
            row.update(
                {
                    "candidate_iou": iou(best["pose_bbox"], gt_bbox_px),
                    "inside_ratio": inside,
                    "torso_inside_ratio": torso_inside,
                    "skeleton_confidence": best["skeleton_confidence"],
                    "keypoint_recall": kp_recall,
                    "mean_kp_distance_ratio": distance,
                    "detached": inside < 0.65 or torso_inside < 0.5,
                }
            )
        rows.append(row)

    numeric_keys = [
        "candidate_iou",
        "inside_ratio",
        "torso_inside_ratio",
        "skeleton_confidence",
        "keypoint_recall",
        "mean_kp_distance_ratio",
    ]
    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_group.setdefault(row["group"] or "unknown", []).append(row)
    return {
        "count": len(rows),
        "matched_rate": fraction(row["matched"] for row in rows),
        "detached_rate": fraction(row["detached"] for row in rows),
        **{f"mean_{key}": safe_mean(row[key] for row in rows) for key in numeric_keys},
        "groups": {
            group: {
                "count": len(group_rows),
                "matched_rate": fraction(row["matched"] for row in group_rows),
                "detached_rate": fraction(row["detached"] for row in group_rows),
                "mean_inside_ratio": safe_mean(row["inside_ratio"] for row in group_rows),
                "mean_candidate_iou": safe_mean(row["candidate_iou"] for row in group_rows),
                "mean_keypoint_recall": safe_mean(row["keypoint_recall"] for row in group_rows),
                "mean_kp_distance_ratio": safe_mean(row["mean_kp_distance_ratio"] for row in group_rows),
            }
            for group, group_rows in sorted(by_group.items())
        },
        "worst_rows": sorted(
            rows,
            key=lambda row: (row["detached"], -row["mean_kp_distance_ratio"], -1.0 + row["inside_ratio"]),
            reverse=True,
        )[:10],
    }


def collect_candidates(result: Any) -> list[dict[str, Any]]:
    keypoints = getattr(result, "keypoints", None)
    if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
        return []
    boxes = getattr(result, "boxes", None)
    box_conf = boxes.conf.cpu().numpy() if boxes is not None and boxes.conf is not None else None
    xy_all = keypoints.xy.cpu().numpy()
    conf_all = keypoints.conf.cpu().numpy() if keypoints.conf is not None else np.ones(xy_all.shape[:2])
    candidates = []
    for index, (xy, scores) in enumerate(zip(xy_all, conf_all)):
        valid = scores >= 0.01
        valid &= ~((xy[:, 0] <= 1.0) & (xy[:, 1] <= 1.0))
        valid_points = xy[valid]
        valid_scores = scores[valid]
        if len(valid_points) < 5:
            continue
        pose_bbox = [
            float(np.min(valid_points[:, 0])),
            float(np.min(valid_points[:, 1])),
            float(np.max(valid_points[:, 0])),
            float(np.max(valid_points[:, 1])),
        ]
        candidates.append(
            {
                "xy": xy,
                "conf": scores,
                "pose_bbox": pose_bbox,
                "skeleton_confidence": float(np.mean(valid_scores)) if len(valid_scores) else 0.0,
                "box_confidence": float(box_conf[index]) if box_conf is not None and index < len(box_conf) else 0.0,
            }
        )
    return candidates


def select_best_candidate(candidates: list[dict[str, Any]], bbox: list[float]) -> dict[str, Any] | None:
    best = None
    best_score = -1.0
    for candidate in candidates:
        score = (
            iou(candidate["pose_bbox"], bbox) * 0.55
            + center_score(candidate["pose_bbox"], bbox) * 0.20
            + points_inside_ratio(candidate["xy"], candidate["conf"], expand_bbox(bbox, 0.08)) * 0.15
            + candidate["skeleton_confidence"] * 0.05
            + candidate["box_confidence"] * 0.05
        )
        if score > best_score:
            best_score = score
            best = candidate
    return best


def yolo_bbox_to_xyxy(bbox: list[float], w: int, h: int) -> list[float]:
    x, y, bw, bh = bbox
    return [(x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h]


def keypoints_to_pixels(keypoints: list[dict[str, Any]], w: int, h: int) -> list[dict[str, Any]]:
    return [{"x": kp["x"] * w, "y": kp["y"] * h, "v": kp["v"]} for kp in keypoints]


def keypoint_alignment(
    pred_xy: np.ndarray,
    pred_conf: np.ndarray,
    gt_kps: list[dict[str, Any]],
    bbox: list[float],
) -> tuple[float, float]:
    diag = max(1.0, math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1]))
    visible = [index for index, kp in enumerate(gt_kps) if kp["v"] > 0]
    if not visible:
        return 0.0, 1.0
    found = 0
    distances = []
    for index in visible:
        if index >= len(pred_xy) or pred_conf[index] < 0.01:
            continue
        found += 1
        distances.append(math.hypot(float(pred_xy[index][0]) - gt_kps[index]["x"], float(pred_xy[index][1]) - gt_kps[index]["y"]) / diag)
    return found / len(visible), safe_mean(distances, default=1.0)


def points_inside_ratio(points: np.ndarray, confidences: np.ndarray, bbox: list[float]) -> float:
    visible = points[confidences >= 0.01]
    if len(visible) == 0:
        return 0.0
    x1, y1, x2, y2 = bbox
    inside = (visible[:, 0] >= x1) & (visible[:, 0] <= x2) & (visible[:, 1] >= y1) & (visible[:, 1] <= y2)
    return float(np.count_nonzero(inside) / len(visible))


def torso_inside_ratio(points: np.ndarray, confidences: np.ndarray, bbox: list[float]) -> float:
    torso = []
    for index in TORSO_IDS:
        if index < len(points) and index < len(confidences) and confidences[index] >= 0.01:
            torso.append(points[index])
    if not torso:
        return 0.0
    arr = np.array(torso, dtype=np.float32)
    x1, y1, x2, y2 = bbox
    inside = (arr[:, 0] >= x1) & (arr[:, 0] <= x2) & (arr[:, 1] >= y1) & (arr[:, 1] <= y2)
    return float(np.count_nonzero(inside) / len(arr))


def expand_bbox(bbox: list[float], ratio: float) -> list[float]:
    x1, y1, x2, y2 = bbox
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    return [x1 - width * ratio, y1 - height * ratio, x2 + width * ratio, y2 + height * ratio]


def center_score(a: list[float], b: list[float]) -> float:
    ac = ((a[0] + a[2]) * 0.5, (a[1] + a[3]) * 0.5)
    bc = ((b[0] + b[2]) * 0.5, (b[1] + b[3]) * 0.5)
    diag = max(1.0, math.hypot(b[2] - b[0], b[3] - b[1]))
    return max(0.0, 1.0 - math.hypot(ac[0] - bc[0], ac[1] - bc[1]) / diag)


def iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def fraction(values: Any) -> float:
    values = list(values)
    return round(sum(1 for value in values if value) / len(values), 6) if values else 0.0


def safe_mean(values: Any, default: float = 0.0) -> float:
    values = [float(value) for value in values]
    return round(mean(values), 6) if values else default


if __name__ == "__main__":
    raise SystemExit(main())
