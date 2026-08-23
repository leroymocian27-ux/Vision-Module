from __future__ import annotations

from pydantic import BaseModel, Field


class DetectedObject(BaseModel):
    label: str = "person"
    confidence: float
    bbox: list[float] = Field(description="[x1, y1, x2, y2] in source frame pixels")
    track_id: int | None = None
    is_target: bool = False
    person_id: str | None = None
    person_name: str | None = None
    identity_state: str | None = None
    pose: dict | None = None
    behavior: dict | None = None
    temporal: dict | None = None
    fall_decision: dict | None = None
    alarm_preview: dict | None = None
    features: dict | None = None
    fusion_debug: dict | None = None


class VisionResult(BaseModel):
    type: str = "vision_result"
    camera_id: str
    timestamp: str
    frame_seq: int
    frame_width: int
    frame_height: int
    objects: list[DetectedObject] = Field(default_factory=list)
    detector: dict = Field(default_factory=dict)
