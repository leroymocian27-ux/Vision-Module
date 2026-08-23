from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from threading import RLock
from typing import Any

import cv2
import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.schemas import PoseKeypoint, PoseResult
from app.pose.yolo_pose_estimator import COCO_KEYPOINT_NAMES
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)
POSE_VALID_CONFIDENCE_THRESHOLD = 0.2
POSE_EDGE_COORD_THRESHOLD = 1.0
POSE_EDGE_UPPER_BODY_CONFIDENCE_THRESHOLD = 0.97
LOWER_BODY_KEYPOINT_NAMES = {
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
}
EDGE_TRUSTED_UPPER_BODY_KEYPOINT_NAMES = {
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
}


class Branch4LegacyPoseEstimator:
    """Branch4-style target-only crop pose estimator."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._last_error: str | None = None
        self._last_debug: dict[str, object] = {}
        self._last_debug_by_track: dict[int, dict[str, object]] = {}
        self._load_lock = RLock()
        self._session_states: dict[str, dict[str, Any]] = {}
        self._max_state_age_ms = 1600
        self._resolved_model_path: str | None = None
        self._load()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_debug(self) -> dict[str, object]:
        return dict(self._last_debug)

    @property
    def last_debug_by_track(self) -> dict[int, dict[str, object]]:
        return {track_id: dict(debug) for track_id, debug in self._last_debug_by_track.items()}

    @property
    def resolved_model_path(self) -> str | None:
        return self._resolved_model_path

    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        if self._model is None:
            self._load()
        if self._model is None:
            raise RuntimeError(f"branch4 legacy pose model unavailable: {self._last_error}")

        target = self._select_target_object(objects)
        if target is None or target.track_id is None:
            self._last_debug = {
                "selected_track_id": None,
                "rejected_reason": "no_pose_targets",
                "model_path": self._resolved_model_path,
            }
            self._last_debug_by_track = {}
            return {}

        crop_info = self._crop_target_roi(frame, target.bbox)
        if crop_info is None:
            self._last_debug = {
                "selected_track_id": int(target.track_id),
                "rejected_reason": "invalid_crop",
                "model_path": self._resolved_model_path,
            }
            self._last_debug_by_track = {
                int(target.track_id): dict(self._last_debug),
            }
            return {}
        crop, offset_x, offset_y, roi_bbox = crop_info

        kwargs = {
            "conf": self.settings.branch4_pose_confidence,
            "imgsz": self.settings.branch4_pose_imgsz,
            "verbose": False,
        }
        if self.settings.yolo11_pose_device:
            kwargs["device"] = self.settings.yolo11_pose_device
        if (
            self.settings.branch4_pose_half
            and self.settings.yolo11_pose_device
            and "cuda" in self.settings.yolo11_pose_device.lower()
        ):
            kwargs["half"] = True

        predictions = self._model.predict(crop, **kwargs)
        if not predictions:
            return self._reject_target(target, roi_bbox, "no_predictions")

        result = predictions[0]
        keypoints = getattr(result, "keypoints", None)
        if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
            return self._reject_target(target, roi_bbox, "no_keypoints")

        xy = keypoints.xy.cpu().numpy()[0]
        conf = keypoints.conf.cpu().numpy()[0] if keypoints.conf is not None else np.ones((xy.shape[0],), dtype=np.float32)
        raw_points = self._build_points(
            xy=xy,
            conf=conf,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        points = self._smooth_points(track_id=int(target.track_id), points=raw_points, bbox=target.bbox)
        filtered_points, dropped_points, dropped_reasons = self._filter_valid_points(
            points,
            frame_width=frame.shape[1],
            frame_height=frame.shape[0],
        )
        if not filtered_points:
            return self._reject_target(
                target,
                roi_bbox,
                "no_valid_keypoints",
                raw_points=points,
                dropped_points=dropped_points,
                dropped_reasons=dropped_reasons,
            )

        pose_bbox = self._pose_bounds(filtered_points)
        skeleton_confidence = self._skeleton_confidence(filtered_points)

        debug = {
            "selected_track_id": int(target.track_id),
            "rejected_reason": None,
            "pose_track_match_score": 1.0,
            "pose_bounds": pose_bbox,
            "pose_bbox": pose_bbox,
            "skeleton_confidence": skeleton_confidence,
            "model_path": self._resolved_model_path,
            "source_bbox": [round(float(value), 2) for value in target.bbox],
            "roi_bbox": roi_bbox,
            "mode": "target-only crop pose",
            "raw_keypoints": self._debug_points(points),
            "pose_bounds_input_points": self._debug_points(filtered_points),
            "visible_keypoint_count": len(filtered_points),
            "filtered_keypoints_count": len(filtered_points),
            "dropped_keypoints_count": len(dropped_points),
            "dropped_reasons": dict(dropped_reasons),
            "dropped_keypoints": self._debug_dropped_points(dropped_points),
        }
        self._last_debug = debug
        self._last_debug_by_track = {int(target.track_id): dict(debug)}
        return {
            int(target.track_id): PoseResult(
                track_id=int(target.track_id),
                source_track_id=int(target.track_id),
                source_bbox=[round(float(value), 2) for value in target.bbox],
                pose_bbox=pose_bbox,
                pose_track_match_score=1.0,
                keypoints=[
                    PoseKeypoint(
                        name=str(point["name"]),
                        x=round(float(point["x"]), 2),
                        y=round(float(point["y"]), 2),
                        confidence=round(float(point["score"]), 4),
                    )
                    for point in filtered_points
                ],
                skeleton_confidence=skeleton_confidence,
                visible_keypoint_count=len(filtered_points),
                filtered_keypoints_count=len(filtered_points),
                dropped_keypoints_count=len(dropped_points),
                dropped_reasons=dict(dropped_reasons),
            )
        }

    def _reject_target(
        self,
        target: DetectedObject,
        roi_bbox: list[float] | None,
        reason: str,
        *,
        raw_points: list[dict[str, Any]] | None = None,
        dropped_points: list[dict[str, Any]] | None = None,
        dropped_reasons: dict[str, int] | None = None,
    ) -> dict[int, PoseResult]:
        debug = {
            "selected_track_id": int(target.track_id) if target.track_id is not None else None,
            "rejected_reason": reason,
            "pose_track_match_score": None,
            "pose_bounds": None,
            "pose_bbox": None,
            "skeleton_confidence": None,
            "model_path": self._resolved_model_path,
            "source_bbox": [round(float(value), 2) for value in target.bbox],
            "roi_bbox": roi_bbox,
            "mode": "target-only crop pose",
            "raw_keypoints": self._debug_points(raw_points or []),
            "pose_bounds_input_points": [],
            "visible_keypoint_count": 0,
            "filtered_keypoints_count": 0,
            "dropped_keypoints_count": len(dropped_points or []),
            "dropped_reasons": dict(dropped_reasons or {}),
            "dropped_keypoints": self._debug_dropped_points(dropped_points or []),
        }
        self._last_debug = debug
        if target.track_id is not None:
            self._last_debug_by_track = {int(target.track_id): dict(debug)}
        else:
            self._last_debug_by_track = {}
        return {}

    def _load(self) -> None:
        with self._load_lock:
            candidates = self._model_candidates()
            errors: list[str] = []
            try:
                from ultralytics import YOLO

                for model_path in candidates:
                    try:
                        self._model = YOLO(model_path)
                        self._resolved_model_path = str(Path(model_path).resolve())
                        self._last_error = None
                        logger.info("branch4_legacy_pose_loaded model=%s", self._resolved_model_path)
                        return
                    except Exception as exc:
                        errors.append(f"{model_path}: {exc}")
                self._model = None
                self._last_error = " | ".join(errors) if errors else "no branch4 legacy pose model candidates"
                logger.error("branch4_legacy_pose_load_failed error=%s", self._last_error)
            except Exception as exc:
                self._model = None
                self._last_error = str(exc)
                logger.error("branch4_legacy_pose_load_failed error=%s", exc)

    def _model_candidates(self) -> list[str]:
        configured = (self.settings.yolo11_pose_model_path or "").strip()
        ordered = [
            configured,
            "yolo11n-pose.pt",
            str((Path.cwd() / "yolo11n-pose.pt").resolve()),
            r"D:\Program\health(5-12)\pose_detection_model_bundle\yolo11n-pose.pt",
            r"D:\Program\health-main(6-6)\410health\pose_detection_model_bundle\yolo11n-pose.pt",
            r"D:\Program\410health_release\pose_detection_model_bundle\yolo11n-pose.pt",
            "yolo11s-pose.pt",
        ]
        seen: set[str] = set()
        candidates: list[str] = []
        for item in ordered:
            if not item:
                continue
            normalized = str(Path(item))
            if normalized in seen:
                continue
            seen.add(normalized)
            path = Path(item)
            if path.exists() or (not path.is_absolute() and len(path.parts) == 1):
                candidates.append(str(path))
        return candidates

    @staticmethod
    def _select_target_object(objects: list[DetectedObject]) -> DetectedObject | None:
        people = [item for item in objects if item.track_id is not None and item.label == "person"]
        if not people:
            return None
        for item in people:
            if item.is_target:
                return item
        return max(people, key=lambda item: Branch4LegacyPoseEstimator._bbox_area(item.bbox))

    def _crop_target_roi(
        self,
        frame: np.ndarray,
        bbox: list[float],
    ) -> tuple[np.ndarray, int, int, list[float]] | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        bbox_w = max(1.0, float(x2) - float(x1))
        bbox_h = max(1.0, float(y2) - float(y1))
        pad_x = bbox_w * self.settings.branch4_pose_crop_padding_ratio
        pad_y = bbox_h * self.settings.branch4_pose_crop_padding_ratio
        left = max(0, int(np.floor(float(x1) - pad_x)))
        top = max(0, int(np.floor(float(y1) - pad_y)))
        right = min(width, int(np.ceil(float(x2) + pad_x)))
        bottom = min(height, int(np.ceil(float(y2) + pad_y)))
        if right <= left or bottom <= top:
            return None
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return None
        roi = cv2.copyMakeBorder(crop, 0, 0, 0, 0, cv2.BORDER_CONSTANT)
        return roi, left, top, [float(left), float(top), float(right), float(bottom)]

    def _build_points(
        self,
        *,
        xy: np.ndarray,
        conf: np.ndarray,
        offset_x: int,
        offset_y: int,
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for index, (point, score) in enumerate(zip(xy, conf)):
            name = COCO_KEYPOINT_NAMES[index] if index < len(COCO_KEYPOINT_NAMES) else f"kp_{index}"
            points.append(
                {
                    "index": index,
                    "name": name,
                    "x": round(float(point[0]) + offset_x, 1),
                    "y": round(float(point[1]) + offset_y, 1),
                    "score": round(float(score), 4),
                    "tracked": False,
                    "estimated": False,
                }
            )
        return points

    def is_valid_pose_point(
        self,
        point: dict[str, Any],
        *,
        frame_width: int,
        frame_height: int,
    ) -> tuple[bool, str | None]:
        x = float(point.get("x") or 0.0)
        y = float(point.get("y") or 0.0)
        score = float(point.get("score") or 0.0)
        name = str(point.get("name") or "")

        if not np.isfinite(x) or not np.isfinite(y) or not np.isfinite(score):
            return False, "invalid_numeric"
        if score < POSE_VALID_CONFIDENCE_THRESHOLD:
            if name in LOWER_BODY_KEYPOINT_NAMES:
                return False, "low_confidence_lower_body"
            return False, "low_confidence"
        if x < 0.0 or y < 0.0 or x > float(frame_width) or y > float(frame_height):
            return False, "out_of_frame"

        touches_edge = (
            x <= POSE_EDGE_COORD_THRESHOLD
            or y <= POSE_EDGE_COORD_THRESHOLD
            or x >= max(0.0, float(frame_width) - POSE_EDGE_COORD_THRESHOLD)
            or y >= max(0.0, float(frame_height) - POSE_EDGE_COORD_THRESHOLD)
        )
        if touches_edge:
            if name in EDGE_TRUSTED_UPPER_BODY_KEYPOINT_NAMES and score >= POSE_EDGE_UPPER_BODY_CONFIDENCE_THRESHOLD:
                return True, None
            return False, "edge_point"
        return True, None

    def _filter_valid_points(
        self,
        points: list[dict[str, Any]],
        *,
        frame_width: int,
        frame_height: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
        filtered: list[dict[str, Any]] = []
        dropped: list[dict[str, Any]] = []
        dropped_reasons: dict[str, int] = {}
        for point in points:
            valid, reason = self.is_valid_pose_point(
                point,
                frame_width=frame_width,
                frame_height=frame_height,
            )
            if valid:
                filtered.append(point)
                continue
            reason_text = reason or "invalid_point"
            dropped_reasons[reason_text] = dropped_reasons.get(reason_text, 0) + 1
            dropped.append(
                {
                    **point,
                    "drop_reason": reason_text,
                }
            )
        return filtered, dropped, dropped_reasons

    def _smooth_points(
        self,
        *,
        track_id: int,
        points: list[dict[str, Any]],
        bbox: list[float],
    ) -> list[dict[str, Any]]:
        if not self.settings.yolo11_pose_smoothing:
            return points

        now_ms = int(time.perf_counter() * 1000)
        state_key = f"track:{track_id}"
        previous = self._session_states.get(state_key)
        if previous and (now_ms - int(previous.get("ts_ms", 0))) > self._max_state_age_ms:
            previous = None

        bbox_diag = max(80.0, float(np.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])))
        max_jump = bbox_diag * self.settings.yolo11_pose_max_jump_ratio
        smoothed: list[dict[str, Any]] = []
        prev_points = previous.get("points") if previous else None

        for point in points:
            idx = int(point["index"])
            score = float(point.get("score") or 0.0)
            x = float(point.get("x") or 0.0)
            y = float(point.get("y") or 0.0)
            prev = None
            if isinstance(prev_points, list):
                prev = next((item for item in prev_points if int(item.get("index", -1)) == idx), None)

            estimated = False
            tracked = False
            if prev is not None:
                px = float(prev.get("x") or x)
                py = float(prev.get("y") or y)
                prev_score = float(prev.get("score") or 0.0)
                jump = float(np.hypot(x - px, y - py))
                if score < 0.18 <= prev_score:
                    x, y = px, py
                    score = max(0.12, min(0.32, prev_score * 0.82))
                    estimated = True
                    tracked = True
                elif jump > max_jump and prev_score >= 0.28:
                    blend = 0.72
                    x = px * blend + x * (1.0 - blend)
                    y = py * blend + y * (1.0 - blend)
                    score = min(score, max(0.24, prev_score * 0.92))
                    tracked = True
                elif score >= 0.18:
                    alpha = 0.55 if score >= 0.5 else 0.38
                    x = px * (1.0 - alpha) + x * alpha
                    y = py * (1.0 - alpha) + y * alpha
                    tracked = True

            smoothed.append(
                {
                    **point,
                    "x": round(x, 1),
                    "y": round(y, 1),
                    "score": round(max(0.0, min(1.0, score)), 4),
                    "tracked": tracked,
                    "estimated": estimated,
                }
            )

        history = deque(maxlen=6)
        if previous and isinstance(previous.get("history"), deque):
            history = previous["history"]
        history.append(smoothed)
        self._session_states[state_key] = {
            "ts_ms": now_ms,
            "points": smoothed,
            "history": history,
        }
        return smoothed

    @staticmethod
    def _pose_bounds(points: list[dict[str, Any]]) -> list[float]:
        visible = [(float(point["x"]), float(point["y"])) for point in points]
        if not visible:
            return [0.0, 0.0, 0.0, 0.0]
        xs = [item[0] for item in visible]
        ys = [item[1] for item in visible]
        return [
            round(min(xs), 2),
            round(min(ys), 2),
            round(max(xs), 2),
            round(max(ys), 2),
        ]

    @staticmethod
    def _skeleton_confidence(points: list[dict[str, Any]]) -> float:
        scores = [float(point.get("score") or 0.0) for point in points]
        if not scores:
            return 0.0
        return round(float(sum(scores) / len(scores)), 4)

    @staticmethod
    def _debug_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "index": int(point.get("index", -1)),
                "name": str(point.get("name") or ""),
                "x": round(float(point.get("x") or 0.0), 2),
                "y": round(float(point.get("y") or 0.0), 2),
                "score": round(float(point.get("score") or 0.0), 4),
                "tracked": bool(point.get("tracked", False)),
                "estimated": bool(point.get("estimated", False)),
            }
            for point in points
        ]

    @staticmethod
    def _debug_dropped_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "index": int(point.get("index", -1)),
                "name": str(point.get("name") or ""),
                "x": round(float(point.get("x") or 0.0), 2),
                "y": round(float(point.get("y") or 0.0), 2),
                "score": round(float(point.get("score") or 0.0), 4),
                "drop_reason": str(point.get("drop_reason") or ""),
            }
            for point in points
        ]

    @staticmethod
    def _bbox_area(bbox: list[float]) -> float:
        return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
