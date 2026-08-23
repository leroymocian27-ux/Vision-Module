from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python 3.10 compatibility
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, Field


class TargetState(StrEnum):
    IDLE = "idle"
    TARGET_LOCKED = "target_locked"
    TARGET_LOST = "target_lost"
    TARGET_REACQUIRING = "target_reacquiring"


class TrackingDetection(BaseModel):
    label: str = "person"
    confidence: float
    bbox: list[float] = Field(description="[x1, y1, x2, y2] in source frame pixels")

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class TrackedObject(BaseModel):
    track_id: int
    label: str = "person"
    confidence: float
    bbox: list[float] = Field(description="[x1, y1, x2, y2] in source frame pixels")
    is_target: bool = False
    person_id: str | None = None
    person_name: str | None = None
    identity_state: str = TargetState.IDLE.value

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


class TrackingStatus(BaseModel):
    tracker_running: bool = False
    tracking_state: str = TargetState.IDLE.value
    tracked_target_id: int | None = None
    active_target_exists: bool = False
    tracked_objects_count: int = 0
    tracking_fps: float = 0.0
    last_error: str | None = None


class IdentityStatus(BaseModel):
    identity_enabled: bool = False
