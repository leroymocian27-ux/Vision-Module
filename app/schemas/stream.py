from __future__ import annotations

from pydantic import BaseModel, Field


class StreamStartRequest(BaseModel):
    camera_id: str = Field(default="camera_01")
    source_url: str | None = Field(
        default=None,
        description="Preferred generic video source URL. Supports HTTP MJPEG, RTSP, mock, and local files.",
    )
    rtsp_url: str | None = Field(
        default=None,
        description="Compatibility field for the authoritative single source URL.",
    )
    main_rtsp_url: str | None = Field(
        default=None,
        description="Compatibility field. In current single-source mode it is ignored when rtsp_url is provided.",
    )
    analysis_rtsp_url: str | None = Field(
        default=None,
        description="Compatibility field. In current single-source mode it is ignored when rtsp_url is provided.",
    )


class StreamStopRequest(BaseModel):
    camera_id: str = Field(default="camera_01")


class MockStreamFaultRequest(BaseModel):
    camera_id: str = Field(default="camera_01")
    mode: str = Field(pattern="^(normal|pause|delay|freeze|stop|resume|decode_error)$")


class StreamControlResponse(BaseModel):
    camera_id: str
    status: str
    message: str
    source_url: str | None = None
    main_rtsp_url: str | None = None
    analysis_rtsp_url: str | None = None


class StreamRuntimeSourceResponse(BaseModel):
    camera_id: str
    running: bool
    dual_stream_enabled: bool
    display_source_current: str
    display_fallback_active: bool
    main_rtsp_url_masked: str | None = None
    analysis_rtsp_url_masked: str | None = None
    source_url_masked: str | None = None
    source_protocol: str = "unknown"
    main_stream_state: str | None = None
    analysis_stream_state: str | None = None
    main_connected: bool | None = None
    analysis_connected: bool | None = None
    main_frame_age_ms: float | None = None
    analysis_frame_age_ms: float | None = None
    main_capture_fps: float | None = None
    analysis_capture_fps: float | None = None
    frame_status: str | None = None
    source_generation: int | None = None
    message: str = "ok"


class StreamHostSwitchRequest(BaseModel):
    camera_id: str = Field(default="camera_01")
    host: str = Field(description="Camera IP or hostname after mobile WiFi restart.")
    username: str = Field(default="admin")
    password: str = Field(description="Camera RTSP password.")
    port: int = Field(default=10554, ge=1, le=65535)
    main_path: str = Field(default="/tcp/av0_0")
    analysis_path: str = Field(default="/tcp/av0_1")
    scheme: str = Field(default="rtsp")


class StreamProbeRequest(BaseModel):
    host: str
    port: int = Field(default=10554, ge=1, le=65535)
    timeout_ms: int = Field(default=1500, ge=100, le=10000)


class StreamProbeResponse(BaseModel):
    host: str
    port: int
    reachable: bool
    elapsed_ms: float
    error: str | None = None
