from __future__ import annotations

from dataclasses import dataclass

from app.behavior.schemas import BehaviorFeatures, BehaviorState
from app.core.config import Settings


@dataclass(frozen=True)
class RuleDecision:
    state: BehaviorState
    confidence: float
    reason: str


class BehaviorRules:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def classify(self, features: BehaviorFeatures) -> RuleDecision:
        if features.bbox_aspect_ratio is None:
            return RuleDecision(BehaviorState.UNKNOWN, 0.2, "missing_bbox")

        if self._is_lying(features):
            return RuleDecision(BehaviorState.LYING, 0.82, "wide_bbox_or_horizontal_torso")
        if self._is_bending(features):
            return RuleDecision(BehaviorState.BENDING, 0.72, "torso_angle_forward")
        if self._is_sitting(features):
            return RuleDecision(BehaviorState.SITTING, 0.68, "compressed_body")
        if self._is_walking(features):
            return RuleDecision(BehaviorState.WALKING, 0.66, "body_center_moving")
        if self._is_standing(features):
            return RuleDecision(BehaviorState.STANDING, 0.7, "upright_body")
        return RuleDecision(BehaviorState.UNKNOWN, 0.35, "low_confidence_features")

    def has_rapid_descent(self, features: BehaviorFeatures) -> bool:
        velocity = features.vertical_velocity
        if velocity is None:
            return False
        return velocity >= self.settings.behavior_rapid_descent_px_per_sec

    def has_long_still(self, features: BehaviorFeatures) -> bool:
        return features.still_duration >= self.settings.behavior_long_still_sec

    @staticmethod
    def _is_lying(features: BehaviorFeatures) -> bool:
        aspect = features.bbox_aspect_ratio or 0.0
        angle = features.torso_angle
        if aspect >= 1.15:
            return True
        return angle is not None and abs(angle) >= 62 and aspect >= 0.85

    @staticmethod
    def _is_bending(features: BehaviorFeatures) -> bool:
        angle = features.torso_angle
        return angle is not None and 35 <= abs(angle) < 62

    @staticmethod
    def _is_sitting(features: BehaviorFeatures) -> bool:
        aspect = features.bbox_aspect_ratio or 0.0
        if aspect < 0.35:
            return False
        if features.shoulder_y is None or features.hip_y is None or features.ankle_y is None:
            return False
        body_height = abs(features.ankle_y - (features.head_y or features.shoulder_y))
        torso_height = abs(features.hip_y - features.shoulder_y)
        if body_height <= 1:
            return False
        return torso_height / body_height < 0.45

    @staticmethod
    def _is_walking(features: BehaviorFeatures) -> bool:
        velocity = features.velocity
        return velocity is not None and velocity >= 45

    @staticmethod
    def _is_standing(features: BehaviorFeatures) -> bool:
        aspect = features.bbox_aspect_ratio or 0.0
        angle = features.torso_angle
        return aspect < 0.85 and (angle is None or abs(angle) < 28)
