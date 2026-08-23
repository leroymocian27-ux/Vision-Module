from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from scripts.showcase_legacy.fall_pose_sequence_service import FallPoseSequenceService


POSE_POINT_NAMES = [
    "nose",
    "L-eye",
    "R-eye",
    "L-ear",
    "R-ear",
    "L-shoulder",
    "R-shoulder",
    "L-elbow",
    "R-elbow",
    "L-wrist",
    "R-wrist",
    "L-hip",
    "R-hip",
    "L-knee",
    "R-knee",
    "L-ankle",
    "R-ankle",
]

COCO_SKELETON = [
    (0, 1, "head"),
    (0, 2, "head"),
    (1, 3, "head"),
    (2, 4, "head"),
    (5, 6, "torso"),
    (5, 11, "torso"),
    (6, 12, "torso"),
    (11, 12, "torso"),
    (5, 7, "L-arm"),
    (7, 9, "L-arm"),
    (6, 8, "R-arm"),
    (8, 10, "R-arm"),
    (11, 13, "L-leg"),
    (13, 15, "L-leg"),
    (12, 14, "R-leg"),
    (14, 16, "R-leg"),
]

SKELETON_COLORS = {
    "head": (255, 180, 0),
    "torso": (0, 255, 100),
    "L-arm": (255, 100, 100),
    "R-arm": (100, 180, 255),
    "L-leg": (255, 255, 80),
    "R-leg": (180, 130, 255),
}


def _safe_numpy(value: Any, shape: tuple[int, ...], dtype=np.float32) -> np.ndarray:
    if value is None:
        return np.zeros(shape, dtype=dtype)
    try:
        array = value.detach().cpu().numpy() if hasattr(value, "detach") else np.asarray(value)
        return array.astype(dtype, copy=False)
    except Exception:
        return np.zeros(shape, dtype=dtype)


def _select_best_person_index(result: Any, xy_all: np.ndarray, conf_all: np.ndarray) -> int:
    if len(xy_all) == 0:
        return 0
    boxes = getattr(result, "boxes", None)
    best_index = 0
    best_score = -1.0
    for index in range(len(xy_all)):
        kp_conf = conf_all[index] if index < len(conf_all) else np.zeros((17,), dtype=np.float32)
        visible_ratio = float((kp_conf >= 0.2).mean()) if kp_conf.size else 0.0
        kp_quality = float(kp_conf[kp_conf > 0].mean()) if (kp_conf > 0).any() else 0.0
        area_score = 1.0
        box_conf = 1.0
        if boxes is not None and getattr(boxes, "xyxy", None) is not None and len(boxes.xyxy) > index:
            box = boxes.xyxy[index].detach().cpu().numpy()
            x1, y1, x2, y2 = [float(v) for v in box]
            area_score = max(1.0, (x2 - x1) * (y2 - y1))
            if getattr(boxes, "conf", None) is not None and len(boxes.conf) > index:
                box_conf = float(boxes.conf[index])
        score = area_score * max(0.05, box_conf) * (0.55 + 0.30 * visible_ratio + 0.15 * kp_quality)
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _selected_pose_arrays(pose_result: Any) -> tuple[int, np.ndarray | None, np.ndarray | None]:
    if pose_result.keypoints is None or len(pose_result.keypoints) == 0:
        return -1, None, None
    xy_all = _safe_numpy(pose_result.keypoints.xy, (0, 17, 2))
    conf_all = (
        _safe_numpy(pose_result.keypoints.conf, xy_all.shape[:2])
        if pose_result.keypoints.conf is not None
        else np.zeros(xy_all.shape[:2], dtype=np.float32)
    )
    if xy_all.ndim == 4:
        xy_all = xy_all[:, 0, :, :]
    if conf_all.ndim == 3:
        conf_all = conf_all[:, 0, :]
    best_index = _select_best_person_index(pose_result, xy_all, conf_all)
    return best_index, xy_all[best_index], conf_all[best_index]


def _kp_color(name: str) -> tuple[int, int, int]:
    lowered = name.lower()
    if "nose" in lowered:
        return (0, 200, 255)
    if "eye" in lowered:
        return (255, 180, 0)
    if "ear" in lowered:
        return (200, 150, 0)
    if "shoulder" in lowered:
        return (0, 255, 100)
    if "elbow" in lowered:
        return (255, 100, 100)
    if "wrist" in lowered:
        return (255, 50, 50)
    if "hip" in lowered:
        return (80, 255, 100)
    if "knee" in lowered:
        return (255, 255, 80)
    if "ankle" in lowered:
        return (180, 130, 255)
    return (200, 200, 200)


def _draw_panel(frame: np.ndarray, text: str, *, color: tuple[int, int, int], x: int = 14, y: int = 34) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.58
    thickness = 1
    (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
    y = max(th + baseline + 4, y)
    cv2.rectangle(frame, (x, y - th - baseline - 8), (x + tw + 8, y + baseline + 4), color, -1)
    cv2.putText(frame, text, (x + 4, y - 4), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def _best_person_feature(result: Any, *, width: int, height: int) -> tuple[np.ndarray, dict[str, Any]]:
    keypoints = result.keypoints
    if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
        return np.zeros((17 * 5,), dtype=np.float32), {"visible": 0, "avg_conf": 0.0, "motion": 0.0, "best_index": -1}

    xy_all = _safe_numpy(keypoints.xy, (0, 17, 2))
    conf_all = _safe_numpy(keypoints.conf, xy_all.shape[:2]) if keypoints.conf is not None else np.zeros(xy_all.shape[:2], dtype=np.float32)
    if xy_all.ndim == 4:
        xy_all = xy_all[:, 0, :, :]
    if conf_all.ndim == 3:
        conf_all = conf_all[:, 0, :]

    best_index = _select_best_person_index(result, xy_all, conf_all)
    xy = xy_all[best_index]
    scores = conf_all[best_index]
    visible = scores >= 0.2

    if visible.any():
        xs = xy[visible, 0]
        ys = xy[visible, 1]
        center_x = float((xs.min() + xs.max()) * 0.5)
        center_y = float((ys.min() + ys.max()) * 0.5)
        scale = max(float(xs.max() - xs.min()), float(ys.max() - ys.min()), 1.0)
    else:
        center_x = width * 0.5
        center_y = height * 0.5
        scale = max(width, height, 1)

    normalized: list[float] = []
    for (x, y), score in zip(xy, scores):
        normalized.extend([(float(x) - center_x) / scale, (float(y) - center_y) / scale, float(score)])

    base = np.asarray(normalized, dtype=np.float32).reshape(17, 3)
    base = np.nan_to_num(base, nan=0.0, posinf=0.0, neginf=0.0)
    base[:, :2] = np.clip(base[:, :2], -2.0, 2.0)
    base[:, 2] = np.clip(base[:, 2], 0.0, 1.0)
    velocity = np.zeros((17, 2), dtype=np.float32)
    debug = {
        "visible": int(visible.sum()),
        "avg_conf": round(float(scores[visible].mean()) if visible.any() else 0.0, 4),
        "motion": 0.0,
        "best_index": int(best_index),
    }
    return np.concatenate([base.reshape(-1), velocity.reshape(-1)], axis=0).astype(np.float32), debug


def _add_motion(feature: np.ndarray, previous: np.ndarray | None, debug: dict[str, Any]) -> np.ndarray:
    current = feature.reshape(17, 5).copy()
    if previous is not None:
        prev = previous.reshape(17, 5)
        delta = current[:, :2] - prev[:, :2]
        current[:, 3:5] = np.clip(delta, -1.25, 1.25)
    else:
        current[:, 3:5] = 0.0
    debug["motion"] = round(float(np.linalg.norm(current[:, 3:5], axis=1).mean()), 4)
    return current.reshape(-1).astype(np.float32)


def _draw_pose_overlay(
    frame: np.ndarray,
    pose_result: Any,
    *,
    status: str,
    probability: float,
    debug: dict[str, Any],
) -> None:
    best_index, xy, conf = _selected_pose_arrays(pose_result)
    if xy is None or conf is None:
        _draw_panel(frame, f"pose_tcn={status} prob={probability:.3f} no-person", color=(42, 160, 80))
        return

    for from_idx, to_idx, group in COCO_SKELETON:
        if conf[from_idx] <= 0.05 or conf[to_idx] <= 0.05:
            continue
        p1 = (int(xy[from_idx, 0]), int(xy[from_idx, 1]))
        p2 = (int(xy[to_idx, 0]), int(xy[to_idx, 1]))
        avg_conf = (float(conf[from_idx]) + float(conf[to_idx])) * 0.5
        thickness = 1 if avg_conf < 0.3 else 2 if avg_conf < 0.6 else 3
        cv2.line(frame, p1, p2, SKELETON_COLORS[group], thickness)

    for idx, name in enumerate(POSE_POINT_NAMES):
        if conf[idx] <= 0.05:
            continue
        px, py = int(xy[idx, 0]), int(xy[idx, 1])
        radius = 4 if conf[idx] >= 0.6 else 3 if conf[idx] >= 0.3 else 2
        color = _kp_color(name)
        cv2.circle(frame, (px, py), radius, color, -1)
        if conf[idx] >= 0.5:
            cv2.circle(frame, (px, py), radius + 1, (255, 255, 255), 1)

    panel_color = (40, 40, 230) if status == "fall" else (0, 152, 180) if status == "suspected" else (42, 160, 80)
    if pose_result.boxes is not None and len(pose_result.boxes) > best_index >= 0:
        box = pose_result.boxes.xyxy[best_index].cpu().numpy()
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        cv2.rectangle(frame, (x1, y1), (x2, y2), panel_color, 2)

    _draw_panel(
        frame,
        f"pose_tcn={status} prob={probability:.3f} kp={debug['visible']}/17 motion={debug['motion']:.3f}",
        color=panel_color,
    )


def run_pose_tcn_showcase(
    *,
    source: Path,
    output_video: Path,
    pose_model_path: Path,
    tcn_weights_path: Path,
    sequence_length: int = 32,
    imgsz: int = 384,
    conf: float = 0.2,
    max_frames: int = 0,
) -> dict[str, Any]:
    source = source.expanduser().resolve()
    output_video = output_video.expanduser().resolve()
    pose_model_path = pose_model_path.expanduser().resolve()
    tcn_weights_path = tcn_weights_path.expanduser().resolve()

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {source}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if max_frames > 0:
        frame_count = min(frame_count, max_frames) if frame_count > 0 else max_frames
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid video dimensions: {width}x{height}")

    output_video.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(output_video), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not write video: {output_video}")

    os_force_cpu = __import__("os").environ.get("FALL_DEMO_FORCE_CPU", "1") != "0"
    device: str | int = "cpu" if os_force_cpu or not torch.cuda.is_available() else 0
    pose_model = YOLO(str(pose_model_path))
    sequence_service = FallPoseSequenceService(weights_path=tcn_weights_path, sequence_length=sequence_length)

    records: list[dict[str, Any]] = []
    previous_feature: np.ndarray | None = None
    frame_index = 0
    started = time.perf_counter()

    try:
        while True:
            if max_frames > 0 and frame_index >= max_frames:
                break
            ok, frame = capture.read()
            if not ok:
                break

            with torch.inference_mode():
                pose_result = pose_model.predict(frame, verbose=False, imgsz=imgsz, conf=conf, device=device)[0]

            base_feature, debug = _best_person_feature(pose_result, width=width, height=height)
            feature = _add_motion(base_feature, previous_feature, debug)
            previous_feature = base_feature

            prediction = sequence_service.push_frame(feature, session_id=source.stem)
            probability = float(prediction.get("fall_probability") or 0.0)
            status = str(prediction.get("status") or "warming")

            _draw_pose_overlay(frame, pose_result, status=status, probability=probability, debug=debug)
            writer.write(frame)

            records.append(
                {
                    "frame": frame_index,
                    "time_s": round(frame_index / max(fps, 1e-6), 3),
                    "ready": status not in {"warming", "warmup"},
                    "status": status,
                    "fall_probability": round(probability, 4),
                    "visible_keypoints": int(debug.get("visible", 0)),
                    "avg_keypoint_conf": float(debug.get("avg_conf", 0.0)),
                    "motion_energy": float(debug.get("motion", 0.0)),
                }
            )
            frame_index += 1
    finally:
        capture.release()
        writer.release()

    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record["status"])
        status_counts[status] = status_counts.get(status, 0) + 1

    max_fall_probability = max((float(item["fall_probability"]) for item in records), default=0.0)
    summary = {
        "mode": "health1_pose_tcn",
        "status_counts": status_counts,
        "max_fall_probability": round(max_fall_probability, 4),
        "pose_model": str(pose_model_path),
        "tcn_model": sequence_service.status(),
    }
    return {
        "video": str(source),
        "output_video": str(output_video),
        "frame_count": frame_index,
        "processed_frames": frame_index,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "summary": summary,
        "records": records,
    }
