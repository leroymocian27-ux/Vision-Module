from __future__ import annotations

from pydantic import BaseModel, Field


class AlertEndpointConfig(BaseModel):
    base_url: str
    path: str = "/video-bridge/fall-events"
    enabled: bool = True
    dry_run: bool = False
    token_header: str | None = None


class AlertEndpointUpdateRequest(BaseModel):
    base_url: str
    path: str = "/video-bridge/fall-events"
    enabled: bool = True


class AlertSimulationStartRequest(BaseModel):
    target_ip: str | None = None
    base_url: str | None = None
    path: str | None = None
    interval_seconds: float = Field(default=2.0, ge=0.2, le=3600.0)
    camera_id: str = "camera_01"
    track_id: str = "smoke-track"
    fall_prob: float = Field(default=0.91, ge=0.0, le=1.0)


class AlertSimulationSendOnceRequest(BaseModel):
    target_ip: str = Field(min_length=1)
    camera_id: str = "camera_01"
    track_id: str = "manual-console-probe"
    fall_prob: float = Field(default=0.91, ge=0.0, le=1.0)


class AlertSimulationSendOnceResult(BaseModel):
    ok: bool
    target_url: str
    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    sent_at: str
    incident_id: str


class AlertSimulationStatus(BaseModel):
    running: bool = False
    interval_seconds: float | None = None
    target_url: str | None = None
    camera_id: str | None = None
    track_id: str | None = None
    sent_count: int = 0
    last_status: str | None = None
    last_error: str | None = None
    last_sent_at: str | None = None
    last_payload: dict | None = None


class AlertControlStatus(BaseModel):
    endpoint: AlertEndpointConfig
    simulation: AlertSimulationStatus
