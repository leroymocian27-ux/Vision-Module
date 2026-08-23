from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.vision_result import DetectedObject


class ConnectionStatusEndpoint(BaseModel):
    base_url: str
    status: str


class ConnectionStatusCamera(BaseModel):
    camera_id: str


class IntegrationConnectionStatusResponse(BaseModel):
    vision_service: ConnectionStatusEndpoint
    main_system: ConnectionStatusEndpoint
    camera: ConnectionStatusCamera
    timestamp: str


class FallAlertPollingResponse(BaseModel):
    camera_id: str
    status: str
    should_popup: bool = False
    last_incident_id: str | None = None
    incident_id: str | None = None
    event_timestamp: str | None = None
    fall_state: str | None = None
    risk_level: str | None = None
    snapshot_url: str | None = None
    alert: dict | None = None


class IntegrationLatestResultResponse(BaseModel):
    type: str = "vision_result"
    camera_id: str
    stream_name: str = "primary"
    source: str = "vision_service"
    event_type: str | None = None
    state: str | None = None
    status: str | None = None
    service_state: str = "unknown"
    camera_lost: bool = False
    capture_stale: bool = False
    frame_age_ms: float | None = None
    source_fps: float | None = None
    analysis_fps: float | None = None
    fall_detected: bool = False
    fall_state: str | None = None
    risk: str | None = None
    risk_level: str | None = None
    fall_prob: float | None = None
    fall_score: float | None = None
    confidence_level: str | None = None
    degraded_by: list[str] = Field(default_factory=list)
    reason: str | None = None
    safe_to_interpret_as_no_fall: bool = True
    frame_status: str | None = None
    camera_stream_state: str | None = None
    source_generation: int | None = None
    track_id: int | str | None = None
    incident_id: str | None = None
    bbox: list[float] | None = None
    target: dict | str | None = None
    snapshot_url: str | None = None
    snapshot_path: str | None = None
    timestamp: str
    frame_seq: int
    frame_width: int
    frame_height: int
    alarm_confirmed: bool = False
    scores: dict = Field(default_factory=dict)
    injury: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    objects: list[DetectedObject] = Field(default_factory=list)
    detector: dict = Field(default_factory=dict)
