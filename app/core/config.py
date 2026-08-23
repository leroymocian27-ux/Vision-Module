from __future__ import annotations

import os
from urllib.parse import urlsplit
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


# Keep the source class of values loaded during import. This makes effective
# configuration observable without exposing a path, a secret, or raw env data.
_PROCESS_ENV_KEYS = frozenset(os.environ)
_ENV_VALUE_SOURCES: dict[str, str] = {}


def _load_env_file() -> None:
    explicit_path = os.getenv("VISION_SERVICE_ENV_FILE")
    candidates: list[tuple[Path, str]] = []
    if explicit_path:
        candidates.append((Path(explicit_path), "explicit_env_file"))
    candidates.append((Path(__file__).resolve().parents[2] / ".env", "project_env_file"))

    seen: set[Path] = set()
    for candidate, source_name in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if key in os.environ:
                if key in _PROCESS_ENV_KEYS:
                    _ENV_VALUE_SOURCES.setdefault(key, "process_env")
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ[key] = value
            _ENV_VALUE_SOURCES[key] = source_name


_load_env_file()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


def config_value_source(name: str) -> str:
    """Return only a source class, never a filesystem path or secret value."""
    if name in _PROCESS_ENV_KEYS or (name in os.environ and name not in _ENV_VALUE_SOURCES):
        return "process_env"
    return _ENV_VALUE_SOURCES.get(name, "default")


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "vision-service")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    runtime_profile: str = os.getenv("VISION_SERVICE_RUNTIME_PROFILE", "default")
    pipeline_mode: str = os.getenv("PIPELINE_MODE", "legacy").strip().lower()

    default_camera_id: str = os.getenv("DEFAULT_CAMERA_ID", "camera_01")
    default_rtsp_url: str | None = os.getenv("DEFAULT_RTSP_URL") or None
    mock_camera_enabled: bool = _get_bool("MOCK_CAMERA_ENABLED", True)
    mock_camera_width: int = _get_int("MOCK_CAMERA_WIDTH", 1280)
    mock_camera_height: int = _get_int("MOCK_CAMERA_HEIGHT", 720)
    mock_camera_fps: int = _get_int("MOCK_CAMERA_FPS", 25)
    camera_rtsp_username: str = os.getenv("CAMERA_RTSP_USERNAME", "admin")
    camera_rtsp_password: str = os.getenv("CAMERA_RTSP_PASSWORD", "")
    camera_rtsp_port: int = _get_int("CAMERA_RTSP_PORT", 10554)
    camera_rtsp_path: str = os.getenv("CAMERA_RTSP_PATH", "/tcp/av0_1")
    device_discovery_enabled: bool = _get_bool("DEVICE_DISCOVERY_ENABLED", True)
    device_discovery_config_path: str = os.getenv("DEVICE_DISCOVERY_CONFIG_PATH", "data/runtime/device_config.json")
    device_discovery_candidate_host_start: int = _get_int("DEVICE_DISCOVERY_CANDIDATE_HOST_START", 248)
    device_discovery_candidate_host_end: int = _get_int("DEVICE_DISCOVERY_CANDIDATE_HOST_END", 255)
    device_discovery_connect_timeout_ms: int = _get_int("DEVICE_DISCOVERY_CONNECT_TIMEOUT_MS", 500)
    device_discovery_scan_timeout_ms: int = _get_int("DEVICE_DISCOVERY_SCAN_TIMEOUT_MS", 5000)
    device_discovery_max_workers: int = _get_int("DEVICE_DISCOVERY_MAX_WORKERS", 8)

    capture_stale_timeout_sec: float = _get_float("CAPTURE_STALE_TIMEOUT_SEC", 3.0)
    frame_delayed_threshold_ms: int = _get_int("FRAME_DELAYED_THRESHOLD_MS", 1000)
    stream_stale_threshold_ms: int = _get_int("STREAM_STALE_THRESHOLD_MS", 3000)
    stream_stale_reconnect_after_ms: int = _get_int("STREAM_STALE_RECONNECT_AFTER_MS", 6000)
    capture_read_warn_ms: int = _get_int("CAPTURE_READ_WARN_MS", 500)
    capture_read_stale_ms: int = _get_int("CAPTURE_READ_STALE_MS", 3000)
    capture_force_reopen_after_slow_reads: int = _get_int("CAPTURE_FORCE_REOPEN_AFTER_SLOW_READS", 3)
    capture_read_watchdog_release_enabled: bool = _get_bool("CAPTURE_READ_WATCHDOG_RELEASE_ENABLED", False)
    capture_backend: str = os.getenv("CAPTURE_BACKEND", "opencv")
    capture_process_frame_timeout_ms: int = _get_int("CAPTURE_PROCESS_FRAME_TIMEOUT_MS", 2000)
    capture_process_open_timeout_ms: int = _get_int("CAPTURE_PROCESS_OPEN_TIMEOUT_MS", 5000)
    capture_process_read_timeout_ms: int = _get_int("CAPTURE_PROCESS_READ_TIMEOUT_MS", 5000)
    capture_process_restart_ms: int = _get_int("CAPTURE_PROCESS_RESTART_MS", 500)
    capture_ipc_mode: str = os.getenv("CAPTURE_IPC_MODE", "jpeg_pipe")
    capture_jpeg_quality: int = _get_int("CAPTURE_JPEG_QUALITY", 60)
    capture_process_output_height: int = _get_int("CAPTURE_PROCESS_OUTPUT_HEIGHT", 720)
    capture_process_write_fps: float = _get_float("CAPTURE_PROCESS_WRITE_FPS", 10.0)
    capture_process_max_restarts: int = _get_int("CAPTURE_PROCESS_MAX_RESTARTS", 0)
    opencv_capture_buffersize: int = _get_int("OPENCV_CAPTURE_BUFFERSIZE", 1)
    opencv_ffmpeg_capture_options: str = os.getenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
    reconnect_initial_delay_sec: float = _get_float("RECONNECT_INITIAL_DELAY_SEC", 1.0)
    reconnect_max_delay_sec: float = _get_float("RECONNECT_MAX_DELAY_SEC", 10.0)
    reconnect_backoff_schedule_sec: str = os.getenv("RECONNECT_BACKOFF_SCHEDULE_SEC", "1,2,5,10,30")

    detection_enabled: bool = _get_bool("DETECTION_ENABLED", True)
    yolo_model_path: str = os.getenv("YOLO_MODEL_PATH", "yolov8n.pt")
    yolo_confidence: float = _get_float("YOLO_CONFIDENCE", 0.35)
    yolo_imgsz: int = _get_int("YOLO_IMGSZ", 640)
    yolo_device: str | None = os.getenv("YOLO_DEVICE") or None
    detection_interval_ms: int = _get_int("DETECTION_INTERVAL_MS", 100)
    fall_detector_enabled: bool = _get_bool("FALL_DETECTOR_ENABLED", True)
    fall_hint_in_detection_service: bool = _get_bool("FALL_HINT_IN_DETECTION_SERVICE", True)
    fall_hint_worker_enabled: bool = _get_bool("FALL_HINT_WORKER_ENABLED", False)
    fall_hint_worker_fps: float = _get_float("FALL_HINT_WORKER_FPS", 3.0)
    fall_hint_max_frame_age_ms: int = _get_int("FALL_HINT_MAX_FRAME_AGE_MS", 800)
    fall_hint_result_ttl_ms: int = _get_int("FALL_HINT_RESULT_TTL_MS", 1500)
    fall_hint_inference_lock_wait_ms: int = _get_int("FALL_HINT_INFERENCE_LOCK_WAIT_MS", 80)
    fall_hint_skip_if_inference_busy: bool = _get_bool("FALL_HINT_SKIP_IF_INFERENCE_BUSY", True)
    fall_hint_circuit_breaker_enabled: bool = _get_bool("FALL_HINT_CIRCUIT_BREAKER_ENABLED", True)
    fall_hint_circuit_failure_threshold: int = _get_int("FALL_HINT_CIRCUIT_FAILURE_THRESHOLD", 5)
    fall_hint_circuit_cooldown_ms: int = _get_int("FALL_HINT_CIRCUIT_COOLDOWN_MS", 3000)
    person_detection_result_ttl_ms: int = _get_int("PERSON_DETECTION_RESULT_TTL_MS", 600)
    yolo_fall_model_path: str = os.getenv(
        "YOLO_FALL_MODEL_PATH",
        "models/yolo_fall_hint_v2_plus_b012_best.pt",
    )
    yolo_fall_confidence: float = _get_float("YOLO_FALL_CONFIDENCE", 0.25)
    yolo_fall_imgsz: int = _get_int("YOLO_FALL_IMGSZ", 640)
    yolo_fall_device: str | None = os.getenv("YOLO_FALL_DEVICE") or None
    fall_detector_interval_ms: int = _get_int("FALL_DETECTOR_INTERVAL_MS", 200)

    enable_tracking: bool = _get_bool("ENABLE_TRACKING", True)
    enable_identity: bool = _get_bool("ENABLE_IDENTITY", False)
    enable_target_binding: bool = _get_bool("ENABLE_TARGET_BINDING", False)
    identity_store_dir: str = os.getenv("IDENTITY_STORE_DIR", "data/identities")
    identity_max_images: int = _get_int("IDENTITY_MAX_IMAGES", 5)
    insightface_model_name: str = os.getenv("INSIGHTFACE_MODEL_NAME", "buffalo_l")
    insightface_ctx_id: int = _get_int("INSIGHTFACE_CTX_ID", 0)
    insightface_det_size: int = _get_int("INSIGHTFACE_DET_SIZE", 640)
    insightface_providers: str | None = os.getenv("INSIGHTFACE_PROVIDERS") or None
    identity_service_url: str = os.getenv("IDENTITY_SERVICE_URL", "http://127.0.0.1:8100")
    enable_identity_binding: bool = _get_bool("ENABLE_IDENTITY_BINDING", False)
    identity_request_timeout_ms: int = _get_int("IDENTITY_REQUEST_TIMEOUT_MS", 500)
    identity_match_interval_ms: int = _get_int("IDENTITY_MATCH_INTERVAL_MS", 1000)
    identity_match_threshold: float = _get_float("IDENTITY_MATCH_THRESHOLD", 0.45)
    identity_crop_padding_ratio: float = _get_float("IDENTITY_CROP_PADDING_RATIO", 0.12)
    identity_binding_async: bool = _get_bool("IDENTITY_BINDING_ASYNC", True)
    identity_health_ttl_ms: int = _get_int("IDENTITY_HEALTH_TTL_MS", 5000)
    identity_match_ttl_ms: int = _get_int("IDENTITY_MATCH_TTL_MS", 1000)
    identity_binding_worker_fps: float = _get_float("IDENTITY_BINDING_WORKER_FPS", 1.0)
    identity_max_inflight: int = _get_int("IDENTITY_MAX_INFLIGHT", 1)
    target_lost_after_ms: int = _get_int("TARGET_LOST_AFTER_MS", 1000)
    tracking_result_ttl_ms: int = _get_int("TRACKING_RESULT_TTL_MS", 1000)
    target_reacquire_after_ms: int = _get_int("TARGET_REACQUIRE_AFTER_MS", 3000)
    bytetrack_track_high_thresh: float = _get_float("BYTETRACK_TRACK_HIGH_THRESH", 0.5)
    bytetrack_track_low_thresh: float = _get_float("BYTETRACK_TRACK_LOW_THRESH", 0.1)
    bytetrack_new_track_thresh: float = _get_float("BYTETRACK_NEW_TRACK_THRESH", 0.6)
    bytetrack_match_thresh: float = _get_float("BYTETRACK_MATCH_THRESH", 0.8)
    bytetrack_track_buffer: int = _get_int("BYTETRACK_TRACK_BUFFER", 30)
    bytetrack_frame_rate: int = _get_int("BYTETRACK_FRAME_RATE", 10)
    bytetrack_fuse_score: bool = _get_bool("BYTETRACK_FUSE_SCORE", True)

    enable_pose: bool = _get_bool("ENABLE_POSE", False)
    pose_provider: str = os.getenv("POSE_PROVIDER", "disabled_placeholder")
    pose_fps: float = _get_float("POSE_FPS", 3.0)
    yolo_pose_model_path: str = os.getenv("YOLO_POSE_MODEL_PATH", "yolov8n-pose.pt")
    yolo_pose_confidence: float = _get_float("YOLO_POSE_CONFIDENCE", 0.25)
    yolo_pose_imgsz: int = _get_int("YOLO_POSE_IMGSZ", 640)
    yolo_pose_device: str | None = os.getenv("YOLO_POSE_DEVICE") or None
    yolo11_pose_model_path: str = os.getenv("YOLO11_POSE_MODEL_PATH", "yolo11n-pose.pt")
    yolo11_pose_confidence: float = _get_float("YOLO11_POSE_CONF", 0.12)
    yolo11_pose_imgsz: int = _get_int("YOLO11_POSE_IMGSZ", 640)
    yolo11_pose_device: str | None = os.getenv("YOLO11_POSE_DEVICE") or os.getenv("YOLO_POSE_DEVICE") or None
    yolo11_pose_half: bool = _get_bool("YOLO11_POSE_HALF", True)
    yolo11_pose_smoothing: bool = _get_bool("YOLO11_POSE_SMOOTHING", True)
    yolo11_pose_max_jump_ratio: float = _get_float("YOLO11_POSE_MAX_JUMP_RATIO", 0.18)
    yolo11_pose_min_match_iou: float = _get_float("YOLO11_POSE_MIN_MATCH_IOU", 0.12)
    yolo11_pose_max_center_distance_ratio: float = _get_float("YOLO11_POSE_MAX_CENTER_DISTANCE_RATIO", 0.65)
    yolo11_pose_match_score_threshold: float = _get_float("YOLO11_POSE_MATCH_SCORE_THRESHOLD", 0.30)
    branch4_pose_confidence: float = _get_float("BRANCH4_POSE_CONF", 0.2)
    branch4_pose_imgsz: int = _get_int("BRANCH4_POSE_IMGSZ", 640)
    branch4_pose_half: bool = _get_bool("BRANCH4_POSE_HALF", True)
    branch4_pose_crop_padding_ratio: float = _get_float("BRANCH4_POSE_CROP_PADDING_RATIO", 0.18)
    rtmpose_config_path: str = os.getenv(
        "RTMPOSE_CONFIG_PATH",
        "models/rtmpose/rtmpose-l_8xb256-420e_coco-384x288.py",
    )
    rtmpose_checkpoint_path: str = os.getenv(
        "RTMPOSE_CHECKPOINT_PATH",
        "models/rtmpose/rtmpose-l_simcc-coco_pt-aic-coco_420e-384x288-9ec0a4e5_20230127.pth",
    )
    rtmpose_device: str | None = os.getenv("RTMPOSE_DEVICE") or None
    rtmpose_bbox_thr: float = _get_float("RTMPOSE_BBOX_THR", 0.2)
    rtmpose_onnx_model_path: str = os.getenv(
        "RTMPOSE_ONNX_MODEL_PATH",
        "models/rtmpose/rtmpose-x-body7-384x288.onnx",
    )
    rtmpose_onnx_input_width: int = _get_int("RTMPOSE_ONNX_INPUT_WIDTH", 288)
    rtmpose_onnx_input_height: int = _get_int("RTMPOSE_ONNX_INPUT_HEIGHT", 384)
    pose_crop_padding_ratio: float = _get_float("POSE_CROP_PADDING_RATIO", 0.06)
    pose_fallen_crop_padding_ratio: float = _get_float("POSE_FALLEN_CROP_PADDING_RATIO", 0.14)
    pose_min_skeleton_confidence: float = _get_float("POSE_MIN_SKELETON_CONFIDENCE", 0.35)
    pose_min_keypoint_inside_ratio: float = _get_float("POSE_MIN_KEYPOINT_INSIDE_RATIO", 0.65)
    pose_min_fallen_keypoint_inside_ratio: float = _get_float("POSE_MIN_FALLEN_KEYPOINT_INSIDE_RATIO", 0.60)
    pose_min_candidate_iou: float = _get_float("POSE_MIN_CANDIDATE_IOU", 0.25)
    pose_min_fallen_candidate_iou: float = _get_float("POSE_MIN_FALLEN_CANDIDATE_IOU", 0.15)
    pose_max_tracking_frame_delta: int = _get_int("POSE_MAX_TRACKING_FRAME_DELTA", 2)
    pose_max_frame_age_ms: int = _get_int("POSE_MAX_FRAME_AGE_MS", 800)
    pose_skip_when_inference_busy: bool = _get_bool("POSE_SKIP_WHEN_INFERENCE_BUSY", True)
    pose_inference_lock_wait_ms: int = _get_int("POSE_INFERENCE_LOCK_WAIT_MS", 160)
    pose_max_inference_ms: int = _get_int("POSE_MAX_INFERENCE_MS", 1500)
    pose_slow_inference_circuit_breaker_count: int = _get_int("POSE_SLOW_INFERENCE_CIRCUIT_BREAKER_COUNT", 3)
    pose_circuit_breaker_cooldown_ms: int = _get_int("POSE_CIRCUIT_BREAKER_COOLDOWN_MS", 10000)
    pose_fallback_to_detection: bool = _get_bool("POSE_FALLBACK_TO_DETECTION", False)
    pose_fallback_min_confidence: float = _get_float("POSE_FALLBACK_MIN_CONFIDENCE", 0.5)

    enable_behavior: bool = _get_bool("ENABLE_BEHAVIOR", False)
    behavior_rapid_descent_px_per_sec: float = _get_float("BEHAVIOR_RAPID_DESCENT_PX_PER_SEC", 260.0)
    behavior_long_still_sec: float = _get_float("BEHAVIOR_LONG_STILL_SEC", 5.0)
    behavior_still_velocity_px_per_sec: float = _get_float("BEHAVIOR_STILL_VELOCITY_PX_PER_SEC", 18.0)

    tracking_worker_fps: float = _get_float("TRACKING_WORKER_FPS", 20.0)
    pose_worker_fps: float = _get_float("POSE_WORKER_FPS", 3.0)
    result_publish_fps: float = _get_float("RESULT_PUBLISH_FPS", 20.0)
    pose_result_ttl_ms: int = _get_int("POSE_RESULT_TTL_MS", 800)
    pose_publish_max_frame_delta: int = _get_int("POSE_PUBLISH_MAX_FRAME_DELTA", 8)
    behavior_result_ttl_ms: int = _get_int("BEHAVIOR_RESULT_TTL_MS", 1500)
    temporal_worker_enabled: bool = _get_bool("TEMPORAL_WORKER_ENABLED", False)
    temporal_worker_fps: float = _get_float("TEMPORAL_WORKER_FPS", 3.0)
    temporal_result_ttl_ms: int = _get_int("TEMPORAL_RESULT_TTL_MS", 1500)
    temporal_max_frame_delta: int = _get_int("TEMPORAL_MAX_FRAME_DELTA", 12)
    fusion_worker_enabled: bool = _get_bool("FUSION_WORKER_ENABLED", False)
    fusion_worker_fps: float = _get_float("FUSION_WORKER_FPS", 10.0)
    fused_result_ttl_ms: int = _get_int("FUSED_RESULT_TTL_MS", 1000)
    fusion_evidence_debug_enabled: bool = _get_bool("FUSION_EVIDENCE_DEBUG_ENABLED", True)
    fusion_max_frame_delta_detection: int = _get_int("FUSION_MAX_FRAME_DELTA_DETECTION", 12)
    fusion_max_frame_delta_tracking: int = _get_int("FUSION_MAX_FRAME_DELTA_TRACKING", 18)
    fusion_max_frame_delta_fall_hint: int = _get_int("FUSION_MAX_FRAME_DELTA_FALL_HINT", 8)

    enable_temporal: bool = _get_bool("ENABLE_TEMPORAL", False)
    feature_window_size: int = _get_int("FEATURE_WINDOW_SIZE", 32)
    temporal_no_object_reset_frames: int = _get_int("TEMPORAL_NO_OBJECT_RESET_FRAMES", 3)
    temporal_track_mode: str = os.getenv("TEMPORAL_TRACK_MODE", "all_tracks")
    temporal_sequence_key_mode: str = os.getenv("TEMPORAL_SEQUENCE_KEY_MODE", "identity")
    temporal_model_provider: str = os.getenv("TEMPORAL_MODEL_PROVIDER", "mock")
    temporal_onnx_model_path: str = os.getenv("TEMPORAL_ONNX_MODEL_PATH", "models/fall_lstm_v5.onnx")
    temporal_feature_schema_path: str = os.getenv(
        "TEMPORAL_FEATURE_SCHEMA_PATH",
        "models/fall_lstm_v5_features.json",
    )
    temporal_model_window_size: int = _get_int("TEMPORAL_MODEL_WINDOW_SIZE", 32)
    temporal_model_input_dim: int = _get_int("TEMPORAL_MODEL_INPUT_DIM", 15)
    temporal_warmup_min_size: int = _get_int("TEMPORAL_WARMUP_MIN_SIZE", 16)
    temporal_fallback_to_mock: bool = _get_bool("TEMPORAL_FALLBACK_TO_MOCK", False)
    temporal_onnx_providers: str = os.getenv(
        "TEMPORAL_ONNX_PROVIDERS",
        "CUDAExecutionProvider,CPUExecutionProvider",
    )
    unstable_frame_threshold: int = _get_int("UNSTABLE_FRAME_THRESHOLD", 3)
    falling_prob_threshold: float = _get_float("FALLING_PROB_THRESHOLD", 0.65)
    low_confidence_fallen_candidate_enabled: bool = _get_bool("LOW_CONFIDENCE_FALLEN_CANDIDATE_ENABLED", True)
    low_confidence_fallen_candidate_max_confidence: float = _get_float("LOW_CONFIDENCE_FALLEN_CANDIDATE_MAX_CONFIDENCE", 0.35)
    low_confidence_fallen_candidate_min_probability: float = _get_float("LOW_CONFIDENCE_FALLEN_CANDIDATE_MIN_PROBABILITY", 0.35)
    low_confidence_fallen_candidate_min_window: int = _get_int("LOW_CONFIDENCE_FALLEN_CANDIDATE_MIN_WINDOW", 8)
    fall_detector_promote_unmatched: bool = _get_bool("FALL_DETECTOR_PROMOTE_UNMATCHED", True)
    fall_detector_promote_min_confidence: float = _get_float("FALL_DETECTOR_PROMOTE_MIN_CONFIDENCE", 0.12)
    fall_detector_confirm_enabled: bool = _get_bool("FALL_DETECTOR_CONFIRM_ENABLED", True)
    fall_detector_confirm_min_probability: float = _get_float("FALL_DETECTOR_CONFIRM_MIN_PROBABILITY", 0.32)
    fall_detector_confirm_min_person_confidence: float = _get_float("FALL_DETECTOR_CONFIRM_MIN_PERSON_CONFIDENCE", 0.2)
    fall_detector_confirm_frames: int = _get_int("FALL_DETECTOR_CONFIRM_FRAMES", 4)
    fall_detector_confirm_ms: int = _get_int("FALL_DETECTOR_CONFIRM_MS", 900)
    field_fall_candidate_enabled: bool = _get_bool("FIELD_FALL_CANDIDATE_ENABLED", True)
    field_fall_candidate_requires_recent_fall_hint: bool = _get_bool("FIELD_FALL_CANDIDATE_REQUIRES_RECENT_FALL_HINT", True)
    field_fall_candidate_recent_hint_ms: int = _get_int("FIELD_FALL_CANDIDATE_RECENT_HINT_MS", 15000)
    field_fall_candidate_min_aspect: float = _get_float("FIELD_FALL_CANDIDATE_MIN_ASPECT", 0.8)
    field_fall_candidate_min_center_y_norm: float = _get_float("FIELD_FALL_CANDIDATE_MIN_CENTER_Y_NORM", 0.48)
    field_fall_candidate_max_height_norm: float = _get_float("FIELD_FALL_CANDIDATE_MAX_HEIGHT_NORM", 0.42)
    field_fall_candidate_max_speed: float = _get_float("FIELD_FALL_CANDIDATE_MAX_SPEED", 38.0)
    field_fall_candidate_min_window: int = _get_int("FIELD_FALL_CANDIDATE_MIN_WINDOW", 16)
    field_fall_candidate_confirm_frames: int = _get_int("FIELD_FALL_CANDIDATE_CONFIRM_FRAMES", 6)
    field_fall_candidate_confirm_ms: int = _get_int("FIELD_FALL_CANDIDATE_CONFIRM_MS", 1200)
    fall_confirm_frames: int = _get_int("FALL_CONFIRM_FRAMES", 5)
    fall_still_ms: int = _get_int("FALL_STILL_MS", 1500)
    cooldown_seconds: float = _get_float("COOLDOWN_SECONDS", 10.0)
    fall_v6_scoring_enabled: bool = _get_bool("FALL_V6_SCORING_ENABLED", True)
    fall_v6_decision_enabled: bool = _get_bool("FALL_V6_DECISION_ENABLED", False)
    fall_v6_debug_payload: bool = _get_bool("FALL_V6_DEBUG_PAYLOAD", True)
    sc_tan_shadow_enabled: bool = _get_bool("SC_TAN_SHADOW_ENABLED", True)
    sc_tan_min_window: int = _get_int("SC_TAN_MIN_WINDOW", 8)
    sc_tan_top_k: int = _get_int("SC_TAN_TOP_K", 5)
    rf_fusion_shadow_enabled: bool = _get_bool("RF_FUSION_SHADOW_ENABLED", True)
    rf_fusion_min_window: int = _get_int("RF_FUSION_MIN_WINDOW", 8)
    unified_decision_enabled: bool = _get_bool("UNIFIED_DECISION_ENABLED", False)
    unified_decision_shadow: bool = _get_bool("UNIFIED_DECISION_SHADOW", True)
    unified_decision_primary_enabled: bool = _get_bool("UNIFIED_DECISION_PRIMARY_ENABLED", False)
    fall_evidence_confirm_threshold: float = _get_float("FALL_EVIDENCE_CONFIRM_THRESHOLD", 0.75)
    adl_suppression_confirm_max: float = _get_float("ADL_SUPPRESSION_CONFIRM_MAX", 0.45)
    adl_suppression_slow_max: float = _get_float("ADL_SUPPRESSION_SLOW_MAX", 0.55)
    adl_suppression_block_threshold: float = _get_float("ADL_SUPPRESSION_BLOCK_THRESHOLD", 0.65)
    track_quality_min_confirm: float = _get_float("TRACK_QUALITY_MIN_CONFIRM", 0.70)
    slow_fall_enabled: bool = _get_bool("SLOW_FALL_ENABLED", True)
    slow_fall_hold_ms: int = _get_int("SLOW_FALL_HOLD_MS", 5000)
    slow_fall_floor_contact_min: float = _get_float("SLOW_FALL_FLOOR_CONTACT_MIN", 0.60)
    slow_fall_support_surface_max: float = _get_float("SLOW_FALL_SUPPORT_SURFACE_MAX", 0.40)
    recovery_cancel_threshold: float = _get_float("RECOVERY_CANCEL_THRESHOLD", 0.60)
    uncertain_track_quality_min: float = _get_float("UNCERTAIN_TRACK_QUALITY_MIN", 0.50)

    post_fall_v2_enabled: bool = _get_bool("POST_FALL_V2_ENABLED", pipeline_mode == "post_fall_v2")
    post_fall_v2_shadow_enabled: bool = _get_bool("POST_FALL_V2_SHADOW_ENABLED", False)
    post_fall_v2_binary_model_path: str = os.getenv(
        "POST_FALL_V2_BINARY_MODEL_PATH",
        "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx",
    )
    post_fall_v2_model_path: str = os.getenv(
        "POST_FALL_V2_MODEL_PATH",
        os.getenv("POST_FALL_V2_BINARY_MODEL_PATH", "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx"),
    )
    post_fall_v2_binary_model_sha256: str = os.getenv(
        "POST_FALL_V2_BINARY_MODEL_SHA256",
        "e9871cdb4687055fb5d934dd994c2ad883adac0c2acab375c240f8e005ee04cc",
    )
    post_fall_v2_input_policy: str = os.getenv("POST_FALL_V2_INPUT_POLICY", "FULL_FRAME_TRAIN_MATCHED")
    post_fall_v2_shadow_sample_fps: float = _get_float("POST_FALL_V2_SHADOW_SAMPLE_FPS", 2.0)
    post_fall_v2_shadow_max_frame_age_ms: int = _get_int("POST_FALL_V2_SHADOW_MAX_FRAME_AGE_MS", 1000)
    post_fall_v2_shadow_queue_size: int = _get_int("POST_FALL_V2_SHADOW_QUEUE_SIZE", 2)
    post_fall_v2_binary_candidate_threshold: float = _get_float(
        "POST_FALL_V2_BINARY_CANDIDATE_THRESHOLD",
        0.3979087471961975,
    )
    # Engineering/default threshold from current OOF evidence; NOT_PRODUCTION_CALIBRATED.
    post_fall_v2_binary_threshold: float = _get_float(
        "POST_FALL_V2_BINARY_THRESHOLD",
        _get_float("POST_FALL_V2_BINARY_CANDIDATE_THRESHOLD", 0.3979087471961975),
    )
    post_fall_v2_sample_fps: float = _get_float("POST_FALL_V2_SAMPLE_FPS", 5.0)
    post_fall_v2_max_frame_age_ms: int = _get_int("POST_FALL_V2_MAX_FRAME_AGE_MS", 1000)
    post_fall_v2_queue_size: int = _get_int("POST_FALL_V2_QUEUE_SIZE", 2)
    post_fall_v2_window_size: int = _get_int("POST_FALL_V2_WINDOW_SIZE", 8)
    post_fall_v2_min_positive_frames: int = _get_int("POST_FALL_V2_MIN_POSITIVE_FRAMES", 4)
    post_fall_v2_min_consecutive_frames: int = _get_int("POST_FALL_V2_MIN_CONSECUTIVE_FRAMES", 3)
    post_fall_v2_candidate_min_ms: int = _get_int("POST_FALL_V2_CANDIDATE_MIN_MS", 800)
    post_fall_v2_recovery_min_ms: int = _get_int("POST_FALL_V2_RECOVERY_MIN_MS", 1500)
    post_fall_v2_cooldown_ms: int = _get_int("POST_FALL_V2_COOLDOWN_MS", 3000)
    post_fall_v2_event_buffer_seconds: float = _get_float("POST_FALL_V2_EVENT_BUFFER_SECONDS", 8.0)
    post_fall_v2_vlm_enabled: bool = _get_bool("POST_FALL_V2_VLM_ENABLED", False)
    post_fall_v2_vlm_timeout_seconds: float = _get_float("POST_FALL_V2_VLM_TIMEOUT_SECONDS", 8.0)
    post_fall_v2_qwen_enabled: bool = _get_bool("POST_FALL_V2_QWEN_ENABLED", post_fall_v2_vlm_enabled)
    post_fall_v2_qwen_provider: str = os.getenv("POST_FALL_V2_QWEN_PROVIDER", "dummy").strip().lower()
    post_fall_v2_qwen_model: str = os.getenv("POST_FALL_V2_QWEN_MODEL", os.getenv("EVENT_QWEN_KEYFRAME_MODEL", "qwen3.5:4b"))
    post_fall_v2_qwen_base_url: str = os.getenv(
        "POST_FALL_V2_QWEN_BASE_URL",
        os.getenv("EVENT_QWEN_KEYFRAME_ENDPOINT", "http://127.0.0.1:11434/api/chat"),
    )
    post_fall_v2_qwen_timeout_seconds: float = _get_float(
        "POST_FALL_V2_QWEN_TIMEOUT_SECONDS",
        _get_float("EVENT_QWEN_KEYFRAME_TIMEOUT_SECONDS", 90.0),
    )
    post_fall_v2_qwen_max_images: int = _get_int("POST_FALL_V2_QWEN_MAX_IMAGES", 6)
    post_fall_v2_qwen_max_image_bytes: int = _get_int("POST_FALL_V2_QWEN_MAX_IMAGE_BYTES", 5242880)
    post_fall_v2_qwen_image_max_edge: int = _get_int("POST_FALL_V2_QWEN_IMAGE_MAX_EDGE", 1280)
    post_fall_v2_qwen_jpeg_quality: int = _get_int("POST_FALL_V2_QWEN_JPEG_QUALITY", 85)
    post_fall_v2_qwen_queue_capacity: int = _get_int("POST_FALL_V2_QWEN_QUEUE_CAPACITY", 2)
    post_fall_v2_keyframe_post_collection_enabled: bool = _get_bool(
        "POST_FALL_V2_KEYFRAME_POST_COLLECTION_ENABLED",
        post_fall_v2_qwen_enabled and post_fall_v2_qwen_provider == "qwen_keyframe",
    )
    post_fall_v2_keyframe_tolerance_ms: int = _get_int("POST_FALL_V2_KEYFRAME_TOLERANCE_MS", 750)
    post_fall_v2_keyframe_collection_timeout_seconds: float = _get_float(
        "POST_FALL_V2_KEYFRAME_COLLECTION_TIMEOUT_SECONDS",
        5.0,
    )
    post_fall_v2_aux_person_detection_enabled: bool = _get_bool("POST_FALL_V2_AUX_PERSON_DETECTION_ENABLED", False)
    post_fall_v2_binary_onnx_providers: str = os.getenv(
        "POST_FALL_V2_BINARY_ONNX_PROVIDERS",
        "CPUExecutionProvider",
    )
    post_fall_v2_shadow_save_results: bool = _get_bool("POST_FALL_V2_SHADOW_SAVE_RESULTS", True)
    post_fall_v2_shadow_output_dir: str = os.getenv(
        "POST_FALL_V2_SHADOW_OUTPUT_DIR",
        "artifacts/post_fall_v2/shadow",
    )
    post_fall_v2_shadow_save_frames: bool = _get_bool("POST_FALL_V2_SHADOW_SAVE_FRAMES", False)
    post_fall_v2_shadow_save_frame_probability_threshold: float = _get_float(
        "POST_FALL_V2_SHADOW_SAVE_FRAME_PROBABILITY_THRESHOLD",
        0.30,
    )
    post_fall_v2_shadow_save_max_frames_per_minute: int = _get_int(
        "POST_FALL_V2_SHADOW_SAVE_MAX_FRAMES_PER_MINUTE",
        6,
    )

    webrtc_stun_server: str = os.getenv(
        "WEBRTC_STUN_SERVER",
        "stun:stun.l.google.com:19302",
    )
    webrtc_video_fps: int = _get_int("WEBRTC_VIDEO_FPS", 25)

    main_system_alert_enabled: bool = _get_bool("MAIN_SYSTEM_ALERT_ENABLED", False)
    main_system_report_dry_run: bool = _get_bool("MAIN_SYSTEM_REPORT_DRY_RUN", False)
    main_system_base_url: str = os.getenv("MAIN_SYSTEM_BASE_URL", "http://127.0.0.1:8090/api/v1")
    main_system_fall_event_path: str = os.getenv("MAIN_SYSTEM_FALL_EVENT_PATH", "/video-bridge/fall-events")
    main_system_alert_timeout_ms: int = _get_int("MAIN_SYSTEM_ALERT_TIMEOUT_MS", 10000)
    main_system_alert_cooldown_seconds: float = _get_float("MAIN_SYSTEM_ALERT_COOLDOWN_SECONDS", 90.0)
    main_system_alert_token: str = os.getenv("MAIN_SYSTEM_ALERT_TOKEN", "")
    main_system_alert_token_header: str = os.getenv("MAIN_SYSTEM_ALERT_TOKEN_HEADER", "X-Vision-Service-Token")
    main_system_default_port: int = _get_int("MAIN_SYSTEM_DEFAULT_PORT", 8000)
    main_system_base_prefix: str = os.getenv("MAIN_SYSTEM_BASE_PREFIX", "/api/v1")
    vision_service_public_base_url: str = os.getenv("VISION_SERVICE_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    fall_event_snapshot_dir: str = os.getenv("FALL_EVENT_SNAPSHOT_DIR", "logs/fall_events/snapshots")
    alert_outbox_enabled: bool = _get_bool("ALERT_OUTBOX_ENABLED", False)
    alert_outbox_path: str = os.getenv("ALERT_OUTBOX_PATH", "data/alert_outbox.sqlite3")
    alert_outbox_retry_limit: int = _get_int("ALERT_OUTBOX_RETRY_LIMIT", 10)

    # The event-semantic pipeline is additive and intentionally disabled until
    # its evidence and delivery behavior is explicitly enabled for a deployment.
    event_pipeline_enabled: bool = _get_bool("EVENT_PIPELINE_ENABLED", False)
    event_ring_buffer_enabled: bool = _get_bool("EVENT_RING_BUFFER_ENABLED", False)
    event_worker_enabled: bool = _get_bool("EVENT_WORKER_ENABLED", False)
    event_semantic_enabled: bool = _get_bool("EVENT_SEMANTIC_ENABLED", False)
    event_vlm_enabled: bool = _get_bool("EVENT_VLM_ENABLED", False)
    event_vlm_provider: str = os.getenv("EVENT_VLM_PROVIDER", "dummy")
    event_vlm_http_mock_url: str = os.getenv("EVENT_VLM_ENDPOINT", os.getenv("EVENT_VLM_HTTP_MOCK_URL", ""))
    event_vlm_timeout_seconds: float = _get_float("EVENT_VLM_TIMEOUT_SECONDS", 8.0)
    event_vlm_max_keyframes: int = _get_int("EVENT_VLM_MAX_KEYFRAMES", 6)
    event_vlm_include_timeline_image: bool = _get_bool("EVENT_VLM_INCLUDE_TIMELINE_IMAGE", True)
    event_vlm_prompt_version: str = os.getenv("EVENT_VLM_PROMPT_VERSION", "fall_event_review_v1")
    event_vlm_output_schema_version: str = os.getenv("EVENT_VLM_OUTPUT_SCHEMA_VERSION", "vlm_review_result_v1")
    event_vlm_max_image_bytes: int = _get_int("EVENT_VLM_MAX_IMAGE_BYTES", 5242880)
    event_vlm_fail_open: bool = _get_bool("EVENT_VLM_FAIL_OPEN", True)
    event_vlm_http_headers_json: str = os.getenv("EVENT_VLM_HTTP_HEADERS_JSON", "")
    event_vlm_request_mode: str = os.getenv("EVENT_VLM_REQUEST_MODE", "json")
    event_vlm_provider_name: str = os.getenv("EVENT_VLM_PROVIDER_NAME", "qwen")
    event_vlm_ollama_endpoint: str = os.getenv(
        "EVENT_VLM_OLLAMA_ENDPOINT",
        os.getenv("EVENT_OLLAMA_ENDPOINT", os.getenv("EVENT_OLLAMA_BASE_URL", "http://127.0.0.1:11434/api/chat")),
    )
    event_vlm_ollama_model: str = os.getenv("EVENT_VLM_OLLAMA_MODEL", os.getenv("EVENT_OLLAMA_MODEL", "qwen3.5:4b"))
    event_vlm_ollama_fallback_model: str = os.getenv(
        "EVENT_VLM_OLLAMA_FALLBACK_MODEL",
        os.getenv("EVENT_OLLAMA_COMPARE_MODEL", "qwen3.5:4b"),
    )
    event_vlm_ollama_timeout_seconds: float = _get_float(
        "EVENT_VLM_OLLAMA_TIMEOUT_SECONDS",
        _get_float("EVENT_OLLAMA_TIMEOUT_SECONDS", 15.0),
    )
    event_vlm_ollama_text_only: bool = _get_bool("EVENT_VLM_OLLAMA_TEXT_ONLY", True)
    event_vlm_ollama_include_images: bool = _get_bool("EVENT_VLM_OLLAMA_INCLUDE_IMAGES", False)
    event_vlm_ollama_allow_non_localhost: bool = _get_bool("EVENT_VLM_OLLAMA_ALLOW_NON_LOCALHOST", _get_bool("EVENT_OLLAMA_ALLOW_NON_LOCALHOST", False))
    # Multimodal keyframe review is deliberately a separate sidecar from the
    # text-only event VLM. Image input remains default-off and local-only.
    event_qwen_keyframe_analysis_enabled: bool = _get_bool("EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED", False)
    event_qwen_keyframe_analyze_candidates: bool = _get_bool("EVENT_QWEN_KEYFRAME_ANALYZE_CANDIDATES", False)
    event_qwen_keyframe_max_images: int = _get_int("EVENT_QWEN_KEYFRAME_MAX_IMAGES", 6)
    event_qwen_keyframe_timeout_seconds: float = _get_float(
        "EVENT_QWEN_KEYFRAME_TIMEOUT_SECONDS", _get_float("EVENT_VLM_OLLAMA_TIMEOUT_SECONDS", 90.0)
    )
    event_qwen_keyframe_max_image_bytes: int = _get_int("EVENT_QWEN_KEYFRAME_MAX_IMAGE_BYTES", 5242880)
    event_qwen_keyframe_endpoint: str = os.getenv(
        "EVENT_QWEN_KEYFRAME_ENDPOINT",
        os.getenv("EVENT_VLM_OLLAMA_ENDPOINT", os.getenv("EVENT_OLLAMA_ENDPOINT", "http://127.0.0.1:11434/api/chat")),
    )
    event_qwen_keyframe_model: str = os.getenv(
        "EVENT_QWEN_KEYFRAME_MODEL", os.getenv("EVENT_VLM_OLLAMA_MODEL", os.getenv("EVENT_OLLAMA_MODEL", "qwen3.5:4b"))
    )
    # Backward-compatible attribute names for the first local-Ollama audit.
    event_ollama_base_url: str = event_vlm_ollama_endpoint
    event_ollama_model: str = event_vlm_ollama_model
    event_ollama_compare_model: str = event_vlm_ollama_fallback_model
    event_ollama_timeout_seconds: float = event_vlm_ollama_timeout_seconds
    event_ollama_allow_image_input: bool = event_vlm_ollama_include_images
    event_ollama_allow_non_localhost: bool = event_vlm_ollama_allow_non_localhost
    event_outbox_backend: str = os.getenv("EVENT_OUTBOX_BACKEND", "memory")
    event_outbox_sqlite_path: str = os.getenv("EVENT_OUTBOX_SQLITE_PATH", "data/event_outbox.sqlite3")
    event_ring_buffer_seconds: float = _get_float("EVENT_RING_BUFFER_SECONDS", 8.0)
    event_ring_buffer_max_frames: int = _get_int("EVENT_RING_BUFFER_MAX_FRAMES", 96)
    event_ring_buffer_max_bytes: int = _get_int("EVENT_RING_BUFFER_MAX_BYTES", 134217728)
    event_worker_lock_ttl_seconds: float = _get_float("EVENT_WORKER_LOCK_TTL_SECONDS", 30.0)
    event_incident_cooldown_seconds: float = _get_float("EVENT_INCIDENT_COOLDOWN_SECONDS", 30.0)
    event_keyframe_offsets_ms: tuple[int, ...] = tuple(
        int(part.strip())
        for part in os.getenv("EVENT_KEYFRAME_OFFSETS_MS", "-3000,-1000,0,1000,3000,5000").split(",")
        if part.strip()
    )
    event_post_keyframe_collection_enabled: bool = _get_bool("EVENT_POST_KEYFRAME_COLLECTION_ENABLED", False)
    event_post_keyframe_window_seconds: float = _get_float("EVENT_POST_KEYFRAME_WINDOW_SECONDS", 5.0)
    event_archive_enabled: bool = _get_bool("EVENT_ARCHIVE_ENABLED", False)
    event_archive_dir: str = os.getenv("EVENT_ARCHIVE_DIR", "logs/event_archive")
    event_archive_save_keyframes: bool = _get_bool("EVENT_ARCHIVE_SAVE_KEYFRAMES", True)
    event_archive_save_json: bool = _get_bool("EVENT_ARCHIVE_SAVE_JSON", True)
    event_archive_max_events_per_camera: int = _get_int("EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA", 200)
    event_archive_retention_days: int = _get_int("EVENT_ARCHIVE_RETENTION_DAYS", 30)
    # Archived evidence is private by default. Enable only for a trusted
    # internal demo network after the archive access policy is reviewed.
    event_keyframe_serving_enabled: bool = _get_bool("EVENT_KEYFRAME_SERVING_ENABLED", False)
    event_delivery_enabled: bool = _get_bool("EVENT_DELIVERY_ENABLED", False)
    event_delivery_mode: str = os.getenv("EVENT_DELIVERY_MODE", "dry_run")
    event_delivery_backend: str = os.getenv("EVENT_DELIVERY_BACKEND", "memory")
    event_delivery_sqlite_path: str = os.getenv("EVENT_DELIVERY_SQLITE_PATH", "data/event_delivery_outbox.sqlite3")
    event_delivery_worker_enabled: bool = _get_bool("EVENT_DELIVERY_WORKER_ENABLED", False)
    event_delivery_worker_interval_seconds: float = _get_float("EVENT_DELIVERY_WORKER_INTERVAL_SECONDS", 2.0)
    event_delivery_claim_ttl_seconds: float = _get_float("EVENT_DELIVERY_CLAIM_TTL_SECONDS", 30.0)
    event_delivery_target_url: str = os.getenv("EVENT_DELIVERY_TARGET_URL", os.getenv("EVENT_DELIVERY_ENDPOINT", ""))
    event_delivery_timeout_seconds: float = _get_float("EVENT_DELIVERY_TIMEOUT_SECONDS", main_system_alert_timeout_ms / 1000)
    event_delivery_retry_limit: int = _get_int("EVENT_DELIVERY_RETRY_LIMIT", _get_int("EVENT_DELIVERY_MAX_RETRIES", 3))
    event_delivery_retry_backoff_seconds: float = _get_float("EVENT_DELIVERY_RETRY_BACKOFF_SECONDS", 5.0)

    # Robot integration remains a mock-only, opt-in boundary until the separate
    # robot service and its physical-safety gates have been accepted.
    robot_assist_enabled: bool = _get_bool("ROBOT_ASSIST_ENABLED", False)
    robot_assist_mode: str = os.getenv("ROBOT_ASSIST_MODE", "mock").strip().lower()
    robot_auto_dispatch_enabled: bool = _get_bool("ROBOT_AUTO_DISPATCH_ENABLED", False)
    go2_read_only_enabled: bool = _get_bool("GO2_READ_ONLY_ENABLED", False)
    go2_control_enabled: bool = _get_bool("GO2_CONTROL_ENABLED", False)
    go2_low_level_control_enabled: bool = _get_bool("GO2_LOW_LEVEL_CONTROL_ENABLED", False)
    go2_control_approved: bool = _get_bool("GO2_CONTROL_APPROVED", False)
    qwen_media_input_enabled: bool = _get_bool(
        "QWEN_MEDIA_INPUT_ENABLED",
        _get_bool("EVENT_VLM_OLLAMA_INCLUDE_IMAGES", False),
    )
    qwen_media_privacy_approved: bool = _get_bool("QWEN_MEDIA_PRIVACY_APPROVED", False)
    event_delivery_post_approved: bool = _get_bool("EVENT_DELIVERY_POST_APPROVED", False)

    pose_deployment_guard_enabled: bool = _get_bool("POSE_DEPLOYMENT_GUARD_ENABLED", True)
    pose_evidence_package: str = os.getenv(
        "POSE_EVIDENCE_PACKAGE",
        "evaluations/pose_evidence_package_check_20260705.json",
    )
    pose_deployment_guard_output: str = os.getenv(
        "POSE_DEPLOYMENT_GUARD_OUTPUT",
        "evaluations/pose_deployment_guard_20260705.json",
    )

    @property
    def device_config_path(self) -> str:
        return self.device_discovery_config_path

    def __post_init__(self) -> None:
        if self.event_outbox_backend not in {"memory", "sqlite"}:
            raise ValueError("EVENT_OUTBOX_BACKEND must be memory or sqlite")
        if self.event_vlm_provider not in {"disabled", "dummy", "http_mock", "http", "qwen_http", "ollama", "qwen_ollama", "ollama_qwen"}:
            if self.event_vlm_enabled:
                raise ValueError("EVENT_VLM_PROVIDER must be disabled, dummy, http_mock, http, qwen_http, ollama, qwen_ollama, or ollama_qwen")
            object.__setattr__(self, "event_vlm_provider", "dummy")
        if self.event_vlm_request_mode != "json":
            raise ValueError("EVENT_VLM_REQUEST_MODE must be json")
        if self.event_qwen_keyframe_max_images < 1 or self.event_qwen_keyframe_max_images > 6:
            raise ValueError("EVENT_QWEN_KEYFRAME_MAX_IMAGES must be between 1 and 6")
        if self.event_qwen_keyframe_max_image_bytes < 1024:
            raise ValueError("EVENT_QWEN_KEYFRAME_MAX_IMAGE_BYTES must be at least 1024")
        if self.event_delivery_mode not in {"dry_run", "post"}:
            raise ValueError("EVENT_DELIVERY_MODE must be dry_run or post")
        if self.event_delivery_backend not in {"memory", "sqlite"}:
            raise ValueError("EVENT_DELIVERY_BACKEND must be memory or sqlite")
        if self.robot_assist_mode not in {"mock", "go2"}:
            raise ValueError("ROBOT_ASSIST_MODE must be mock or go2")
        if self.post_fall_v2_input_policy not in {"FULL_FRAME_TRAIN_MATCHED", "EXPERIMENTAL_PERSON_ROI"}:
            raise ValueError("POST_FALL_V2_INPUT_POLICY must be FULL_FRAME_TRAIN_MATCHED or EXPERIMENTAL_PERSON_ROI")
        if self.post_fall_v2_shadow_sample_fps <= 0:
            raise ValueError("POST_FALL_V2_SHADOW_SAMPLE_FPS must be positive")
        if self.post_fall_v2_shadow_queue_size < 1:
            raise ValueError("POST_FALL_V2_SHADOW_QUEUE_SIZE must be at least 1")
        allowed_modes = {"legacy", "async_v1", "fall_disabled", "post_fall_v2"}
        if self.pipeline_mode not in allowed_modes:
            raise ValueError(f"PIPELINE_MODE must be one of {sorted(allowed_modes)}, got {self.pipeline_mode!r}")

        if self.post_fall_v2_sample_fps <= 0:
            raise ValueError("POST_FALL_V2_SAMPLE_FPS must be positive")
        if self.post_fall_v2_queue_size < 1:
            raise ValueError("POST_FALL_V2_QUEUE_SIZE must be at least 1")
        if self.post_fall_v2_window_size < 1:
            raise ValueError("POST_FALL_V2_WINDOW_SIZE must be at least 1")
        if self.post_fall_v2_min_positive_frames < 1:
            raise ValueError("POST_FALL_V2_MIN_POSITIVE_FRAMES must be at least 1")
        if self.post_fall_v2_min_consecutive_frames < 1:
            raise ValueError("POST_FALL_V2_MIN_CONSECUTIVE_FRAMES must be at least 1")
        if self.post_fall_v2_event_buffer_seconds <= 0:
            raise ValueError("POST_FALL_V2_EVENT_BUFFER_SECONDS must be positive")
        if self.post_fall_v2_qwen_provider not in {"dummy", "qwen_keyframe"}:
            raise ValueError("POST_FALL_V2_QWEN_PROVIDER must be dummy or qwen_keyframe")
        if self.post_fall_v2_qwen_max_images < 1 or self.post_fall_v2_qwen_max_images > 6:
            raise ValueError("POST_FALL_V2_QWEN_MAX_IMAGES must be between 1 and 6")
        if self.post_fall_v2_qwen_max_image_bytes < 1024:
            raise ValueError("POST_FALL_V2_QWEN_MAX_IMAGE_BYTES must be at least 1024")
        if self.post_fall_v2_qwen_image_max_edge < 128:
            raise ValueError("POST_FALL_V2_QWEN_IMAGE_MAX_EDGE must be at least 128")
        if self.post_fall_v2_qwen_jpeg_quality < 40 or self.post_fall_v2_qwen_jpeg_quality > 95:
            raise ValueError("POST_FALL_V2_QWEN_JPEG_QUALITY must be between 40 and 95")
        if self.post_fall_v2_qwen_queue_capacity < 1:
            raise ValueError("POST_FALL_V2_QWEN_QUEUE_CAPACITY must be at least 1")
        if self.post_fall_v2_keyframe_tolerance_ms < 0:
            raise ValueError("POST_FALL_V2_KEYFRAME_TOLERANCE_MS must be non-negative")
        if self.post_fall_v2_keyframe_collection_timeout_seconds <= 0:
            raise ValueError("POST_FALL_V2_KEYFRAME_COLLECTION_TIMEOUT_SECONDS must be positive")
        if self.pipeline_mode == "post_fall_v2" and not self.post_fall_v2_enabled:
            raise ValueError("PIPELINE_MODE=post_fall_v2 requires POST_FALL_V2_ENABLED=true")

        if self.pipeline_mode == "legacy":
            if not self.fall_hint_in_detection_service or self.fall_hint_worker_enabled:
                raise ValueError(
                    "PIPELINE_MODE=legacy requires FALL_HINT_IN_DETECTION_SERVICE=true "
                    "and FALL_HINT_WORKER_ENABLED=false"
                )
        elif self.pipeline_mode == "async_v1":
            if self.fall_hint_in_detection_service or not self.fall_hint_worker_enabled:
                raise ValueError(
                    "PIPELINE_MODE=async_v1 requires FALL_HINT_IN_DETECTION_SERVICE=false "
                    "and FALL_HINT_WORKER_ENABLED=true"
                )
        elif self.pipeline_mode == "fall_disabled":
            if self.fall_hint_in_detection_service or self.fall_hint_worker_enabled or self.fall_detector_enabled:
                raise ValueError(
                    "PIPELINE_MODE=fall_disabled requires FALL_HINT_IN_DETECTION_SERVICE=false, "
                    "FALL_HINT_WORKER_ENABLED=false, and FALL_DETECTOR_ENABLED=false"
                )

        if self.unified_decision_primary_enabled and not self.unified_decision_enabled:
            raise ValueError(
                "UNIFIED_DECISION_PRIMARY_ENABLED=true requires UNIFIED_DECISION_ENABLED=true"
            )

    def startup_safety_errors(self) -> list[str]:
        """Report unsafe enabled combinations without reading or returning secrets."""
        errors: list[str] = []
        if self.go2_low_level_control_enabled:
            errors.append("GO2_LOW_LEVEL_CONTROL_ENABLED must remain false")
        if self.go2_control_enabled and not self.go2_control_approved:
            errors.append("GO2_CONTROL_ENABLED requires GO2_CONTROL_APPROVED=true")
        if self.go2_control_enabled and not self.robot_assist_enabled:
            errors.append("GO2_CONTROL_ENABLED requires ROBOT_ASSIST_ENABLED=true")
        if self.qwen_media_input_enabled and not self.qwen_media_privacy_approved:
            errors.append("QWEN_MEDIA_INPUT_ENABLED requires QWEN_MEDIA_PRIVACY_APPROVED=true")
        if self.event_qwen_keyframe_analysis_enabled:
            endpoint = urlsplit(self.event_qwen_keyframe_endpoint)
            if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
                errors.append("EVENT_QWEN_KEYFRAME_ENDPOINT must use localhost")
            if not self.qwen_media_input_enabled or not self.qwen_media_privacy_approved:
                errors.append("EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED requires approved local media input")
            if not self.event_pipeline_enabled or not self.event_archive_enabled or not self.event_archive_save_keyframes or not self.event_archive_save_json:
                errors.append("EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED requires pipeline archive, keyframes, and JSON archive")
            if not self.event_qwen_keyframe_model:
                errors.append("EVENT_QWEN_KEYFRAME_MODEL is required when keyframe analysis is enabled")
        if self.post_fall_v2_qwen_enabled and self.post_fall_v2_qwen_provider == "qwen_keyframe":
            endpoint = urlsplit(self.post_fall_v2_qwen_base_url)
            if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
                errors.append("POST_FALL_V2_QWEN_BASE_URL must use localhost")
            if not self.qwen_media_input_enabled or not self.qwen_media_privacy_approved:
                errors.append("POST_FALL_V2_QWEN_ENABLED requires approved local media input")
            if not self.post_fall_v2_qwen_model:
                errors.append("POST_FALL_V2_QWEN_MODEL is required when PFV2 Qwen is enabled")
        if self.event_delivery_enabled and self.event_delivery_mode == "post":
            if not self.event_delivery_post_approved:
                errors.append("EVENT_DELIVERY_MODE=post requires EVENT_DELIVERY_POST_APPROVED=true")
            if not self.event_delivery_target_url:
                errors.append("EVENT_DELIVERY_MODE=post requires EVENT_DELIVERY_TARGET_URL")
            if not (self.main_system_alert_token_header and self.main_system_alert_token):
                errors.append("EVENT_DELIVERY_MODE=post requires configured main-system token header and token")
        return errors


_SAFE_CONFIG_FIELDS: dict[str, tuple[str, str]] = {
    "pipeline_mode": ("PIPELINE_MODE", "pipeline_mode"),
    "main_system_alert_enabled": ("MAIN_SYSTEM_ALERT_ENABLED", "main_system_alert_enabled"),
    "event_pipeline_enabled": ("EVENT_PIPELINE_ENABLED", "event_pipeline_enabled"),
    "event_ring_buffer_enabled": ("EVENT_RING_BUFFER_ENABLED", "event_ring_buffer_enabled"),
    "event_worker_enabled": ("EVENT_WORKER_ENABLED", "event_worker_enabled"),
    "event_semantic_enabled": ("EVENT_SEMANTIC_ENABLED", "event_semantic_enabled"),
    "event_delivery_enabled": ("EVENT_DELIVERY_ENABLED", "event_delivery_enabled"),
    "event_delivery_mode": ("EVENT_DELIVERY_MODE", "event_delivery_mode"),
    "event_delivery_backend": ("EVENT_DELIVERY_BACKEND", "event_delivery_backend"),
    "event_delivery_worker_enabled": ("EVENT_DELIVERY_WORKER_ENABLED", "event_delivery_worker_enabled"),
    "event_vlm_enabled": ("EVENT_VLM_ENABLED", "event_vlm_enabled"),
    "event_vlm_provider": ("EVENT_VLM_PROVIDER", "event_vlm_provider"),
    "event_vlm_ollama_text_only": ("EVENT_VLM_OLLAMA_TEXT_ONLY", "event_vlm_ollama_text_only"),
    "event_vlm_ollama_include_images": ("EVENT_VLM_OLLAMA_INCLUDE_IMAGES", "event_vlm_ollama_include_images"),
    "event_qwen_keyframe_analysis_enabled": ("EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED", "event_qwen_keyframe_analysis_enabled"),
    "post_fall_v2_enabled": ("POST_FALL_V2_ENABLED", "post_fall_v2_enabled"),
    "post_fall_v2_sample_fps": ("POST_FALL_V2_SAMPLE_FPS", "post_fall_v2_sample_fps"),
    "post_fall_v2_binary_threshold": ("POST_FALL_V2_BINARY_THRESHOLD", "post_fall_v2_binary_threshold"),
    "post_fall_v2_window_size": ("POST_FALL_V2_WINDOW_SIZE", "post_fall_v2_window_size"),
    "post_fall_v2_min_positive_frames": ("POST_FALL_V2_MIN_POSITIVE_FRAMES", "post_fall_v2_min_positive_frames"),
    "post_fall_v2_min_consecutive_frames": ("POST_FALL_V2_MIN_CONSECUTIVE_FRAMES", "post_fall_v2_min_consecutive_frames"),
    "post_fall_v2_vlm_enabled": ("POST_FALL_V2_VLM_ENABLED", "post_fall_v2_vlm_enabled"),
    "post_fall_v2_qwen_enabled": ("POST_FALL_V2_QWEN_ENABLED", "post_fall_v2_qwen_enabled"),
    "post_fall_v2_qwen_provider": ("POST_FALL_V2_QWEN_PROVIDER", "post_fall_v2_qwen_provider"),
    "post_fall_v2_qwen_model": ("POST_FALL_V2_QWEN_MODEL", "post_fall_v2_qwen_model"),
    "post_fall_v2_shadow_enabled": ("POST_FALL_V2_SHADOW_ENABLED", "post_fall_v2_shadow_enabled"),
    "post_fall_v2_input_policy": ("POST_FALL_V2_INPUT_POLICY", "post_fall_v2_input_policy"),
    "post_fall_v2_shadow_sample_fps": ("POST_FALL_V2_SHADOW_SAMPLE_FPS", "post_fall_v2_shadow_sample_fps"),
    "robot_assist_enabled": ("ROBOT_ASSIST_ENABLED", "robot_assist_enabled"),
    "robot_assist_mode": ("ROBOT_ASSIST_MODE", "robot_assist_mode"),
    "robot_auto_dispatch_enabled": ("ROBOT_AUTO_DISPATCH_ENABLED", "robot_auto_dispatch_enabled"),
    "go2_read_only_enabled": ("GO2_READ_ONLY_ENABLED", "go2_read_only_enabled"),
    "go2_control_enabled": ("GO2_CONTROL_ENABLED", "go2_control_enabled"),
    "go2_low_level_control_enabled": ("GO2_LOW_LEVEL_CONTROL_ENABLED", "go2_low_level_control_enabled"),
}


def safe_configuration_snapshot(settings: Settings) -> dict[str, Any]:
    """Return public configuration truth without values that can identify a host or credential."""
    effective_config = {
        public_name: getattr(settings, attribute)
        for public_name, (_, attribute) in _SAFE_CONFIG_FIELDS.items()
    }
    config_sources = {
        public_name: config_value_source(env_name)
        for public_name, (env_name, _) in _SAFE_CONFIG_FIELDS.items()
    }
    feature_flags = {
        key: effective_config[key]
        for key in (
            "event_pipeline_enabled",
            "event_delivery_enabled",
            "event_vlm_enabled",
            "event_qwen_keyframe_analysis_enabled",
            "post_fall_v2_enabled",
            "post_fall_v2_shadow_enabled",
            "post_fall_v2_vlm_enabled",
            "post_fall_v2_qwen_enabled",
            "robot_assist_enabled",
            "robot_auto_dispatch_enabled",
            "go2_read_only_enabled",
            "go2_control_enabled",
        )
    }
    return {
        "effective_config": effective_config,
        "config_sources": config_sources,
        "feature_flags": feature_flags,
        "startup_safety_errors": settings.startup_safety_errors(),
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
