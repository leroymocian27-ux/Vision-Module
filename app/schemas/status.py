from __future__ import annotations

from pydantic import BaseModel, Field


class CameraStatus(BaseModel):
    camera_id: str
    running: bool
    connected: bool
    source_url_masked: str | None = None
    frame_seq: int = 0
    frame_width: int | None = None
    frame_height: int | None = None
    frame_age_ms: float | None = None
    last_frame_at: str | None = None
    received_at: str | None = None
    source: str = "unknown"
    source_generation: int = 0
    frame_status: str = "no_frame"
    is_stale: bool = False
    safe_to_interpret_as_no_fall: bool = False
    stream_state: str = "disconnected"
    capture_fps: float = 0.0
    reconnect_count: int = 0
    read_latency_ms: float | None = None
    read_latency_max_ms: float | None = None
    read_timeout_count: int = 0
    stale_count: int = 0
    last_read_started_at: str | None = None
    last_read_completed_at: str | None = None
    consecutive_slow_reads: int = 0
    reconnect_reason: str | None = None
    capture_backend: str = "opencv"
    capture_process_alive: bool = False
    capture_process_pid: int | None = None
    capture_process_restart_count: int = 0
    capture_process_last_frame_age_ms: float | None = None
    capture_process_last_error: str | None = None
    capture_process_last_exit_code: int | None = None
    capture_ipc_decode_errors: int = 0
    capture_ipc_dropped_frames: int = 0
    capture_output_width: int | None = None
    capture_output_height: int | None = None
    last_error: str | None = None


class DetectionStatus(BaseModel):
    camera_id: str
    running: bool
    enabled: bool
    loaded: bool
    model_name: str | None = None
    detection_fps: float = 0.0
    fall_hint_fps: float = 0.0
    inference_latency_ms: float | None = None
    fall_inference_latency_ms: float | None = None
    fall_hint_writer_source: str = "DetectionService"
    last_error: str | None = None
    latest_raw_person_count: int = 0
    latest_fall_model_count: int = 0
    latest_person_boxes: list[list[float]] = Field(default_factory=list)
    latest_person_confidences: list[float] = Field(default_factory=list)
    latest_fall_labels: list[str] = Field(default_factory=list)
    latest_fall_confidences: list[float] = Field(default_factory=list)
    latest_fall_boxes: list[list[float]] = Field(default_factory=list)


class StreamingStatus(BaseModel):
    webrtc_clients: int = 0
    ws_clients: int = 0


class TrackingStatus(BaseModel):
    tracker_running: bool = False
    tracking_state: str = "idle"
    tracked_target_id: int | None = None
    active_target_exists: bool = False
    tracked_objects_count: int = 0
    tracking_fps: float = 0.0
    last_error: str | None = None


class IdentityStatus(BaseModel):
    identity_enabled: bool = False
    identity_binding_enabled: bool = False
    identity_service_available: bool = False
    recognizer_loaded: bool = False
    recognizer_name: str | None = None
    model_name: str | None = None
    registered_count: int = 0
    bound_person_id: str | None = None
    bound_person_name: str | None = None
    last_match_score: float | None = None
    cache_age_ms: float | None = None
    last_match_latency_ms: float | None = None
    pending_requests: int = 0
    skipped_due_to_inflight: int = 0
    health_cache_age_ms: float | None = None
    last_error: str | None = None


class PoseStatus(BaseModel):
    pose_enabled: bool = False
    pose_provider: str = "disabled_placeholder"
    pose_pipeline_removed: bool = False
    placeholder_reason: str | None = None
    pose_fps: float = 0.0
    last_inference_latency_ms: float | None = None
    slow_inference_count: int = 0
    skipped_due_to_busy: int = 0
    worker_tick_count: int = 0
    inference_attempt_count: int = 0
    inference_success_count: int = 0
    pose_target_object_count: int = 0
    pose_attached_object_count: int = 0
    pose_valid_rate: float = 0.0
    inference_success_rate: float = 0.0
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    circuit_open: bool = False
    circuit_cooldown_remaining_ms: float | None = None
    last_error: str | None = None
    selected_track_id: int | None = None
    keypoint_inside_bbox_ratio: float | None = None
    keypoint_inside_source_bbox_ratio: float | None = None
    candidate_iou: float | None = None
    pose_track_match_score: float | None = None
    pose_match_iou: float | None = None
    pose_match_center_distance_ratio: float | None = None
    pose_bounds: list[float] | None = None
    torso_inside_bbox: bool | None = None
    skeleton_confidence: float | None = None
    rejected_reason: str | None = None
    pose_frame_seq: int | None = None
    tracking_frame_seq: int | None = None
    pose_tracking_seq_delta: int | None = None
    pose_frame_age_ms: float | None = None
    pose_model_path: str | None = None
    pose_quality_level: str | None = None


class BehaviorStatus(BaseModel):
    enabled: bool = False
    state: str = "unknown"
    last_error: str | None = None


class TemporalStatus(BaseModel):
    enabled: bool = False
    feature_extractor_ok: bool = True
    window_size: int = 32
    active_tracks: int = 0
    fall_state: str = "normal"
    fall_probability: float = 0.0
    risk_level: str = "low"
    last_error: str | None = None
    model_provider: str = "mock"
    model_loaded: bool = True
    model_path: str | None = None
    model_input_size: int | None = None
    feature_schema_version: str | None = None
    feature_schema_hash: str | None = None
    model_last_error: str | None = None
    fallback_active: bool = False
    sc_tan_shadow_enabled: bool = False
    sc_tan_last_error: str | None = None
    rf_fusion_shadow_enabled: bool = False
    rf_fusion_last_error: str | None = None
    no_object_reset_count: int = 0
    last_reset_reason: str | None = None


class PipelineStatus(BaseModel):
    detection_worker_fps: float = 0.0
    fall_hint_worker_fps: float = 0.0
    fall_hint_latency_ms: float | None = None
    tracking_worker_fps: float = 0.0
    result_publish_fps: float = 0.0
    latest_detection_age_ms: float | None = None
    latest_fall_hint_age_ms: float | None = None
    latest_tracking_age_ms: float | None = None
    latest_pose_age_ms: float | None = None
    latest_temporal_age_ms: float | None = None
    latest_fused_age_ms: float | None = None
    detection_to_publish_lag_ms: float | None = None
    fusion_confirmed_count: int = 0
    fusion_candidate_count: int = 0
    fusion_suppressed_count: int = 0
    fusion_latest_guard_reason: str | None = None
    evidence_freshness: dict = Field(default_factory=dict)
    evidence_age_ms: dict = Field(default_factory=dict)
    last_error: str | None = None


class LatestResultStatus(BaseModel):
    camera_id: str | None = None
    timestamp: str | None = None
    latest_objects_count: int = 0
    latest_person_confidence: float | None = None
    latest_bbox: list[float] | None = None
    track_id: int | None = None
    pose_available: bool = False
    temporal_window_size: int | None = None
    temporal_source: str | None = None
    temporal_shadow_fall_probability: float | None = None
    fall_state: str | None = None
    alarm_confirmed: bool = False
    risk_level: str | None = None
    fall_prob: float | None = None
    fall_score: float | None = None
    incident_id: str | None = None
    snapshot_url: str | None = None
    snapshot_path: str | None = None
    fall_candidate_source: str | None = None
    fall_suppressed_reason: str | None = None
    confidence_level: str | None = None
    degraded_by: list[str] = Field(default_factory=list)
    frame_status: str | None = None
    camera_stream_state: str | None = None
    reason: str | None = None
    safe_to_interpret_as_no_fall: bool = True
    source_generation: int | None = None
    detector_debug: dict = Field(default_factory=dict)
    pose_debug: dict = Field(default_factory=dict)
    temporal_debug: dict = Field(default_factory=dict)


class PollingAlertStatus(BaseModel):
    camera_id: str | None = None
    status: str = "no_alert"
    should_popup: bool = False
    incident_id: str | None = None
    event_timestamp: str | None = None
    fall_state: str | None = None
    risk_level: str | None = None
    snapshot_url: str | None = None


class FallEventReporterStatus(BaseModel):
    enabled: bool = False
    running: bool = False
    endpoint: str | None = None
    endpoint_base_url: str | None = None
    endpoint_path: str | None = None
    queue_size: int = 0
    cooldown_seconds: float = 0.0
    last_post_status: str | None = None
    last_incident_id: str | None = None
    last_snapshot_url: str | None = None
    last_error: str | None = None
    last_post_body: str | None = None
    last_payload: dict | None = None
    outbox: dict | None = None


class StreamRuntimeAlias(BaseModel):
    source_url_masked: str | None = None
    stream_state: str = "disconnected"
    connected: bool = False
    frame_age_ms: float | None = None
    frame_status: str = "no_frame"
    source_generation: int = 0
    is_stale: bool = False
    frame_width: int | None = None
    frame_height: int | None = None
    capture_fps: float = 0.0


class DiagnosticsStatus(BaseModel):
    camera_lost: bool = False
    capture_stale: bool = False


class ConfigurationStatus(BaseModel):
    # This is intentionally a small allowlist. Hostnames, paths, credentials,
    # tokens, raw environment variables, and approval values never belong here.
    effective_config: dict = Field(default_factory=dict)
    config_sources: dict[str, str] = Field(default_factory=dict)
    feature_flags: dict = Field(default_factory=dict)
    startup_safety_errors: list[str] = Field(default_factory=list)


class VisionStatus(BaseModel):
    service_status: str = "running"
    runtime_profile: str = "default"
    cameras: list[CameraStatus] = Field(default_factory=list)
    detection: list[DetectionStatus] = Field(default_factory=list)
    streaming: StreamingStatus = Field(default_factory=StreamingStatus)
    tracking: TrackingStatus = Field(default_factory=TrackingStatus)
    identity: IdentityStatus = Field(default_factory=IdentityStatus)
    pose: PoseStatus = Field(default_factory=PoseStatus)
    behavior: BehaviorStatus = Field(default_factory=BehaviorStatus)
    temporal: TemporalStatus = Field(default_factory=TemporalStatus)
    pipeline: PipelineStatus = Field(default_factory=PipelineStatus)
    latest_result: LatestResultStatus = Field(default_factory=LatestResultStatus)
    polling_alert: PollingAlertStatus = Field(default_factory=PollingAlertStatus)
    fall_event_reporter: FallEventReporterStatus = Field(default_factory=FallEventReporterStatus)
    main_stream: StreamRuntimeAlias | None = None
    analysis_stream: StreamRuntimeAlias | None = None
    display_source_current: str = "single"
    display_source: str = "single"
    analysis_source: str = "single"
    display_fallback_active: bool = False
    diagnostics: DiagnosticsStatus = Field(default_factory=DiagnosticsStatus)
    workers: dict = Field(default_factory=dict)
    configuration: ConfigurationStatus = Field(default_factory=ConfigurationStatus)
