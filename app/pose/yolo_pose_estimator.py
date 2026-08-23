from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.schemas import PoseKeypoint, PoseResult
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)

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

TORSO_KEYPOINTS = {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}


class YoloPoseEstimator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model = None
        self._last_error: str | None = None
        self._last_debug: dict[str, object] = {}
        self._load()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_debug(self) -> dict[str, object]:
        return dict(self._last_debug)

    def _load(self) -> None:
        candidates = self._model_candidates()
        errors: list[str] = []
        try:
            from ultralytics import YOLO
            for model_path in candidates:
                try:
                    self._model = YOLO(model_path)
                    self._last_error = None
                    logger.info("yolo_pose_loaded model=%s", model_path)
                    return
                except Exception as exc:
                    errors.append(f"{model_path}: {exc}")
            self._model = None
            self._last_error = " | ".join(errors) if errors else "no pose model candidates"
            logger.error("yolo_pose_load_failed error=%s", self._last_error)
        except Exception as exc:
            self._model = None
            self._last_error = str(exc)
            logger.error("yolo_pose_load_failed error=%s", exc)

    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        if self._model is None:
            self._load()
        if self._model is None:
            raise RuntimeError(f"yolo pose model unavailable: {self._last_error}")

        results: dict[int, PoseResult] = {}
        for item in objects:
            if item.track_id is None:
                continue
            crop_info = self._crop(frame, item.bbox)
            if crop_info is None:
                self._last_debug = {
                    "selected_track_id": item.track_id,
                    "rejected_reason": "invalid_crop",
                }
                continue
            crop, left, top, expanded_bbox = crop_info
            pose = self._estimate_crop(crop, left, top, item.track_id, item.bbox, expanded_bbox)
            if pose is not None:
                results[item.track_id] = pose
        return results

    def _estimate_crop(
        self,
        crop: np.ndarray,
        left: int,
        top: int,
        track_id: int,
        source_bbox: list[float],
        expanded_bbox: list[float],
    ) -> PoseResult | None:
        kwargs = {
            "conf": self.settings.yolo_pose_confidence,
            "imgsz": self.settings.yolo_pose_imgsz,
            "verbose": False,
        }
        if self.settings.yolo_pose_device:
            kwargs["device"] = self.settings.yolo_pose_device

        predictions = self._model.predict(crop, **kwargs)
        if not predictions:
            return None
        result = predictions[0]
        keypoints = getattr(result, "keypoints", None)
        if keypoints is None or keypoints.xy is None or len(keypoints.xy) == 0:
            self._last_debug = {
                "selected_track_id": track_id,
                "rejected_reason": "no_keypoints",
            }
            return None

        boxes = getattr(result, "boxes", None)
        box_conf = boxes.conf.cpu().numpy() if boxes is not None and boxes.conf is not None else None
        box_xyxy = boxes.xyxy.cpu().numpy() if boxes is not None and boxes.xyxy is not None else None
        xy_all = keypoints.xy.cpu().numpy()
        conf_all = keypoints.conf.cpu().numpy() if keypoints.conf is not None else np.ones(xy_all.shape[:2])

        candidate_index, candidate_debug = self._select_candidate(
            xy_all=xy_all,
            conf_all=conf_all,
            box_xyxy=box_xyxy,
            box_conf=box_conf,
            left=left,
            top=top,
            source_bbox=source_bbox,
            expanded_bbox=expanded_bbox,
        )
        if candidate_index is None:
            self._last_debug = {
                "selected_track_id": track_id,
                **candidate_debug,
            }
            return None

        xy = xy_all[candidate_index]
        conf = conf_all[candidate_index]
        points: list[PoseKeypoint] = []
        confidences: list[float] = []
        for index, (point, score) in enumerate(zip(xy, conf)):
            name = COCO_KEYPOINT_NAMES[index] if index < len(COCO_KEYPOINT_NAMES) else f"kp_{index}"
            x, y = float(point[0]) + left, float(point[1]) + top
            confidence = round(float(score), 4)
            points.append(PoseKeypoint(name=name, x=round(x, 2), y=round(y, 2), confidence=confidence))
            confidences.append(float(score))
        skeleton_confidence = round(float(np.mean(confidences)), 4) if confidences else 0.0
        self._last_debug = {
            "selected_track_id": track_id,
            "rejected_reason": None,
            "keypoint_inside_bbox_ratio": candidate_debug.get("keypoint_inside_bbox_ratio"),
            "keypoint_inside_source_bbox_ratio": candidate_debug.get("keypoint_inside_source_bbox_ratio"),
            "candidate_iou": candidate_debug.get("candidate_iou"),
            "pose_bounds": candidate_debug.get("pose_bounds"),
            "torso_inside_bbox": candidate_debug.get("torso_inside_bbox"),
            "skeleton_confidence": skeleton_confidence,
        }
        return PoseResult(track_id=track_id, keypoints=points, skeleton_confidence=skeleton_confidence)

    def _crop(self, frame: np.ndarray, bbox: list[float]) -> tuple[np.ndarray, int, int, list[float]] | None:
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        bbox_w = max(1.0, x2 - x1)
        bbox_h = max(1.0, y2 - y1)
        padding_ratio = self.settings.pose_crop_padding_ratio
        if bbox_w >= bbox_h * 1.15:
            padding_ratio = max(padding_ratio, self.settings.pose_fallen_crop_padding_ratio)
        pad_x = bbox_w * padding_ratio
        pad_y = bbox_h * padding_ratio
        left = max(0, int(x1 - pad_x))
        top = max(0, int(y1 - pad_y))
        right = min(width, int(x2 + pad_x))
        bottom = min(height, int(y2 + pad_y))
        if right <= left or bottom <= top:
            return None
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            return None
        # Ensure contiguous BGR input for Ultralytics.
        return cv2.copyMakeBorder(crop, 0, 0, 0, 0, cv2.BORDER_CONSTANT), left, top, [
            float(left),
            float(top),
            float(right),
            float(bottom),
        ]

    def _select_candidate(
        self,
        *,
        xy_all: np.ndarray,
        conf_all: np.ndarray,
        box_xyxy: np.ndarray | None,
        box_conf: np.ndarray | None,
        left: int,
        top: int,
        source_bbox: list[float],
        expanded_bbox: list[float],
    ) -> tuple[int | None, dict[str, object]]:
        best_index: int | None = None
        best_score = -1.0
        best_debug: dict[str, object] = {"rejected_reason": "no_valid_candidate"}
        for index, xy in enumerate(xy_all):
            conf = conf_all[index] if index < len(conf_all) else np.ones(len(xy))
            valid = conf >= max(0.01, self.settings.yolo_pose_confidence * 0.35)
            valid_points = xy[valid]
            valid_conf = conf[valid]
            if len(valid_points) < 4:
                continue
            global_points = valid_points + np.array([left, top])
            source_gate_bbox = self._expand_bbox(source_bbox, 0.08)
            inside_ratio = self._points_inside_ratio(global_points, source_gate_bbox)
            expanded_inside_ratio = self._points_inside_ratio(global_points, expanded_bbox)
            skeleton_confidence = float(np.mean(valid_conf)) if len(valid_conf) else 0.0
            point_box = [
                float(np.min(global_points[:, 0])),
                float(np.min(global_points[:, 1])),
                float(np.max(global_points[:, 0])),
                float(np.max(global_points[:, 1])),
            ]
            candidate_iou = 0.0
            if box_xyxy is not None and index < len(box_xyxy):
                local_box = box_xyxy[index]
                global_box = [
                    float(local_box[0]) + left,
                    float(local_box[1]) + top,
                    float(local_box[2]) + left,
                    float(local_box[3]) + top,
                ]
                candidate_iou = self._iou(global_box, source_bbox)
            elif len(global_points):
                candidate_iou = self._iou(point_box, source_bbox)
            torso_inside = self._torso_inside_ratio(xy, conf, left, top, source_gate_bbox) >= 0.5
            detector_conf = float(box_conf[index]) if box_conf is not None and index < len(box_conf) else 0.0
            score = (
                candidate_iou * 2.0
                + inside_ratio
                + expanded_inside_ratio * 0.25
                + skeleton_confidence
                + (0.35 if torso_inside else 0.0)
                + detector_conf * 0.25
            )
            debug = {
                "candidate_iou": round(candidate_iou, 4),
                "keypoint_inside_bbox_ratio": round(inside_ratio, 4),
                "keypoint_inside_source_bbox_ratio": round(inside_ratio, 4),
                "keypoint_inside_expanded_bbox_ratio": round(expanded_inside_ratio, 4),
                "pose_bounds": [round(value, 2) for value in point_box],
                "torso_inside_bbox": torso_inside,
                "skeleton_confidence": round(skeleton_confidence, 4),
            }
            if score > best_score:
                best_score = score
                best_index = index
                best_debug = debug

        if best_index is None:
            return None, best_debug
        min_iou = self._min_candidate_iou(source_bbox)
        min_inside_ratio = self._min_inside_ratio(source_bbox)
        if float(best_debug.get("skeleton_confidence") or 0.0) < self.settings.pose_min_skeleton_confidence:
            best_debug["rejected_reason"] = "low_skeleton_confidence"
            return None, best_debug
        if float(best_debug.get("keypoint_inside_bbox_ratio") or 0.0) < min_inside_ratio:
            best_debug["rejected_reason"] = "keypoints_outside_bbox"
            return None, best_debug
        if float(best_debug.get("candidate_iou") or 0.0) < min_iou:
            best_debug["rejected_reason"] = "candidate_bbox_mismatch"
            return None, best_debug
        if not bool(best_debug.get("torso_inside_bbox")):
            best_debug["rejected_reason"] = "torso_outside_bbox"
            return None, best_debug
        best_debug["rejected_reason"] = None
        return best_index, best_debug

    def _min_candidate_iou(self, bbox: list[float]) -> float:
        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        if width >= height * 1.15:
            return self.settings.pose_min_fallen_candidate_iou
        return self.settings.pose_min_candidate_iou

    def _min_inside_ratio(self, bbox: list[float]) -> float:
        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        if width >= height * 1.15:
            return self.settings.pose_min_fallen_keypoint_inside_ratio
        return self.settings.pose_min_keypoint_inside_ratio

    @staticmethod
    def _torso_inside_ratio(
        xy: np.ndarray,
        conf: np.ndarray,
        left: int,
        top: int,
        bbox: list[float],
    ) -> float:
        points: list[list[float]] = []
        for index, point in enumerate(xy):
            name = COCO_KEYPOINT_NAMES[index] if index < len(COCO_KEYPOINT_NAMES) else f"kp_{index}"
            if name not in TORSO_KEYPOINTS:
                continue
            if index < len(conf) and float(conf[index]) <= 0.01:
                continue
            points.append([float(point[0]) + left, float(point[1]) + top])
        if not points:
            return 0.0
        return YoloPoseEstimator._points_inside_ratio(np.array(points), bbox)

    @staticmethod
    def _expand_bbox(bbox: list[float], ratio: float) -> list[float]:
        x1, y1, x2, y2 = bbox
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        pad_x = width * ratio
        pad_y = height * ratio
        return [float(x1 - pad_x), float(y1 - pad_y), float(x2 + pad_x), float(y2 + pad_y)]

    @staticmethod
    def _points_inside_ratio(points: np.ndarray, bbox: list[float]) -> float:
        if len(points) == 0:
            return 0.0
        x1, y1, x2, y2 = bbox
        inside = (
            (points[:, 0] >= x1)
            & (points[:, 0] <= x2)
            & (points[:, 1] >= y1)
            & (points[:, 1] <= y2)
        )
        return float(np.count_nonzero(inside) / len(points))

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

    def _model_candidates(self) -> list[str]:
        configured = (self.settings.yolo_pose_model_path or "").strip()
        ordered = [
            configured,
            "yolo11s-pose.pt",
            "yolo11n-pose.pt",
            "yolo26n-pose.pt",
            "yolov8n-pose.pt",
        ]
        seen: set[str] = set()
        candidates: list[str] = []
        for item in ordered:
            if not item or item in seen:
                continue
            seen.add(item)
            path = Path(item)
            if path.exists() or (not path.is_absolute() and len(path.parts) == 1):
                candidates.append(str(path))
        return candidates
