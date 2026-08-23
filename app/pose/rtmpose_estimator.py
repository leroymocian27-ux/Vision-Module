from __future__ import annotations

from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.schemas import PoseKeypoint, PoseResult
from app.pose.yolo_pose_estimator import COCO_KEYPOINT_NAMES
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


class RTMPoseEstimator:
    """Top-down RTMPose wrapper for tracked person boxes.

    This provider is designed to fit the existing pipeline shape:
    one full frame plus tracked person bounding boxes in, one COCO-17 pose per
    track out. It intentionally keeps the same output schema as the YOLO pose
    estimator so downstream temporal and behavior logic can stay unchanged.
    """

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
        config_path = Path(self.settings.rtmpose_config_path)
        checkpoint_path = Path(self.settings.rtmpose_checkpoint_path)
        try:
            from mmpose.apis import init_model
        except Exception as exc:
            self._model = None
            self._last_error = (
                "mmpose import failed. Install mmpose/mmdet/mmengine/mmcv first. "
                f"Original error: {exc}"
            )
            logger.error("rtmpose_load_failed error=%s", self._last_error)
            return

        if not config_path.exists():
            self._model = None
            self._last_error = f"rtmpose config not found: {config_path}"
            logger.error("rtmpose_load_failed error=%s", self._last_error)
            return
        if not checkpoint_path.exists():
            self._model = None
            self._last_error = f"rtmpose checkpoint not found: {checkpoint_path}"
            logger.error("rtmpose_load_failed error=%s", self._last_error)
            return

        device = self.settings.rtmpose_device or self.settings.yolo_pose_device or "cuda:0"
        try:
            self._model = init_model(str(config_path), str(checkpoint_path), device=device)
            self._last_error = None
            logger.info(
                "rtmpose_loaded config=%s checkpoint=%s device=%s",
                config_path,
                checkpoint_path,
                device,
            )
        except Exception as exc:
            self._model = None
            self._last_error = str(exc)
            logger.error("rtmpose_load_failed error=%s", exc)

    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        if self._model is None:
            self._load()
        if self._model is None:
            raise RuntimeError(f"rtmpose model unavailable: {self._last_error}")

        try:
            from mmpose.apis import inference_topdown
        except Exception as exc:
            raise RuntimeError(f"rtmpose inference api unavailable: {exc}") from exc

        bboxes: list[list[float]] = []
        tracked_items: list[DetectedObject] = []
        for item in objects:
            if item.track_id is None:
                continue
            tracked_items.append(item)
            bboxes.append([float(v) for v in item.bbox])

        if not bboxes:
            return {}

        pose_samples = inference_topdown(
            self._model,
            frame,
            np.asarray(bboxes, dtype=np.float32),
            bbox_format="xyxy",
        )

        results: dict[int, PoseResult] = {}
        best_debug: dict[str, object] | None = None
        for item, sample in zip(tracked_items, pose_samples):
            pred_instances = getattr(sample, "pred_instances", None)
            if pred_instances is None:
                continue
            keypoints = getattr(pred_instances, "keypoints", None)
            keypoint_scores = getattr(pred_instances, "keypoint_scores", None)
            if keypoints is None or len(keypoints) == 0:
                continue

            xy = np.asarray(keypoints[0], dtype=float)
            scores = (
                np.asarray(keypoint_scores[0], dtype=float)
                if keypoint_scores is not None and len(keypoint_scores) > 0
                else np.ones(len(xy), dtype=float)
            )
            points: list[PoseKeypoint] = []
            confidences: list[float] = []
            for index, (point, score) in enumerate(zip(xy, scores)):
                name = COCO_KEYPOINT_NAMES[index] if index < len(COCO_KEYPOINT_NAMES) else f"kp_{index}"
                points.append(
                    PoseKeypoint(
                        name=name,
                        x=round(float(point[0]), 2),
                        y=round(float(point[1]), 2),
                        confidence=round(float(score), 4),
                    )
                )
                confidences.append(float(score))

            skeleton_confidence = round(float(np.mean(confidences)), 4) if confidences else 0.0
            pose_result = PoseResult(
                track_id=item.track_id,
                keypoints=points,
                skeleton_confidence=skeleton_confidence,
            )
            results[item.track_id] = pose_result
            if best_debug is None:
                best_debug = {
                    "selected_track_id": item.track_id,
                    "candidate_iou": None,
                    "keypoint_inside_bbox_ratio": None,
                    "keypoint_inside_source_bbox_ratio": None,
                    "pose_bounds": [
                        round(float(np.min(xy[:, 0])), 2),
                        round(float(np.min(xy[:, 1])), 2),
                        round(float(np.max(xy[:, 0])), 2),
                        round(float(np.max(xy[:, 1])), 2),
                    ],
                    "torso_inside_bbox": None,
                    "skeleton_confidence": skeleton_confidence,
                    "rejected_reason": None,
                }
        self._last_debug = best_debug or {}
        return results
