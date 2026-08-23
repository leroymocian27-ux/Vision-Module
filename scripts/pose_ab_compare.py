from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.detection.object_detector import YoloPersonDetector
from app.pose.schemas import PoseResult
from app.pose.yolo_pose_estimator import YoloPoseEstimator
from app.schemas.vision_result import DetectedObject

COCO_CONNECTIONS = [
    (0, 1, "head"),
    (0, 2, "head"),
    (1, 3, "head"),
    (2, 4, "head"),
    (5, 6, "torso"),
    (5, 7, "left_arm"),
    (7, 9, "left_arm"),
    (6, 8, "right_arm"),
    (8, 10, "right_arm"),
    (5, 11, "torso"),
    (6, 12, "torso"),
    (11, 12, "torso"),
    (11, 13, "left_leg"),
    (13, 15, "left_leg"),
    (12, 14, "right_leg"),
    (14, 16, "right_leg"),
]

KEYPOINT_INDEX = {
    "nose": 0,
    "left_eye": 1,
    "right_eye": 2,
    "left_ear": 3,
    "right_ear": 4,
    "left_shoulder": 5,
    "right_shoulder": 6,
    "left_elbow": 7,
    "right_elbow": 8,
    "left_wrist": 9,
    "right_wrist": 10,
    "left_hip": 11,
    "right_hip": 12,
    "left_knee": 13,
    "right_knee": 14,
    "left_ankle": 15,
    "right_ankle": 16,
}

FRAME_MANIFEST = [
    {
        "id": "01_normal_standing",
        "scene": "normal standing",
        "video": "20eab7404c5cac9c3038a059cf6d0bbc.mp4",
        "frame_index": 115,
    },
    {
        "id": "02_forward_bend",
        "scene": "forward bend",
        "video": "a64f9bce58dfda706d4ba830a7749ae2.mp4",
        "frame_index": 3093,
    },
    {
        "id": "03_kneeling",
        "scene": "kneeling",
        "video": "a64f9bce58dfda706d4ba830a7749ae2.mp4",
        "frame_index": 2706,
    },
    {
        "id": "04_sitting_floor",
        "scene": "sitting",
        "video": "574c42749fa162a487f7e3d3e84bb181_raw.mp4",
        "frame_index": 246,
    },
    {
        "id": "05_sitting_occluded",
        "scene": "sitting occluded",
        "video": "574c42749fa162a487f7e3d3e84bb181_raw.mp4",
        "frame_index": 184,
    },
    {
        "id": "06_prone_support",
        "scene": "occluded prone support",
        "video": "574c42749fa162a487f7e3d3e84bb181_raw.mp4",
        "frame_index": 154,
    },
    {
        "id": "07_fall_transition",
        "scene": "fall transition",
        "video": "20eab7404c5cac9c3038a059cf6d0bbc.mp4",
        "frame_index": 193,
    },
    {
        "id": "08_fallen_supine",
        "scene": "fallen supine",
        "video": "87b7d5c9e038702bb20062f873c6a465.mp4",
        "frame_index": 1790,
    },
    {
        "id": "09_floor_recovery",
        "scene": "floor recovery",
        "video": "87b7d5c9e038702bb20062f873c6a465.mp4",
        "frame_index": 2046,
    },
    {
        "id": "10_partial_second_person",
        "scene": "partial second person",
        "video": "ec4c9594a3fee498abcee80566372029.mp4",
        "frame_index": 461,
    },
]


@dataclass
class PipelineFrameResult:
    pipeline: str
    bbox: list[float] | None
    boxes: list[list[float]]
    keypoints: list[dict[str, Any]]
    latency_ms: float
    debug: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline pose A/B comparison for current and historical pipelines.")
    parser.add_argument("--output-dir", default="logs/pose_ab_compare")
    parser.add_argument("--warmup-frames", type=int, default=5)
    args = parser.parse_args()

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    comparator = PoseABComparator(output_dir=output_dir, warmup_frames=args.warmup_frames)
    summary = comparator.run(FRAME_MANIFEST)

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = output_dir / "frame_metrics.csv"
    _write_csv(csv_path, summary["frames"])

    print(json.dumps(summary["result"], ensure_ascii=False, indent=2))
    return 0


class PoseABComparator:
    def __init__(self, *, output_dir: Path, warmup_frames: int) -> None:
        self.output_dir = output_dir
        self.warmup_frames = max(0, int(warmup_frames))

        base_settings = get_settings()
        self.current_settings = replace(
            base_settings,
            detection_enabled=True,
            yolo_pose_model_path="yolov8n-pose.pt",
            yolo_pose_confidence=0.25,
            yolo_pose_imgsz=640,
        )
        self.detector = YoloPersonDetector(self.current_settings)
        self.current_estimator = YoloPoseEstimator(self.current_settings)

        historical_root = Path(r"D:\Program\health(5-12)\pose_detection_model_bundle")
        historical_module = _load_historical_module(
            Path(r"D:\Program\health(5-12)\backend\services\target_pose_service.py")
        )
        self.historical_service = historical_module.TargetPoseService(model_root=historical_root)

    def run(self, manifest: list[dict[str, Any]]) -> dict[str, Any]:
        frame_summaries: list[dict[str, Any]] = []
        score_counts = {"Current": 0, "Historical": 0, "SameBad": 0, "Tie": 0}
        current_latency_values: list[float] = []
        historical_latency_values: list[float] = []

        for item in manifest:
            frame_summary = self._process_frame(item)
            frame_summaries.append(frame_summary)
            current_latency_values.append(frame_summary["current"]["latency_ms"])
            historical_latency_values.append(frame_summary["historical"]["latency_ms"])
            score_counts[frame_summary["winner"]] += 1

        root_cause = self._root_cause(frame_summaries)
        best_candidate = self._best_candidate(score_counts)
        if best_candidate == "Neither":
            recommended_next_step = "Switch to RTMPose or improve camera angle; both offline pipelines remain weak."
        elif best_candidate == "Historical":
            recommended_next_step = "Migrate yolo11n-pose + full-frame pose + smoothing after a controlled rollout."
        else:
            recommended_next_step = "Continue investigating realtime pipeline, overlay, and track binding; offline current crop pipeline is not the main limiter."

        result = {
            "frames_tested": len(frame_summaries),
            "current_pipeline": "PASS" if all(frame["current"]["pipeline_ok"] for frame in frame_summaries) else "FAIL",
            "historical_pipeline": "PASS" if all(frame["historical"]["pipeline_ok"] for frame in frame_summaries) else "FAIL",
            "historical_better_count": score_counts["Historical"],
            "current_better_count": score_counts["Current"],
            "same_bad_count": score_counts["SameBad"],
            "latency_current_avg": round(_mean(current_latency_values), 2),
            "latency_historical_avg": round(_mean(historical_latency_values), 2),
            "best_candidate": best_candidate,
            "root_cause": root_cause,
            "recommended_next_step": recommended_next_step,
        }
        return {
            "result": result,
            "frames": frame_summaries,
        }

    def _process_frame(self, item: dict[str, Any]) -> dict[str, Any]:
        video_path = ROOT / "video" / item["video"]
        frame_index = int(item["frame_index"])
        frame = _read_frame(video_path, frame_index)
        frame_dir = self.output_dir / item["id"]
        frame_dir.mkdir(parents=True, exist_ok=True)

        original_path = frame_dir / "original.jpg"
        cv2.imwrite(str(original_path), frame)

        current = self._run_current(frame)
        historical = self._run_historical(video_path, frame_index)

        reference_boxes = current.boxes if current.boxes else historical.boxes
        reference_bbox = current.bbox or _largest_bbox(reference_boxes)

        current_metrics = _compute_metrics(
            keypoints=current.keypoints,
            selected_bbox=reference_bbox,
            all_boxes=reference_boxes,
            latency_ms=current.latency_ms,
        )
        historical_metrics = _compute_metrics(
            keypoints=historical.keypoints,
            selected_bbox=reference_bbox,
            all_boxes=reference_boxes,
            latency_ms=historical.latency_ms,
        )

        current_overlay = _draw_overlay(
            frame=frame,
            title=f"Current yolov8 crop | {item['scene']}",
            boxes=current.boxes,
            selected_bbox=current.bbox,
            keypoints=current.keypoints,
            color=(70, 220, 70),
            metrics=current_metrics,
        )
        historical_overlay = _draw_overlay(
            frame=frame,
            title=f"Historical yolo11 full-frame | {item['scene']}",
            boxes=reference_boxes,
            selected_bbox=reference_bbox,
            keypoints=historical.keypoints,
            color=(0, 170, 255),
            metrics=historical_metrics,
        )

        current_path = frame_dir / "current_yolov8_crop.jpg"
        historical_path = frame_dir / "historical_yolo11_fullframe.jpg"
        compare_path = frame_dir / "compare_grid.jpg"
        cv2.imwrite(str(current_path), current_overlay)
        cv2.imwrite(str(historical_path), historical_overlay)
        cv2.imwrite(
            str(compare_path),
            _make_compare_grid(
                frame=frame,
                current=current_overlay,
                historical=historical_overlay,
                scene=item["scene"],
                frame_title=f"{item['video']}#{frame_index}",
                current_metrics=current_metrics,
                historical_metrics=historical_metrics,
            ),
        )

        current_score = _pipeline_score(current_metrics)
        historical_score = _pipeline_score(historical_metrics)
        current_good = _pipeline_good(current_metrics)
        historical_good = _pipeline_good(historical_metrics)

        winner = "Tie"
        if not current_good and not historical_good:
            winner = "SameBad"
        elif current_score >= 0.2 and current_score > historical_score + 0.15 and current_good:
            winner = "Current"
        elif historical_score >= 0.2 and historical_score > current_score + 0.15 and historical_good:
            winner = "Historical"

        return {
            "frame_id": item["id"],
            "scene": item["scene"],
            "video": item["video"],
            "frame_index": frame_index,
            "original": str(original_path),
            "current_image": str(current_path),
            "historical_image": str(historical_path),
            "compare_grid": str(compare_path),
            "winner": winner,
            "current": {
                **current_metrics,
                "pipeline_ok": True,
                "bbox": current.bbox,
                "detected_person_count": len(current.boxes),
                "debug": current.debug,
                "score": round(current_score, 4),
            },
            "historical": {
                **historical_metrics,
                "pipeline_ok": True,
                "bbox": reference_bbox,
                "detected_person_count": len(reference_boxes),
                "debug": historical.debug,
                "score": round(historical_score, 4),
            },
        }

    def _run_current(self, frame: np.ndarray) -> PipelineFrameResult:
        started = time.perf_counter()
        objects = self.detector.detect(frame)
        objects = [
            item.model_copy(update={"track_id": index + 1})
            for index, item in enumerate(sorted(objects, key=_area, reverse=True))
        ]
        selected = objects[:1]
        pose_result = self.current_estimator.estimate(frame, selected) if selected else {}
        latency_ms = (time.perf_counter() - started) * 1000

        bbox = selected[0].bbox if selected else None
        pose = pose_result.get(selected[0].track_id) if selected else None
        keypoints = _pose_result_to_points(pose)
        return PipelineFrameResult(
            pipeline="current",
            bbox=bbox,
            boxes=[obj.bbox for obj in objects],
            keypoints=keypoints,
            latency_ms=round(latency_ms, 2),
            debug=self.current_estimator.last_debug,
        )

    def _run_historical(self, video_path: Path, frame_index: int) -> PipelineFrameResult:
        if hasattr(self.historical_service, "_session_states"):
            self.historical_service._session_states = {}
        result: dict[str, Any] | None = None
        window_start = max(0, frame_index - self.warmup_frames)
        cap = cv2.VideoCapture(str(video_path))
        try:
            for index in range(window_start, frame_index + 1):
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, warm_frame = cap.read()
                if not ok or warm_frame is None:
                    continue
                result = self.historical_service.estimate_pose(
                    warm_frame,
                    imgsz=320,
                    conf=0.12,
                    session_id=f"{video_path.stem}:{frame_index}",
                )
        finally:
            cap.release()

        if not result:
            return PipelineFrameResult(
                pipeline="historical",
                bbox=None,
                boxes=[],
                keypoints=[],
                latency_ms=0.0,
                debug={"error": "no_result"},
            )
        pose = result.get("pose") if isinstance(result, dict) else None
        points = pose.get("points") if isinstance(pose, dict) else []
        return PipelineFrameResult(
            pipeline="historical",
            bbox=None,
            boxes=[],
            keypoints=_historical_points(points),
            latency_ms=float(result.get("latency_ms") or 0.0),
            debug={
                "ok": result.get("ok"),
                "error": result.get("error"),
                "model": result.get("model"),
                "quality": pose.get("quality") if isinstance(pose, dict) else None,
            },
        )

    @staticmethod
    def _root_cause(frame_summaries: list[dict[str, Any]]) -> str:
        historical_wins = sum(1 for frame in frame_summaries if frame["winner"] == "Historical")
        current_wins = sum(1 for frame in frame_summaries if frame["winner"] == "Current")
        same_bad = sum(1 for frame in frame_summaries if frame["winner"] == "SameBad")
        if historical_wins >= max(3, current_wins + 2):
            return "Mixed"
        if current_wins >= max(3, historical_wins + 2):
            return "RealtimePipeline"
        if same_bad >= max(3, len(frame_summaries) // 2):
            return "Mixed"
        if any(frame["current"]["cross_person_error"] == "YES" for frame in frame_summaries):
            return "CropStrategy"
        return "Mixed"

    @staticmethod
    def _best_candidate(score_counts: dict[str, int]) -> str:
        if score_counts["SameBad"] >= max(3, score_counts["Historical"] + score_counts["Current"]):
            return "Neither"
        if score_counts["Historical"] > score_counts["Current"]:
            return "Historical"
        if score_counts["Current"] > score_counts["Historical"]:
            return "Current"
        return "Neither"


def _load_historical_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("historical_target_pose_service", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load historical module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_frame(video_path: Path, frame_index: int) -> np.ndarray:
    cap = cv2.VideoCapture(str(video_path))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"failed to read frame {frame_index} from {video_path}")
        return frame
    finally:
        cap.release()


def _pose_result_to_points(pose: PoseResult | None) -> list[dict[str, Any]]:
    if pose is None:
        return []
    points = []
    for index, keypoint in enumerate(pose.keypoints):
        points.append(
            {
                "index": index,
                "name": keypoint.name,
                "x": float(keypoint.x),
                "y": float(keypoint.y),
                "score": float(keypoint.confidence),
            }
        )
    return points


def _historical_points(points: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(points, list):
        return []
    return [
        {
            "index": int(item.get("index", index)),
            "name": str(item.get("name", f"kp_{index}")),
            "x": float(item.get("x", 0.0)),
            "y": float(item.get("y", 0.0)),
            "score": float(item.get("score", 0.0)),
        }
        for index, item in enumerate(points)
    ]


def _compute_metrics(
    *,
    keypoints: list[dict[str, Any]],
    selected_bbox: list[float] | None,
    all_boxes: list[list[float]],
    latency_ms: float,
) -> dict[str, Any]:
    visible = [point for point in keypoints if float(point.get("score", 0.0)) >= 0.2]
    visible_ratio = len(visible) / 17.0
    avg_conf = _mean([float(point.get("score", 0.0)) for point in visible])
    pose_bbox = _points_bbox(visible)

    hip_valid = _group_valid(visible, ("left_hip", "right_hip"))
    knee_valid = _group_valid(visible, ("left_knee", "right_knee"))
    ankle_valid = _group_valid(visible, ("left_ankle", "right_ankle"))
    torso_valid = _torso_valid(visible)

    obvious_misalignment = "NO"
    cross_person_error = "NO"
    inside_ratio = None
    pose_iou = None

    if selected_bbox and pose_bbox:
        expanded = _expand_bbox(selected_bbox, 0.1)
        inside_ratio = _inside_ratio(visible, expanded)
        pose_iou = _iou(pose_bbox, selected_bbox)
        if len(visible) < 5 or inside_ratio < 0.55 or pose_iou < 0.08:
            obvious_misalignment = "YES"
        if len(all_boxes) >= 2:
            selected_index = _nearest_box_index(_bbox_center(selected_bbox), all_boxes)
            pose_center = _bbox_center(pose_bbox)
            pose_index = _nearest_box_index(pose_center, all_boxes)
            if pose_index is not None and selected_index is not None and pose_index != selected_index:
                cross_person_error = "YES"
    elif len(visible) < 5:
        obvious_misalignment = "YES"

    return {
        "keypoint_count": len(visible),
        "avg_confidence": round(avg_conf, 4),
        "hip_valid": hip_valid,
        "knee_valid": knee_valid,
        "ankle_valid": ankle_valid,
        "torso_valid": torso_valid,
        "visible_keypoint_ratio": round(visible_ratio, 4),
        "obvious_misalignment": obvious_misalignment,
        "cross_person_error": cross_person_error,
        "latency_ms": round(float(latency_ms), 2),
        "pose_bbox": [round(value, 2) for value in pose_bbox] if pose_bbox else None,
        "bbox_inside_ratio": round(inside_ratio, 4) if inside_ratio is not None else None,
        "bbox_iou": round(pose_iou, 4) if pose_iou is not None else None,
    }


def _draw_overlay(
    *,
    frame: np.ndarray,
    title: str,
    boxes: list[list[float]],
    selected_bbox: list[float] | None,
    keypoints: list[dict[str, Any]],
    color: tuple[int, int, int],
    metrics: dict[str, Any],
) -> np.ndarray:
    canvas = frame.copy()
    for bbox in boxes:
        x1, y1, x2, y2 = [int(v) for v in bbox]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (180, 180, 180), 1)
    if selected_bbox:
        x1, y1, x2, y2 = [int(v) for v in selected_bbox]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)

    by_index = {int(point["index"]): point for point in keypoints if float(point.get("score", 0.0)) >= 0.2}
    for a, b, _part in COCO_CONNECTIONS:
        point_a = by_index.get(a)
        point_b = by_index.get(b)
        if point_a is None or point_b is None:
            continue
        cv2.line(
            canvas,
            (int(point_a["x"]), int(point_a["y"])),
            (int(point_b["x"]), int(point_b["y"])),
            color,
            2,
            cv2.LINE_AA,
        )
    for point in by_index.values():
        cv2.circle(canvas, (int(point["x"]), int(point["y"])), 3, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(canvas, (int(point["x"]), int(point["y"])), 4, color, 1, cv2.LINE_AA)

    cv2.rectangle(canvas, (10, 10), (560, 96), (22, 22, 22), -1)
    cv2.putText(canvas, title, (20, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(
        canvas,
        (
            f"kp={metrics['keypoint_count']} conf={metrics['avg_confidence']:.2f} "
            f"vis={metrics['visible_keypoint_ratio']:.2f} latency={metrics['latency_ms']:.1f}ms"
        ),
        (20, 62),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        f"misalign={metrics['obvious_misalignment']} cross_person={metrics['cross_person_error']}",
        (20, 88),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    return canvas


def _make_compare_grid(
    *,
    frame: np.ndarray,
    current: np.ndarray,
    historical: np.ndarray,
    scene: str,
    frame_title: str,
    current_metrics: dict[str, Any],
    historical_metrics: dict[str, Any],
) -> np.ndarray:
    thumb_size = (640, 360)
    original = cv2.resize(frame, thumb_size)
    current = cv2.resize(current, thumb_size)
    historical = cv2.resize(historical, thumb_size)
    text_panel = np.full((thumb_size[1], thumb_size[0], 3), 245, dtype=np.uint8)

    lines = [
        f"Scene: {scene}",
        f"Frame: {frame_title}",
        "",
        "Current",
        (
            f"kp={current_metrics['keypoint_count']} conf={current_metrics['avg_confidence']:.2f} "
            f"hip={current_metrics['hip_valid']} knee={current_metrics['knee_valid']} "
            f"ankle={current_metrics['ankle_valid']} torso={current_metrics['torso_valid']}"
        ),
        (
            f"vis={current_metrics['visible_keypoint_ratio']:.2f} "
            f"misalign={current_metrics['obvious_misalignment']} "
            f"cross={current_metrics['cross_person_error']} "
            f"lat={current_metrics['latency_ms']:.1f}ms"
        ),
        "",
        "Historical",
        (
            f"kp={historical_metrics['keypoint_count']} conf={historical_metrics['avg_confidence']:.2f} "
            f"hip={historical_metrics['hip_valid']} knee={historical_metrics['knee_valid']} "
            f"ankle={historical_metrics['ankle_valid']} torso={historical_metrics['torso_valid']}"
        ),
        (
            f"vis={historical_metrics['visible_keypoint_ratio']:.2f} "
            f"misalign={historical_metrics['obvious_misalignment']} "
            f"cross={historical_metrics['cross_person_error']} "
            f"lat={historical_metrics['latency_ms']:.1f}ms"
        ),
    ]
    y = 40
    for line in lines:
        cv2.putText(text_panel, line, (18, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (30, 30, 30), 1, cv2.LINE_AA)
        y += 34

    top = cv2.hconcat([original, current])
    bottom = cv2.hconcat([historical, text_panel])
    return cv2.vconcat([top, bottom])


def _pipeline_score(metrics: dict[str, Any]) -> float:
    return (
        float(metrics["visible_keypoint_ratio"]) * 1.8
        + float(metrics["avg_confidence"])
        + (0.2 if metrics["hip_valid"] else 0.0)
        + (0.2 if metrics["knee_valid"] else 0.0)
        + (0.2 if metrics["ankle_valid"] else 0.0)
        + (0.2 if metrics["torso_valid"] else 0.0)
        - (1.2 if metrics["obvious_misalignment"] == "YES" else 0.0)
        - (1.0 if metrics["cross_person_error"] == "YES" else 0.0)
    )


def _pipeline_good(metrics: dict[str, Any]) -> bool:
    return (
        metrics["obvious_misalignment"] == "NO"
        and metrics["keypoint_count"] >= 12
        and float(metrics["visible_keypoint_ratio"]) >= 0.7
        and metrics["torso_valid"]
    )


def _group_valid(points: list[dict[str, Any]], names: tuple[str, ...]) -> bool:
    visible_names = {str(point.get("name")) for point in points}
    return any(name in visible_names for name in names)


def _torso_valid(points: list[dict[str, Any]]) -> bool:
    torso_names = {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}
    visible_names = {str(point.get("name")) for point in points}
    return len(torso_names & visible_names) >= 3


def _points_bbox(points: list[dict[str, Any]]) -> list[float] | None:
    if not points:
        return None
    xs = [float(point["x"]) for point in points]
    ys = [float(point["y"]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _inside_ratio(points: list[dict[str, Any]], bbox: list[float]) -> float:
    x1, y1, x2, y2 = bbox
    inside = 0
    for point in points:
        x = float(point["x"])
        y = float(point["y"])
        if x1 <= x <= x2 and y1 <= y <= y2:
            inside += 1
    return inside / max(1, len(points))


def _expand_bbox(bbox: list[float], ratio: float) -> list[float]:
    x1, y1, x2, y2 = bbox
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    return [
        x1 - width * ratio,
        y1 - height * ratio,
        x2 + width * ratio,
        y2 + height * ratio,
    ]


def _bbox_center(bbox: list[float]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5)


def _nearest_box_index(center: tuple[float, float], boxes: list[list[float]]) -> int | None:
    if not boxes:
        return None
    best_index = None
    best_distance = float("inf")
    for index, bbox in enumerate(boxes):
        other_center = _bbox_center(bbox)
        distance = math.hypot(center[0] - other_center[0], center[1] - other_center[1])
        if distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _largest_bbox(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return max(boxes, key=lambda bbox: max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1]))


def _area(item: DetectedObject) -> float:
    x1, y1, x2, y2 = item.bbox
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _write_csv(path: Path, frames: list[dict[str, Any]]) -> None:
    columns = [
        "frame_id",
        "scene",
        "video",
        "frame_index",
        "winner",
        "current_keypoint_count",
        "current_avg_confidence",
        "current_visible_keypoint_ratio",
        "current_obvious_misalignment",
        "current_cross_person_error",
        "current_latency_ms",
        "historical_keypoint_count",
        "historical_avg_confidence",
        "historical_visible_keypoint_ratio",
        "historical_obvious_misalignment",
        "historical_cross_person_error",
        "historical_latency_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for frame in frames:
            writer.writerow(
                {
                    "frame_id": frame["frame_id"],
                    "scene": frame["scene"],
                    "video": frame["video"],
                    "frame_index": frame["frame_index"],
                    "winner": frame["winner"],
                    "current_keypoint_count": frame["current"]["keypoint_count"],
                    "current_avg_confidence": frame["current"]["avg_confidence"],
                    "current_visible_keypoint_ratio": frame["current"]["visible_keypoint_ratio"],
                    "current_obvious_misalignment": frame["current"]["obvious_misalignment"],
                    "current_cross_person_error": frame["current"]["cross_person_error"],
                    "current_latency_ms": frame["current"]["latency_ms"],
                    "historical_keypoint_count": frame["historical"]["keypoint_count"],
                    "historical_avg_confidence": frame["historical"]["avg_confidence"],
                    "historical_visible_keypoint_ratio": frame["historical"]["visible_keypoint_ratio"],
                    "historical_obvious_misalignment": frame["historical"]["obvious_misalignment"],
                    "historical_cross_person_error": frame["historical"]["cross_person_error"],
                    "historical_latency_ms": frame["historical"]["latency_ms"],
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
