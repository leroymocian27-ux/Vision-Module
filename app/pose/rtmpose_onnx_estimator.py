from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from app.core.config import Settings
from app.core.logger import get_logger
from app.pose.schemas import PoseKeypoint, PoseResult
from app.pose.yolo_pose_estimator import COCO_KEYPOINT_NAMES
from app.schemas.vision_result import DetectedObject

logger = get_logger(__name__)


class RTMPoseOnnxEstimator:
    """Project-local ONNX RTMPose wrapper that consumes existing person boxes.

    This avoids bringing the entire OpenMMLab runtime into the service while
    preserving the current pipeline contract:
    tracked person bbox in -> COCO-17 keypoints out.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_path = Path(settings.rtmpose_onnx_model_path)
        self.model_input_size = (
            int(settings.rtmpose_onnx_input_width),
            int(settings.rtmpose_onnx_input_height),
        )
        self.mean = np.array((123.675, 116.28, 103.53), dtype=np.float32)
        self.std = np.array((58.395, 57.12, 57.375), dtype=np.float32)
        self._session: ort.InferenceSession | None = None
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
        if not self.model_path.exists():
            self._session = None
            self._last_error = f"rtmpose onnx model not found: {self.model_path}"
            logger.error("rtmpose_onnx_load_failed error=%s", self._last_error)
            return

        providers: list[str] = ["CPUExecutionProvider"]
        device = (self.settings.rtmpose_device or self.settings.yolo_pose_device or "").lower()
        if "cuda" in device:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

        try:
            self._session = ort.InferenceSession(str(self.model_path), providers=providers)
            self._last_error = None
            logger.info(
                "rtmpose_onnx_loaded model=%s providers=%s",
                self.model_path,
                providers,
            )
        except Exception as exc:
            self._session = None
            self._last_error = str(exc)
            logger.error("rtmpose_onnx_load_failed error=%s", exc)

    def estimate(self, frame: np.ndarray, objects: list[DetectedObject]) -> dict[int, PoseResult]:
        if self._session is None:
            self._load()
        if self._session is None:
            raise RuntimeError(f"rtmpose onnx unavailable: {self._last_error}")

        results: dict[int, PoseResult] = {}
        best_debug: dict[str, object] | None = None
        for item in objects:
            if item.track_id is None:
                continue
            kpts, scores, debug = self._infer_one(frame, item.bbox)
            if kpts is None or scores is None:
                continue
            points: list[PoseKeypoint] = []
            confidences: list[float] = []
            for index, (point, score) in enumerate(zip(kpts, scores)):
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
            results[item.track_id] = PoseResult(
                track_id=item.track_id,
                keypoints=points,
                skeleton_confidence=skeleton_confidence,
            )
            if best_debug is None:
                best_debug = {
                    "selected_track_id": item.track_id,
                    "pose_bounds": [
                        round(float(np.min(kpts[:, 0])), 2),
                        round(float(np.min(kpts[:, 1])), 2),
                        round(float(np.max(kpts[:, 0])), 2),
                        round(float(np.max(kpts[:, 1])), 2),
                    ],
                    "skeleton_confidence": skeleton_confidence,
                    "candidate_iou": None,
                    "keypoint_inside_bbox_ratio": None,
                    "keypoint_inside_source_bbox_ratio": None,
                    "torso_inside_bbox": None,
                    "rejected_reason": None,
                }
        self._last_debug = best_debug or {}
        return results

    def _infer_one(
        self,
        frame: np.ndarray,
        bbox: list[float],
    ) -> tuple[np.ndarray | None, np.ndarray | None, dict[str, object]]:
        center, scale = self._bbox_xyxy2cs(np.asarray(bbox, dtype=np.float32), padding=1.25)
        img, scale = self._top_down_affine(self.model_input_size, scale, center, frame)
        img = (img.astype(np.float32) - self.mean) / self.std
        inp = np.ascontiguousarray(img.transpose(2, 0, 1)[None, ...], dtype=np.float32)

        assert self._session is not None
        input_name = self._session.get_inputs()[0].name
        output_names = [out.name for out in self._session.get_outputs()]
        outputs = self._session.run(output_names, {input_name: inp})
        keypoints, scores = self._postprocess(outputs, center, scale)
        debug = {
            "center": center.tolist(),
            "scale": scale.tolist(),
        }
        return keypoints, scores, debug

    @staticmethod
    def _bbox_xyxy2cs(bbox: np.ndarray, padding: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
        x1, y1, x2, y2 = bbox
        center = np.array([(x1 + x2) * 0.5, (y1 + y2) * 0.5], dtype=np.float32)
        scale = np.array([(x2 - x1) * padding, (y2 - y1) * padding], dtype=np.float32)
        return center, scale

    @staticmethod
    def _rotate_point(pt: np.ndarray, angle_rad: float) -> np.ndarray:
        sn, cs = np.sin(angle_rad), np.cos(angle_rad)
        rot_mat = np.array([[cs, -sn], [sn, cs]], dtype=np.float32)
        return rot_mat @ pt

    @staticmethod
    def _get_3rd_point(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        direction = a - b
        return b + np.r_[-direction[1], direction[0]]

    @classmethod
    def _get_warp_matrix(
        cls,
        center: np.ndarray,
        scale: np.ndarray,
        rot: float,
        output_size: tuple[int, int],
    ) -> np.ndarray:
        src_w = scale[0]
        dst_w, dst_h = output_size
        rot_rad = np.deg2rad(rot)
        src_dir = cls._rotate_point(np.array([0.0, src_w * -0.5], dtype=np.float32), rot_rad)
        dst_dir = np.array([0.0, dst_w * -0.5], dtype=np.float32)

        src = np.zeros((3, 2), dtype=np.float32)
        src[0, :] = center
        src[1, :] = center + src_dir
        src[2, :] = cls._get_3rd_point(src[0, :], src[1, :])

        dst = np.zeros((3, 2), dtype=np.float32)
        dst[0, :] = [dst_w * 0.5, dst_h * 0.5]
        dst[1, :] = np.array([dst_w * 0.5, dst_h * 0.5], dtype=np.float32) + dst_dir
        dst[2, :] = cls._get_3rd_point(dst[0, :], dst[1, :])
        return cv2.getAffineTransform(np.float32(src), np.float32(dst))

    @classmethod
    def _top_down_affine(
        cls,
        input_size: tuple[int, int],
        bbox_scale: np.ndarray,
        bbox_center: np.ndarray,
        img: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        w, h = input_size
        aspect_ratio = w / h
        b_w, b_h = bbox_scale[0], bbox_scale[1]
        if b_w > b_h * aspect_ratio:
            bbox_scale = np.array([b_w, b_w / aspect_ratio], dtype=np.float32)
        else:
            bbox_scale = np.array([b_h * aspect_ratio, b_h], dtype=np.float32)
        warp_mat = cls._get_warp_matrix(bbox_center, bbox_scale, 0, (w, h))
        out = cv2.warpAffine(img, warp_mat, (int(w), int(h)), flags=cv2.INTER_LINEAR)
        return out, bbox_scale

    def _postprocess(
        self,
        outputs: list[np.ndarray],
        center: np.ndarray,
        scale: np.ndarray,
        simcc_split_ratio: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        simcc_x, simcc_y = outputs
        locs, scores = self._get_simcc_maximum(simcc_x, simcc_y)
        keypoints = locs / simcc_split_ratio
        keypoints = keypoints / np.array(self.model_input_size, dtype=np.float32) * scale
        keypoints = keypoints + center - scale / 2
        return keypoints[0], scores[0]

    @staticmethod
    def _get_simcc_maximum(
        simcc_x: np.ndarray,
        simcc_y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        n, k, _ = simcc_x.shape
        simcc_x = simcc_x.reshape(n * k, -1)
        simcc_y = simcc_y.reshape(n * k, -1)
        x_locs = np.argmax(simcc_x, axis=1)
        y_locs = np.argmax(simcc_y, axis=1)
        locs = np.stack((x_locs, y_locs), axis=-1).astype(np.float32)
        max_val_x = np.amax(simcc_x, axis=1)
        max_val_y = np.amax(simcc_y, axis=1)
        vals = 0.5 * (max_val_x + max_val_y)
        locs[vals <= 0.0] = -1
        return locs.reshape(n, k, 2), vals.reshape(n, k)
