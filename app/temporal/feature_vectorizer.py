from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.temporal.schemas import TargetFeature


FEATURE_SCHEMA_VERSION = "fall_lstm_features_v1"
FEATURE_NAMES = [
    "bbox_center_x_norm",
    "bbox_center_y_norm",
    "bbox_width_norm",
    "bbox_height_norm",
    "aspect_ratio_clipped",
    "delta_x_norm",
    "delta_y_norm",
    "velocity_x_norm",
    "velocity_y_norm",
    "speed_norm",
    "pose_available",
    "pose_confidence",
    "torso_angle_norm",
    "head_height_ratio_filled",
    "hip_height_ratio_filled",
]


@dataclass(frozen=True)
class FeatureSchema:
    schema_version: str
    input_dim: int
    window_size: int
    feature_names: list[str]
    schema_hash: str
    missing_pose_fill: dict[str, float]

    def model_dump(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "input_dim": self.input_dim,
            "window_size": self.window_size,
            "feature_names": self.feature_names,
            "schema_hash": self.schema_hash,
            "missing_pose_fill": self.missing_pose_fill,
        }


class FeatureVectorizer:
    def __init__(self, window_size: int = 32) -> None:
        self.window_size = window_size
        self.feature_names = list(FEATURE_NAMES)
        self.input_dim = len(self.feature_names)
        self.schema_version = FEATURE_SCHEMA_VERSION
        self.missing_pose_fill = {
            "pose_available": 0.0,
            "pose_confidence": 0.0,
            "torso_angle_norm": 0.0,
            "head_height_ratio_filled": -1.0,
            "hip_height_ratio_filled": -1.0,
        }
        self.schema_hash = self._schema_hash()

    def schema(self) -> FeatureSchema:
        return FeatureSchema(
            schema_version=self.schema_version,
            input_dim=self.input_dim,
            window_size=self.window_size,
            feature_names=list(self.feature_names),
            schema_hash=self.schema_hash,
            missing_pose_fill=dict(self.missing_pose_fill),
        )

    def vectorize(
        self,
        feature: TargetFeature,
        *,
        frame_width: int,
        frame_height: int,
    ) -> list[float]:
        eps = 1e-6
        frame_width_f = max(float(frame_width), eps)
        frame_height_f = max(float(frame_height), eps)
        bbox_height = max(float(feature.bbox_height), eps)
        torso_angle = feature.torso_angle
        head_ratio = feature.head_height_ratio
        hip_ratio = feature.hip_height_ratio
        vector = [
            self._clip(feature.bbox_center_x / frame_width_f, 0.0, 1.5),
            self._clip(feature.bbox_center_y / frame_height_f, 0.0, 1.5),
            self._clip(feature.bbox_width / frame_width_f, 0.0, 1.5),
            self._clip(feature.bbox_height / frame_height_f, 0.0, 1.5),
            self._clip(feature.aspect_ratio, 0.0, 3.0),
            self._clip(feature.delta_x / bbox_height, -3.0, 3.0),
            self._clip(feature.delta_y / bbox_height, -3.0, 3.0),
            self._clip(feature.velocity_x / bbox_height, -10.0, 10.0),
            self._clip(feature.velocity_y / bbox_height, -10.0, 10.0),
            self._clip(feature.speed / bbox_height, 0.0, 10.0),
            1.0 if feature.pose_available else self.missing_pose_fill["pose_available"],
            self._clip(feature.pose_confidence, 0.0, 1.0),
            self._clip((torso_angle if torso_angle is not None else 0.0) / 90.0, -1.0, 1.0),
            self._clip(
                head_ratio if head_ratio is not None else self.missing_pose_fill["head_height_ratio_filled"],
                -1.0,
                2.0,
            ),
            self._clip(
                hip_ratio if hip_ratio is not None else self.missing_pose_fill["hip_height_ratio_filled"],
                -1.0,
                2.0,
            ),
        ]
        return [float(item) for item in vector]

    def vectors_from_window(
        self,
        window: list[TargetFeature],
        *,
        frame_width: int,
        frame_height: int,
    ) -> list[list[float]]:
        return [
            self.vectorize(item, frame_width=frame_width, frame_height=frame_height)
            for item in window
        ]

    def _schema_hash(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "input_dim": self.input_dim,
            "window_size": self.window_size,
            "feature_names": self.feature_names,
            "missing_pose_fill": self.missing_pose_fill,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    @staticmethod
    def _clip(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))
