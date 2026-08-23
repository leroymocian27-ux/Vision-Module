from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field


class BehaviorState(StrEnum):
    STANDING = "standing"
    WALKING = "walking"
    SITTING = "sitting"
    BENDING = "bending"
    LYING = "lying"
    UNKNOWN = "unknown"


class BehaviorFeatures(BaseModel):
    head_y: float | None = None
    shoulder_y: float | None = None
    hip_y: float | None = None
    ankle_y: float | None = None
    torso_angle: float | None = None
    bbox_aspect_ratio: float | None = None
    body_center: list[float] | None = Field(default=None, description="[x, y] in source frame pixels")
    velocity: float | None = None
    still_duration: float = 0.0
    vertical_velocity: float | None = None


class BehaviorResult(BaseModel):
    behavior_state: str = BehaviorState.UNKNOWN.value
    behavior_confidence: float = 0.0
    behavior_features: BehaviorFeatures = Field(default_factory=BehaviorFeatures)


class BehaviorStatus(BaseModel):
    enabled: bool = False
    state: str = BehaviorState.UNKNOWN.value
    last_error: str | None = None
