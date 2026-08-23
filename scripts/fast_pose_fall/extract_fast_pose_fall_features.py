from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from feature_schema import FEATURE_FIELDS, feature_schema


SPLITS = [
    "public_train",
    "public_val",
    "public_test",
    "local_val",
    "local_test",
    "hard_negative_test",
]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_timestamp_seconds(value: Any, first_timestamp: datetime | None) -> tuple[float | None, datetime | None]:
    if not value:
        return None, first_timestamp
    text = str(value).replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None, first_timestamp
    if first_timestamp is None:
        first_timestamp = ts
    return max(0.0, (ts - first_timestamp).total_seconds()), first_timestamp


def load_split(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in FEATURE_FIELDS}


def compute_fall_score(
    *,
    aspect_ratio: float | None,
    center_y_delta: float | None,
    velocity_y: float | None,
    speed: float | None,
    stillness_duration_sec: float | None,
    bbox_center_y: float | None,
    frame_height: float | None,
    person_confidence: float | None,
) -> float:
    aspect = safe_float(aspect_ratio)
    descent = max(safe_float(center_y_delta), safe_float(velocity_y) * 0.05)
    speed_value = safe_float(speed)
    still = safe_float(stillness_duration_sec)
    height = safe_float(frame_height)
    center = safe_float(bbox_center_y)
    center_norm = center / height if height > 0 else 0.0
    confidence = safe_float(person_confidence, 0.5)

    posture_score = clamp((aspect - 0.65) / 0.75)
    descent_score = clamp(descent / 70.0)
    low_center_score = clamp((center_norm - 0.52) / 0.33)
    still_score = clamp(still / 1.5) if speed_value < 35.0 else 0.0
    score = (
        0.46 * posture_score
        + 0.22 * descent_score
        + 0.18 * low_center_score
        + 0.14 * still_score
    )
    if confidence < 0.12:
        score *= 0.55
    return round(clamp(score), 4)


def scene_flags(bbox: tuple[float, float, float, float] | None, frame_width: int, frame_height: int) -> tuple[bool, bool, bool]:
    if bbox is None or frame_width <= 0 or frame_height <= 0:
        return False, False, False
    x1, y1, x2, y2 = bbox
    edge_margin_x = frame_width * 0.03
    edge_margin_y = frame_height * 0.03
    edge = x1 <= edge_margin_x or y1 <= edge_margin_y or x2 >= frame_width - edge_margin_x or y2 >= frame_height - edge_margin_y
    visible_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    frame_area = float(frame_width * frame_height)
    partial = edge and visible_area > frame_area * 0.05
    occluded = False
    return partial, edge, occluded


def make_feature_row(
    *,
    asset: dict[str, Any],
    split: str,
    frame_index: int,
    time_sec: float,
    track_id: int | None,
    bbox: tuple[float, float, float, float] | None,
    frame_width: int,
    frame_height: int,
    center_y_delta: float | None,
    height_delta: float | None,
    velocity_y: float | None,
    speed: float | None,
    track_age_sec: float | None,
    stillness_duration_sec: float | None,
    person_confidence: float | None,
    pose_keypoint_count: int | None = None,
    pose_confidence_mean: float | None = None,
    torso_angle: float | None = None,
    hip_height_ratio: float | None = None,
) -> dict[str, Any]:
    if bbox is None:
        x1 = y1 = x2 = y2 = width = height = area = center_x = center_y = aspect = None
    else:
        x1, y1, x2, y2 = bbox
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        area = width * height
        center_x = x1 + width / 2.0
        center_y = y1 + height / 2.0
        aspect = width / height if height > 1e-6 else 0.0

    partial, edge, occluded = scene_flags(bbox, frame_width, frame_height)
    fall_score = compute_fall_score(
        aspect_ratio=aspect,
        center_y_delta=center_y_delta,
        velocity_y=velocity_y,
        speed=speed,
        stillness_duration_sec=stillness_duration_sec,
        bbox_center_y=center_y,
        frame_height=frame_height,
        person_confidence=person_confidence,
    )
    row = {
        "asset_id": asset.get("asset_id"),
        "video_id": asset.get("video_id"),
        "dataset": asset.get("dataset"),
        "source": asset.get("source"),
        "split": split,
        "label": asset.get("label"),
        "group_id": asset.get("group_id"),
        "frame_index": int(frame_index),
        "time_sec": round(float(time_sec), 4),
        "track_id": track_id,
        "bbox_x1": round(x1, 3) if x1 is not None else None,
        "bbox_y1": round(y1, 3) if y1 is not None else None,
        "bbox_x2": round(x2, 3) if x2 is not None else None,
        "bbox_y2": round(y2, 3) if y2 is not None else None,
        "bbox_width": round(width, 3) if width is not None else None,
        "bbox_height": round(height, 3) if height is not None else None,
        "bbox_area": round(area, 3) if area is not None else None,
        "bbox_center_x": round(center_x, 3) if center_x is not None else None,
        "bbox_center_y": round(center_y, 3) if center_y is not None else None,
        "bbox_aspect_ratio": round(aspect, 4) if aspect is not None else None,
        "bbox_center_y_delta": round(center_y_delta, 3) if center_y_delta is not None else None,
        "bbox_height_delta": round(height_delta, 3) if height_delta is not None else None,
        "velocity_y": round(velocity_y, 3) if velocity_y is not None else None,
        "speed": round(speed, 3) if speed is not None else None,
        "track_age_sec": round(track_age_sec, 4) if track_age_sec is not None else None,
        "stillness_duration_sec": round(stillness_duration_sec, 4) if stillness_duration_sec is not None else None,
        "fall_score": fall_score,
        "person_confidence": round(person_confidence, 4) if person_confidence is not None else None,
        "pose_keypoint_count": pose_keypoint_count,
        "pose_confidence_mean": round(pose_confidence_mean, 4) if pose_confidence_mean is not None else None,
        "torso_angle": round(torso_angle, 4) if torso_angle is not None else None,
        "hip_height_ratio": round(hip_height_ratio, 4) if hip_height_ratio is not None else None,
        "is_partial_body": partial,
        "is_edge_person": edge,
        "is_occluded": occluded,
        "scene_tags": asset.get("scene_tags") or [],
        "hard_negative": bool(asset.get("hard_negative")),
    }
    return normalize_record(row)


class MotionBoxExtractor:
    def __init__(self, frame_width: int, frame_height: int) -> None:
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.prev_gray: np.ndarray | None = None
        self.last_bbox: tuple[float, float, float, float] | None = None
        self.last_center: tuple[float, float] | None = None
        self.last_height: float | None = None
        self.last_time: float | None = None
        self.track_started_at: float | None = None
        self.stillness_started_at: float | None = None
        self.missing_frames = 0

    def update(self, frame: np.ndarray, time_sec: float) -> dict[str, Any]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (7, 7), 0)
        bbox: tuple[float, float, float, float] | None = None
        confidence = 0.0

        if self.prev_gray is not None:
            diff = cv2.absdiff(gray, self.prev_gray)
            _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
            kernel = np.ones((7, 7), np.uint8)
            thresh = cv2.dilate(thresh, kernel, iterations=2)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            frame_area = float(self.frame_width * self.frame_height)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < max(80.0, frame_area * 0.0015):
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                boxes.append((x, y, x + w, y + h, area))
            if boxes:
                boxes.sort(key=lambda item: item[4], reverse=True)
                x1, y1, x2, y2, area = boxes[0]
                pad_x = max(8, int((x2 - x1) * 0.25))
                pad_y = max(12, int((y2 - y1) * 0.35))
                bbox = (
                    float(max(0, x1 - pad_x)),
                    float(max(0, y1 - pad_y)),
                    float(min(self.frame_width - 1, x2 + pad_x)),
                    float(min(self.frame_height - 1, y2 + pad_y)),
                )
                confidence = clamp(area / max(1.0, frame_area * 0.08), 0.15, 0.9)
                self.missing_frames = 0

        self.prev_gray = gray
        if bbox is None and self.last_bbox is not None and self.missing_frames < 8:
            bbox = self.last_bbox
            confidence = 0.18
            self.missing_frames += 1
        elif bbox is None:
            self.last_bbox = None
            self.last_center = None
            self.last_height = None
            self.last_time = time_sec
            self.track_started_at = None
            self.stillness_started_at = None
            return {
                "bbox": None,
                "center_y_delta": None,
                "height_delta": None,
                "velocity_y": None,
                "speed": None,
                "track_age_sec": None,
                "stillness_duration_sec": None,
                "person_confidence": 0.0,
            }

        x1, y1, x2, y2 = bbox
        center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        height = max(0.0, y2 - y1)
        if self.track_started_at is None:
            self.track_started_at = time_sec
        dt = max(1e-6, time_sec - self.last_time) if self.last_time is not None else 0.0
        center_y_delta = center[1] - self.last_center[1] if self.last_center is not None else 0.0
        height_delta = height - self.last_height if self.last_height is not None else 0.0
        velocity_y = center_y_delta / dt if dt > 0 else 0.0
        if self.last_center is not None and dt > 0:
            dx = center[0] - self.last_center[0]
            dy = center[1] - self.last_center[1]
            speed = math.sqrt(dx * dx + dy * dy) / dt
        else:
            speed = 0.0
        if speed < 28.0:
            if self.stillness_started_at is None:
                self.stillness_started_at = time_sec
            stillness = time_sec - self.stillness_started_at
        else:
            self.stillness_started_at = None
            stillness = 0.0

        self.last_bbox = bbox
        self.last_center = center
        self.last_height = height
        self.last_time = time_sec
        return {
            "bbox": bbox,
            "center_y_delta": center_y_delta,
            "height_delta": height_delta,
            "velocity_y": velocity_y,
            "speed": speed,
            "track_age_sec": time_sec - self.track_started_at,
            "stillness_duration_sec": stillness,
            "person_confidence": confidence,
        }


def extract_video_features(asset: dict[str, Any], split: str, frame_stride: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(asset["path"])
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return [], {
            "asset_id": asset.get("asset_id"),
            "path": str(path),
            "status": "open_failed",
            "rows": 0,
            "error": "OpenCV could not open video",
        }
    fps = safe_float(cap.get(cv2.CAP_PROP_FPS), safe_float(asset.get("fps"), 25.0))
    if fps <= 0:
        fps = safe_float(asset.get("fps"), 25.0) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    extractor = MotionBoxExtractor(width, height)
    rows: list[dict[str, Any]] = []
    frame_index = 0
    start = time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        time_sec = frame_index / fps
        features = extractor.update(frame, time_sec)
        if frame_index % frame_stride == 0:
            rows.append(
                make_feature_row(
                    asset=asset,
                    split=split,
                    frame_index=frame_index,
                    time_sec=time_sec,
                    track_id=1 if features["bbox"] is not None else None,
                    bbox=features["bbox"],
                    frame_width=width,
                    frame_height=height,
                    center_y_delta=features["center_y_delta"],
                    height_delta=features["height_delta"],
                    velocity_y=features["velocity_y"],
                    speed=features["speed"],
                    track_age_sec=features["track_age_sec"],
                    stillness_duration_sec=features["stillness_duration_sec"],
                    person_confidence=features["person_confidence"],
                )
            )
        frame_index += 1
    cap.release()
    elapsed = time.perf_counter() - start
    return rows, {
        "asset_id": asset.get("asset_id"),
        "path": str(path),
        "status": "ok",
        "asset_type": "video",
        "frames_read": frame_index,
        "rows": len(rows),
        "offline_processing_fps": round(frame_index / elapsed, 3) if elapsed > 0 else None,
    }


def bbox_from_target_feature(target: dict[str, Any]) -> tuple[float, float, float, float] | None:
    width = safe_float(target.get("bbox_width"))
    height = safe_float(target.get("bbox_height"))
    cx = safe_float(target.get("bbox_center_x"))
    cy = safe_float(target.get("bbox_center_y"))
    if width <= 0 or height <= 0:
        return None
    return (cx - width / 2.0, cy - height / 2.0, cx + width / 2.0, cy + height / 2.0)


def extract_sequence_features(asset: dict[str, Any], split: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(asset["path"])
    rows: list[dict[str, Any]] = []
    first_timestamp: datetime | None = None
    first_time: float | None = None
    stillness_started_at: float | None = None
    with path.open("r", encoding="utf-8") as fh:
        for ordinal, line in enumerate(fh):
            if not line.strip():
                continue
            raw = json.loads(line)
            target = raw.get("target_feature") if isinstance(raw.get("target_feature"), dict) else {}
            frame_index = int(raw.get("frame_seq") or raw.get("frame_index") or ordinal)
            parsed_time, first_timestamp = parse_timestamp_seconds(target.get("timestamp") or raw.get("timestamp"), first_timestamp)
            if parsed_time is None:
                parsed_time = frame_index / 30.0
            if first_time is None:
                first_time = parsed_time
            time_sec = max(0.0, parsed_time - first_time)
            frame_width = int(raw.get("frame_width") or 0)
            frame_height = int(raw.get("frame_height") or 0)
            bbox = bbox_from_target_feature(target)
            speed = safe_float(target.get("speed"))
            if speed < 28.0:
                if stillness_started_at is None:
                    stillness_started_at = time_sec
                stillness = time_sec - stillness_started_at
            else:
                stillness_started_at = None
                stillness = 0.0
            pose_available = bool(target.get("pose_available"))
            pose_conf = safe_float(target.get("pose_confidence")) if pose_available else None
            rows.append(
                make_feature_row(
                    asset=asset,
                    split=split,
                    frame_index=frame_index,
                    time_sec=time_sec,
                    track_id=target.get("track_id") or raw.get("track_id") or 1,
                    bbox=bbox,
                    frame_width=frame_width,
                    frame_height=frame_height,
                    center_y_delta=safe_float(target.get("delta_y")),
                    height_delta=None,
                    velocity_y=safe_float(target.get("velocity_y")),
                    speed=speed,
                    track_age_sec=time_sec,
                    stillness_duration_sec=stillness,
                    person_confidence=0.85 if bbox is not None else 0.0,
                    pose_keypoint_count=None,
                    pose_confidence_mean=pose_conf,
                    torso_angle=target.get("torso_angle"),
                    hip_height_ratio=target.get("hip_height_ratio"),
                )
            )
    return rows, {
        "asset_id": asset.get("asset_id"),
        "path": str(path),
        "status": "ok",
        "asset_type": "sequence",
        "rows": len(rows),
        "offline_processing_fps": None,
    }


def extract_asset(asset: dict[str, Any], split: str, frame_stride: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(asset.get("path", ""))
    if path.suffix.lower() == ".jsonl" or asset.get("asset_type") == "sequence":
        return extract_sequence_features(asset, split)
    return extract_video_features(asset, split, frame_stride)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract fast pose fall frame-level features from clean splits.")
    parser.add_argument("--splits-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "splits")
    parser.add_argument("--features-dir", type=Path, default=ROOT / "datasets" / "fast_pose_fall" / "features")
    parser.add_argument("--frame-stride", type=int, default=3)
    args = parser.parse_args()

    args.features_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "frame_stride": max(1, args.frame_stride),
        "splits": {},
        "errors": [],
    }

    schema_path = args.features_dir / "feature_schema_20260622.json"
    schema_path.write_text(json.dumps(feature_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for split in SPLITS:
        split_path = args.splits_dir / f"{split}.jsonl"
        assets = load_split(split_path)
        feature_rows: list[dict[str, Any]] = []
        asset_summaries = []
        for asset in assets:
            if asset.get("label_status") == "pseudo" or asset.get("label_source") == "pseudo":
                continue
            rows, asset_summary = extract_asset(asset, split, max(1, args.frame_stride))
            feature_rows.extend(rows)
            asset_summaries.append(asset_summary)
            if asset_summary.get("status") != "ok":
                summary["errors"].append(asset_summary)
        out_path = args.features_dir / f"features_{split}.jsonl"
        row_count = write_jsonl(out_path, feature_rows)
        summary["splits"][split] = {
            "assets": len(assets),
            "feature_rows": row_count,
            "output": str(out_path),
            "asset_summaries": asset_summaries,
        }

    summary_path = args.features_dir / "feature_extraction_summary_20260622.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["errors"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
