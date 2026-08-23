from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.schemas import PoseKeypoint, PoseResult
from app.pose.yolo_pose_estimator import COCO_KEYPOINT_NAMES
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)
LOWER_BODY_KEYPOINT_NAMES = {"left_knee", "right_knee", "left_ankle", "right_ankle"}
LOWER_BODY_MIN_CONFIDENCE = 0.35


@dataclass
class LegacyPoseCandidate:
    index: int
    keypoints: np.ndarray
    confidences: np.ndarray
    pose_bbox: list[float]
    skeleton_confidence: float
    box_confidence: float


class Yolo11LegacyPoseEstimator:
    """Historical staging pose estimator.

    This intentionally keeps the old "full-frame YOLO11 pose + temporal
    smoothing" behavior behind an explicit provider switch without replacing the
    current crop-based provider.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._last_error: str | None = None
        self._last_debug: dict[str, object] = {}
        self._last_debug_by_track: dict[int, dict[str, object]] = {}
        self._load_lock = RLock()
        self._session_states: dict[str, dict[str, Any]] = {}
        self._last_track_keys: set[str] = set()
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
            raise RuntimeError(f"yolo11 legacy pose model unavailable: {self._last_error}")

        tracked_objects = [item for item in objects if item.track_id is not None and item.label == "person"]
        if not tracked_objects:
            self._last_debug = {
                "selected_track_id": None,
                "rejected_reason": "no_pose_targets",
                "model_path": self._resolved_model_path,
            }
            self._last_debug_by_track = {}
            return {}

        kwargs = {
            "conf": self.settings.yolo11_pose_confidence,
            "imgsz": self.settings.yolo11_pose_imgsz,
            "verbose": False,
        }
        if self.settings.yolo11_pose_device:
            kwargs["device"] = self.settings.yolo11_pose_device
        if (
            self.settings.yolo11_pose_half
            and self.settings.yolo11_pose_device
            and "cuda" in self.settings.yolo11_pose_device.lower()
        ):
            kwargs["half"] = True

        predictions = self._model.predict(frame, **kwargs)
        if not predictions:
            self._last_debug = {
                "selected_track_id": None,
                "rejected_reason": "no_predictions",
                "model_path": self._resolved_model_path,
            }
            self._last_debug_by_track = {}
            return {}

        result = predictions[0]
        candidates = self._collect_candidates(result)
        if not candidates:
            self._last_debug = {
                "selected_track_id": None,
                "rejected_reason": "no_keypoints",
                "model_path": self._resolved_model_path,
            }
            self._last_debug_by_track = {}
            return {}

        matched = self._match_candidates(tracked_objects, candidates)
        self._prune_session_state(tracked_objects)
        pose_by_track: dict[int, PoseResult] = {}
        debug_by_track: dict[int, dict[str, object]] = {}
        primary_debug: dict[str, object] | None = None
        for item in tracked_objects:
            track_id = int(item.track_id)
            match = matched.get(track_id)
            if match is None:
                debug = {
                    "selected_track_id": track_id,
                    "rejected_reason": "pose_track_match_low_score",
                    "pose_track_match_score": 0.0,
                    "pose_bounds": None,
                    "candidate_iou": 0.0,
                    "keypoint_inside_bbox_ratio": 0.0,
                    "keypoint_inside_source_bbox_ratio": 0.0,
                    "torso_inside_bbox": False,
                    "skeleton_confidence": None,
                    "pose_match_iou": 0.0,
                    "pose_match_center_distance_ratio": None,
                    "model_path": self._resolved_model_path,
                }
                debug_by_track[track_id] = debug
                if item.is_target and primary_debug is None:
                    primary_debug = debug
                continue

            candidate, match_debug = match
            smoothed_points = self._smooth_points(
                track_id=track_id,
                points=self._candidate_points(candidate),
                bbox=item.bbox,
            )
            pose_by_track[track_id] = PoseResult(
                track_id=track_id,
                pose_bbox=[round(value, 2) for value in candidate.pose_bbox],
                pose_track_match_score=round(float(match_debug["pose_track_match_score"]), 4),
                keypoints=[
                    PoseKeypoint(
                        name=str(point["name"]),
                        x=round(float(point["x"]), 2),
                        y=round(float(point["y"]), 2),
                        confidence=round(float(point["score"]), 4),
                    )
                    for point in smoothed_points
                ],
                skeleton_confidence=round(float(candidate.skeleton_confidence), 4),
            )
            debug = {
                "selected_track_id": track_id,
                "rejected_reason": None,
                "pose_track_match_score": round(float(match_debug["pose_track_match_score"]), 4),
                "pose_match_iou": round(float(match_debug["pose_match_iou"]), 4),
                "pose_match_center_distance_ratio": round(float(match_debug["pose_match_center_distance_ratio"]), 4),
                "pose_bounds": [round(value, 2) for value in candidate.pose_bbox],
                "candidate_iou": round(float(match_debug["pose_match_iou"]), 4),
                "keypoint_inside_bbox_ratio": round(float(match_debug["keypoint_inside_bbox_ratio"]), 4),
                "keypoint_inside_source_bbox_ratio": round(float(match_debug["keypoint_inside_bbox_ratio"]), 4),
                "torso_inside_bbox": bool(match_debug["torso_inside_bbox"]),
                "skeleton_confidence": round(float(candidate.skeleton_confidence), 4),
                "model_path": self._resolved_model_path,
            }
            debug_by_track[track_id] = debug
            if primary_debug is None or item.is_target:
                primary_debug = debug

        self._last_debug_by_track = debug_by_track
        self._last_debug = primary_debug or {
            "selected_track_id": None,
            "rejected_reason": "pose_track_match_low_score",
            "model_path": self._resolved_model_path,
        }
        return pose_by_track

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
                        logger.info("yolo11_legacy_pose_loaded model=%s", self._resolved_model_path)
                        return
                    except Exception as exc:
                        errors.append(f"{model_path}: {exc}")
                self._model = None
                self._last_error = " | ".join(errors) if errors else "no yolo11 legacy pose model candidates"
                logger.error("yolo11_legacy_pose_load_failed error=%s", self._last_error)
            except Exception as exc:
                self._model = None
                self._last_error = str(exc)
                logger.error("yolo11_legacy_pose_load_failed error=%s", exc)

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

    def _collect_candidates(self, result) -> list[LegacyPoseCandidate]:
        keypoints = getattr(result, "keypoints", None)
        if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
            return []

        boxes = getattr(result, "boxes", None)
        box_conf = boxes.conf.cpu().numpy() if boxes is not None and boxes.conf is not None else None
        xy_all = keypoints.xy.cpu().numpy()
        conf_all = keypoints.conf.cpu().numpy() if keypoints.conf is not None else np.ones(xy_all.shape[:2])

        candidates: list[LegacyPoseCandidate] = []
        for index, (xy, conf) in enumerate(zip(xy_all, conf_all)):
            valid = conf >= max(0.01, self.settings.yolo11_pose_confidence * 0.35)
            valid &= ~((xy[:, 0] <= 1.0) & (xy[:, 1] <= 1.0))
            valid_points = xy[valid]
            valid_conf = conf[valid]
            if len(valid_points) < 5:
                continue
            pose_bbox = [
                float(np.min(valid_points[:, 0])),
                float(np.min(valid_points[:, 1])),
                float(np.max(valid_points[:, 0])),
                float(np.max(valid_points[:, 1])),
            ]
            candidates.append(
                LegacyPoseCandidate(
                    index=index,
                    keypoints=xy,
                    confidences=conf,
                    pose_bbox=pose_bbox,
                    skeleton_confidence=float(np.mean(valid_conf)) if len(valid_conf) else 0.0,
                    box_confidence=float(box_conf[index]) if box_conf is not None and index < len(box_conf) else 0.0,
                )
            )
        return candidates

    def _match_candidates(
        self,
        objects: list[DetectedObject],
        candidates: list[LegacyPoseCandidate],
    ) -> dict[int, tuple[LegacyPoseCandidate, dict[str, float | bool]]]:
        unmatched = set(range(len(candidates)))
        ordered_objects = sorted(
            objects,
            key=lambda item: (0 if item.is_target else 1, -self._bbox_area(item.bbox)),
        )
        matched: dict[int, tuple[LegacyPoseCandidate, dict[str, float | bool]]] = {}
        for item in ordered_objects:
            track_id = int(item.track_id)
            best_index: int | None = None
            best_score = -1.0
            best_debug: dict[str, float | bool] | None = None
            for candidate_index in list(unmatched):
                candidate = candidates[candidate_index]
                debug = self._match_debug(candidate, item.bbox)
                score = float(debug["pose_track_match_score"])
                if score > best_score:
                    best_score = score
                    best_index = candidate_index
                    best_debug = debug
            if best_index is None or best_debug is None:
                continue
            if not self._accept_match(best_debug):
                continue
            unmatched.remove(best_index)
            matched[track_id] = (candidates[best_index], best_debug)
        return matched

    def _match_debug(self, candidate: LegacyPoseCandidate, bbox: list[float]) -> dict[str, float | bool]:
        iou = self._iou(candidate.pose_bbox, bbox)
        bbox_center = self._bbox_center(bbox)
        pose_center = self._bbox_center(candidate.pose_bbox)
        bbox_diag = max(1.0, float(np.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1])))
        center_distance = float(np.hypot(pose_center[0] - bbox_center[0], pose_center[1] - bbox_center[1]))
        center_distance_ratio = center_distance / bbox_diag
        center_score = max(0.0, 1.0 - center_distance_ratio)
        gate_bbox = self._expand_bbox(bbox, 0.08)
        inside_ratio = self._points_inside_ratio(candidate.keypoints, candidate.confidences, gate_bbox)
        torso_inside = self._torso_inside_ratio(candidate.keypoints, candidate.confidences, gate_bbox) >= 0.5
        score = (
            iou * 0.55
            + center_score * 0.20
            + inside_ratio * 0.15
            + candidate.skeleton_confidence * 0.05
            + candidate.box_confidence * 0.05
            + (0.1 if torso_inside else 0.0)
        )
        return {
            "pose_track_match_score": score,
            "pose_match_iou": iou,
            "pose_match_center_distance_ratio": center_distance_ratio,
            "keypoint_inside_bbox_ratio": inside_ratio,
            "torso_inside_bbox": torso_inside,
        }

    def _accept_match(self, debug: dict[str, float | bool]) -> bool:
        score = float(debug["pose_track_match_score"])
        iou = float(debug["pose_match_iou"])
        center_ratio = float(debug["pose_match_center_distance_ratio"])
        inside_ratio = float(debug["keypoint_inside_bbox_ratio"])
        torso_inside = bool(debug["torso_inside_bbox"])
        if score < self.settings.yolo11_pose_match_score_threshold:
            return False
        if iou < self.settings.yolo11_pose_min_match_iou and center_ratio > self.settings.yolo11_pose_max_center_distance_ratio:
            return False
        if inside_ratio < 0.35:
            return False
        if not torso_inside and iou < max(self.settings.yolo11_pose_min_match_iou, 0.18):
            return False
        return True

    def _candidate_points(self, candidate: LegacyPoseCandidate) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for index, (point, score) in enumerate(zip(candidate.keypoints, candidate.confidences)):
            name = COCO_KEYPOINT_NAMES[index] if index < len(COCO_KEYPOINT_NAMES) else f"kp_{index}"
            point_score = float(score)
            if float(point[0]) <= 1.0 and float(point[1]) <= 1.0 and point_score < 0.6:
                point_score = 0.0
            if name in LOWER_BODY_KEYPOINT_NAMES and point_score < LOWER_BODY_MIN_CONFIDENCE:
                point_score = 0.0
            points.append(
                {
                    "index": index,
                    "name": name,
                    "x": round(float(point[0]), 1),
                    "y": round(float(point[1]), 1),
                    "score": round(point_score, 4),
                    "tracked": False,
                    "estimated": False,
                }
            )
        return points

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
            name = str(point.get("name") or "")
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
                if (x <= 1.0 and y <= 1.0 and score < 0.6 and prev_score >= 0.18) or (score < 0.18 <= prev_score):
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

            if x <= 1.0 and y <= 1.0 and score < 0.6:
                score = 0.0
            if name in LOWER_BODY_KEYPOINT_NAMES and (estimated or score < LOWER_BODY_MIN_CONFIDENCE):
                score = 0.0
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

    def _prune_session_state(self, objects: list[DetectedObject]) -> None:
        now_ms = int(time.perf_counter() * 1000)
        active_keys = {f"track:{int(item.track_id)}" for item in objects if item.track_id is not None}
        stale_keys = [
            key
            for key, value in self._session_states.items()
            if key not in active_keys and (now_ms - int(value.get("ts_ms", 0))) > self._max_state_age_ms
        ]
        for key in stale_keys:
            self._session_states.pop(key, None)
        self._last_track_keys = active_keys

    @staticmethod
    def _points_inside_ratio(points: np.ndarray, confidences: np.ndarray, bbox: list[float]) -> float:
        visible = points[confidences >= 0.01]
        if len(visible) == 0:
            return 0.0
        x1, y1, x2, y2 = bbox
        inside = (
            (visible[:, 0] >= x1)
            & (visible[:, 0] <= x2)
            & (visible[:, 1] >= y1)
            & (visible[:, 1] <= y2)
        )
        return float(np.count_nonzero(inside) / len(visible))

    @staticmethod
    def _torso_inside_ratio(points: np.ndarray, confidences: np.ndarray, bbox: list[float]) -> float:
        torso_points: list[list[float]] = []
        for index, point in enumerate(points):
            if index >= len(COCO_KEYPOINT_NAMES):
                continue
            if COCO_KEYPOINT_NAMES[index] not in {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}:
                continue
            if index < len(confidences) and float(confidences[index]) <= 0.01:
                continue
            torso_points.append([float(point[0]), float(point[1])])
        if not torso_points:
            return 0.0
        x1, y1, x2, y2 = bbox
        points_array = np.array(torso_points, dtype=np.float32)
        inside = (
            (points_array[:, 0] >= x1)
            & (points_array[:, 0] <= x2)
            & (points_array[:, 1] >= y1)
            & (points_array[:, 1] <= y2)
        )
        return float(np.count_nonzero(inside) / len(points_array))

    @staticmethod
    def _expand_bbox(bbox: list[float], ratio: float) -> list[float]:
        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        return [x1 - width * ratio, y1 - height * ratio, x2 + width * ratio, y2 + height * ratio]

    @staticmethod
    def _bbox_center(bbox: list[float]) -> tuple[float, float]:
        return ((bbox[0] + bbox[2]) * 0.5, (bbox[1] + bbox[3]) * 0.5)

    @staticmethod
    def _bbox_area(bbox: list[float]) -> float:
        return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])

    @staticmethod
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
        return float(inter / union)
