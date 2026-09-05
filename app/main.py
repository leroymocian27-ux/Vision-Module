from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import alerting_api, device_discovery_api, event_api, fall_events_api, identity_api, integration_api, rest_api, runtime_control_api, status_api, webrtc_api, ws_api
from app.camera.source_manager import CameraSourceManager
from app.core.config import get_settings, safe_configuration_snapshot
from app.core.logger import configure_logging, get_logger
from app.core.runtime import Runtime
from app.events.pipeline import EventPipelineService
from app.events.delivery_worker import DeliveryWorker
from app.detection.realtime_result_store import RealtimeResultStore
from app.detection.result_store import ResultStore
from app.services.behavior_service import BehaviorService
from app.services.alert_outbox_service import AlertOutboxService
from app.services.alert_simulator_service import AlertSimulatorService
from app.services.detection_service import DetectionService
from app.services.device_connection_service import DeviceConnectionService
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.fall_hint_worker_service import FallHintWorkerService
from app.services.identity_binding_service import IdentityBindingService
from app.services.identity_binding_worker_service import IdentityBindingWorkerService
from app.services.identity_service import IdentityService
from app.services.pose_service import PoseService
from app.services.pose_worker_service import PoseWorkerService
from app.services.result_publisher_service import ResultPublisherService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.status_service import StatusService
from app.services.stream_service import StreamService
from app.services.temporal_service import TemporalService
from app.services.temporal_worker_service import TemporalWorkerService
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService
from app.fall.fusion import FallFusionService
from app.post_fall_v2.fall_binary_shadow_service import FallBinaryShadowService
from app.post_fall_v2.follow_target import FollowTargetReceiver
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.qwen_fall_analyzer import PFV2QwenFallAnalyzer
from app.post_fall_v2.vlm_review_service import VLMReviewService
from app.post_fall_v2.evidence_exporter import PostFallEvidenceExporter
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.post_fall_v2.detection_session_orchestrator import DetectionSessionOrchestrator
from app.integration.identity_client import IdentityClient
from app.streaming.peer_manager import PeerManager
from app.streaming.result_channel_manager import ResultChannelManager

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    device_connection_service = DeviceConnectionService(settings=settings)
    if settings.device_discovery_enabled:
        try:
            resolution = device_connection_service.startup_resolve()
            settings = resolution.settings
            logger.info("device_connection_startup_resolved status=%s", resolution.status.get("discovery"))
        except Exception:
            logger.exception("device_connection_startup_resolve_failed")
    safety_errors = settings.startup_safety_errors()
    if safety_errors:
        raise RuntimeError("startup safety configuration rejected: " + "; ".join(safety_errors))
    logger.info("safe_configuration_summary=%s", safe_configuration_snapshot(settings))
    _enforce_pose_deployment_guard(settings)
    _enforce_cuda_runtime_guard(settings)

    event_pipeline = EventPipelineService(settings)
    event_delivery_worker = DeliveryWorker(settings, event_pipeline.delivery_outbox)
    source_manager = CameraSourceManager(settings, frame_observer=event_pipeline.record_frame_packet)
    realtime_store = RealtimeResultStore()
    result_store = ResultStore()
    result_channels = ResultChannelManager()
    result_channels.bind_loop(asyncio.get_running_loop())
    tracking_service = TrackingService(settings=settings)
    identity_service = IdentityService(settings=settings)
    identity_client = IdentityClient(settings=settings)
    identity_binding_service = IdentityBindingService(settings=settings, client=identity_client)
    identity_binding_worker_service = IdentityBindingWorkerService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        identity_binding_service=identity_binding_service,
    )
    pose_service = PoseService(settings=settings)
    behavior_service = BehaviorService(settings=settings)
    temporal_service = TemporalService(settings=settings)
    fall_fusion_service = FallFusionService(settings=settings)
    alert_outbox_service = AlertOutboxService(settings=settings)
    fall_event_reporter = FallEventReporterService(
        settings=settings,
        source_manager=source_manager,
        alert_outbox=alert_outbox_service,
    )
    fall_event_reporter.start()
    alert_simulator_service = AlertSimulatorService(reporter=fall_event_reporter)
    detection_service = DetectionService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
    )
    fall_hint_worker_service = FallHintWorkerService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
    )
    tracking_worker_service = TrackingWorkerService(
        settings=settings,
        realtime_store=realtime_store,
        tracking_service=tracking_service,
        identity_binding_service=identity_binding_service,
    )
    pose_worker_service = PoseWorkerService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        pose_service=pose_service,
        behavior_service=behavior_service,
    )
    result_publisher_service = ResultPublisherService(
        settings=settings,
        realtime_store=realtime_store,
        result_channels=result_channels,
        temporal_service=temporal_service,
        fall_fusion_service=fall_fusion_service,
        fall_event_reporter=fall_event_reporter,
        event_pipeline=event_pipeline,
    )
    temporal_worker_service = TemporalWorkerService(
        settings=settings,
        realtime_store=realtime_store,
        temporal_service=temporal_service,
    )
    fusion_worker_service = FusionWorkerService(
        settings=settings,
        realtime_store=realtime_store,
        result_builder=result_publisher_service,
    )
    post_fall_v2_shadow_service = FallBinaryShadowService(
        settings=settings,
        source_manager=source_manager,
    )
    follow_target_receiver = FollowTargetReceiver(
        enabled=settings.follow_target_enabled,
        host=settings.follow_target_udp_host,
        port=settings.follow_target_udp_port,
    )
    follow_target_receiver.start()
    post_fall_v2_vlm_review_service = VLMReviewService(
        enabled=settings.post_fall_v2_vlm_enabled,
        timeout_seconds=(
            settings.post_fall_v2_qwen_timeout_seconds
            if settings.post_fall_v2_qwen_provider == "qwen_keyframe"
            else settings.post_fall_v2_vlm_timeout_seconds
        ),
        queue_capacity=settings.post_fall_v2_qwen_queue_capacity,
    )
    post_fall_v2_evidence_exporter = PostFallEvidenceExporter(
        enabled=settings.post_fall_v2_evidence_export_enabled,
        binary_output_dir=settings.post_fall_v2_binary_evidence_dir,
        qwen_output_dir=settings.post_fall_v2_qwen_evidence_dir,
    )
    post_fall_test_archive_service = PostFallTestArchiveService(
        settings.test_event_root,
        drain_timeout_seconds=settings.test_drain_timeout_seconds,
    )
    post_fall_v2_runtime_service = PostFallV2RuntimeService(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        result_channels=result_channels,
        event_pipeline=event_pipeline,
        vlm_review_service=post_fall_v2_vlm_review_service,
        evidence_exporter=post_fall_v2_evidence_exporter,
        test_archive_service=post_fall_test_archive_service,
        fall_event_reporter=fall_event_reporter,
        follow_target_receiver=follow_target_receiver,
        manual_control_enabled=True,
    )
    if settings.post_fall_v2_qwen_enabled and settings.post_fall_v2_qwen_provider == "qwen_keyframe":
        post_fall_v2_vlm_review_service.analyzer = PFV2QwenFallAnalyzer.from_config(
            endpoint_url=settings.post_fall_v2_qwen_base_url,
            model_name=settings.post_fall_v2_qwen_model,
            timeout_seconds=settings.post_fall_v2_qwen_timeout_seconds,
            num_ctx=settings.post_fall_v2_qwen_num_ctx,
            max_output_tokens=settings.post_fall_v2_qwen_max_output_tokens,
            temperature=settings.post_fall_v2_qwen_temperature,
            context_retry_enabled=settings.post_fall_v2_qwen_context_retry_enabled,
            image_provider=post_fall_v2_runtime_service.qwen_images_for_incident,
        )
    stream_service = StreamService(
        settings=settings,
        source_manager=source_manager,
        detection_service=detection_service,
        realtime_store=realtime_store,
        tracking_service=tracking_service,
        fall_hint_worker_service=fall_hint_worker_service,
        identity_binding_service=identity_binding_service,
        temporal_service=temporal_service,
        temporal_worker_service=temporal_worker_service,
        fusion_worker_service=fusion_worker_service,
        tracking_worker_service=tracking_worker_service,
        identity_binding_worker_service=identity_binding_worker_service,
        pose_worker_service=pose_worker_service,
        result_publisher_service=result_publisher_service,
        fall_fusion_service=fall_fusion_service,
        post_fall_v2_shadow_service=post_fall_v2_shadow_service,
        post_fall_v2_runtime_service=post_fall_v2_runtime_service,
    )
    detection_session_orchestrator = DetectionSessionOrchestrator(
        settings=settings,
        stream_service=stream_service,
        post_fall_service=post_fall_v2_runtime_service,
        archive_service=post_fall_test_archive_service,
    )
    peer_manager = PeerManager(settings=settings, source_manager=source_manager)
    status_service = StatusService(
        settings=settings,
        source_manager=source_manager,
        detection_service=detection_service,
        fall_hint_worker_service=fall_hint_worker_service,
        peer_manager=peer_manager,
        result_channels=result_channels,
        realtime_store=realtime_store,
        tracking_service=tracking_service,
        tracking_worker_service=tracking_worker_service,
        identity_service=identity_service,
        identity_binding_service=identity_binding_service,
        identity_binding_worker_service=identity_binding_worker_service,
        pose_service=pose_service,
        behavior_service=behavior_service,
        temporal_service=temporal_service,
        temporal_worker_service=temporal_worker_service,
        fusion_worker_service=fusion_worker_service,
        fall_fusion_service=fall_fusion_service,
        result_publisher_service=result_publisher_service,
        fall_event_reporter=fall_event_reporter,
        post_fall_v2_shadow_service=post_fall_v2_shadow_service,
        post_fall_v2_runtime_service=post_fall_v2_runtime_service,
    )
    runtime = Runtime(
        settings=settings,
        source_manager=source_manager,
        realtime_store=realtime_store,
        result_store=result_store,
        result_channels=result_channels,
        tracking_service=tracking_service,
        detection_service=detection_service,
        fall_hint_worker_service=fall_hint_worker_service,
        identity_service=identity_service,
        identity_binding_service=identity_binding_service,
        identity_binding_worker_service=identity_binding_worker_service,
        pose_service=pose_service,
        behavior_service=behavior_service,
        temporal_service=temporal_service,
        temporal_worker_service=temporal_worker_service,
        fusion_worker_service=fusion_worker_service,
        post_fall_v2_shadow_service=post_fall_v2_shadow_service,
        post_fall_v2_runtime_service=post_fall_v2_runtime_service,
        follow_target_receiver=follow_target_receiver,
        fall_fusion_service=fall_fusion_service,
        fall_event_reporter=fall_event_reporter,
        alert_simulator_service=alert_simulator_service,
        tracking_worker_service=tracking_worker_service,
        pose_worker_service=pose_worker_service,
        result_publisher_service=result_publisher_service,
        stream_service=stream_service,
        peer_manager=peer_manager,
        status_service=status_service,
        device_connection_service=device_connection_service,
        event_pipeline=event_pipeline,
        event_delivery_worker=event_delivery_worker,
        post_fall_test_archive_service=post_fall_test_archive_service,
        detection_session_orchestrator=detection_session_orchestrator,
    )
    app.state.runtime = runtime
    event_pipeline.start()
    event_delivery_worker.start()

    auto_start_source = (
        settings.default_rtsp_url
        or (settings.go2_mjpeg_url if settings.video_source_mode == "mjpeg" else None)
    )
    if settings.auto_start_stream and (auto_start_source or settings.mock_camera_enabled):
        try:
            runtime.stream_service.start(settings.default_camera_id, auto_start_source)
            logger.info("default_stream_started camera_id=%s", settings.default_camera_id)
        except Exception:
            logger.exception("default_stream_start_failed")

    try:
        yield
    finally:
        await runtime.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(title="Vision Service", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(status_api.router)
    app.include_router(rest_api.router)
    app.include_router(runtime_control_api.router)
    app.include_router(webrtc_api.router)
    app.include_router(ws_api.router)
    app.include_router(identity_api.router)
    app.include_router(fall_events_api.router)
    app.include_router(integration_api.router)
    app.include_router(alerting_api.router)
    app.include_router(device_discovery_api.router)
    app.include_router(event_api.router)

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend_demo"
    if frontend_dir.exists():
        app.mount("/demo", StaticFiles(directory=frontend_dir, html=True), name="demo")
    return app


app = create_app()


def _should_run_app_pose_deployment_guard(settings: Any) -> bool:
    return bool(
        getattr(settings, "pose_deployment_guard_enabled", True)
        and getattr(settings, "enable_pose", False)
        and getattr(settings, "main_system_alert_enabled", False)
    )


def _enforce_pose_deployment_guard(settings: Any) -> dict[str, Any] | None:
    if not _should_run_app_pose_deployment_guard(settings):
        return None

    from scripts.check_pose_deployment_guard import build_deployment_guard_report_from_env

    report = build_deployment_guard_report_from_env(
        env=_pose_guard_env_from_settings(settings),
        env_path="app_settings",
        evidence_package_path=Path(getattr(settings, "pose_evidence_package")),
        mode="production",
    )
    output_path = Path(getattr(settings, "pose_deployment_guard_output"))
    if not output_path.is_absolute():
        output_path = Path(__file__).resolve().parents[1] / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if summary.get("deployment_allowed") is not True:
        logger.error("pose_deployment_guard_rejected_startup summary=%s", summary)
        raise RuntimeError("pose deployment guard rejected app startup")
    return report


def _pose_guard_env_from_settings(settings: Any) -> dict[str, str]:
    values = {
        "ENABLE_POSE": _bool_text(getattr(settings, "enable_pose", False)),
        "POSE_PROVIDER": getattr(settings, "pose_provider", "disabled_placeholder"),
        "POSE_WORKER_FPS": getattr(settings, "pose_worker_fps", 3.0),
        "POSE_FPS": getattr(settings, "pose_fps", 3.0),
        "POSE_RESULT_TTL_MS": getattr(settings, "pose_result_ttl_ms", 800),
        "POSE_MAX_FRAME_AGE_MS": getattr(settings, "pose_max_frame_age_ms", 800),
        "POSE_MAX_TRACKING_FRAME_DELTA": getattr(settings, "pose_max_tracking_frame_delta", 2),
        "POSE_INFERENCE_LOCK_WAIT_MS": getattr(settings, "pose_inference_lock_wait_ms", 160),
        "POSE_FALLBACK_TO_DETECTION": _bool_text(getattr(settings, "pose_fallback_to_detection", False)),
        "YOLO_POSE_MODEL_PATH": getattr(settings, "yolo_pose_model_path", ""),
        "YOLO_POSE_DEVICE": getattr(settings, "yolo_pose_device", "") or "",
        "YOLO11_POSE_MODEL_PATH": getattr(settings, "yolo11_pose_model_path", ""),
        "YOLO11_POSE_DEVICE": getattr(settings, "yolo11_pose_device", "") or "",
        "RTMPOSE_ONNX_MODEL_PATH": getattr(settings, "rtmpose_onnx_model_path", ""),
        "RTMPOSE_CHECKPOINT_PATH": getattr(settings, "rtmpose_checkpoint_path", ""),
        "RTMPOSE_DEVICE": getattr(settings, "rtmpose_device", "") or "",
    }
    return {key: str(value) for key, value in values.items()}


def _bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def _should_enforce_cuda_runtime_guard(settings: Any) -> bool:
    return bool(getattr(settings, "vision_service_require_cuda", True))


def _enforce_cuda_runtime_guard(settings: Any) -> dict[str, Any] | None:
    if not _should_enforce_cuda_runtime_guard(settings):
        return None

    errors: list[str] = []
    evidence: dict[str, Any] = {"python": sys.executable}

    expected_python = str(getattr(settings, "vision_service_cuda_python_path", "") or "").strip()
    if expected_python:
        try:
            running_python = Path(sys.executable).resolve()
            required_python = Path(expected_python).resolve()
            evidence["required_python"] = str(required_python)
            if running_python != required_python:
                errors.append(
                    "Python interpreter must be the configured CUDA interpreter: "
                    f"expected {required_python}, got {running_python}"
                )
        except OSError as exc:
            errors.append(f"Could not verify CUDA Python interpreter path: {exc}")

    torch_info = _inspect_torch_cuda()
    evidence["torch"] = torch_info
    if torch_info.get("error"):
        errors.append(f"torch CUDA check failed: {torch_info['error']}")
    elif not torch_info.get("cuda_available"):
        errors.append("torch.cuda.is_available() is false")
    elif int(torch_info.get("device_count") or 0) < 1:
        errors.append("torch reports zero CUDA devices")

    ort_info = _inspect_onnxruntime_cuda()
    evidence["onnxruntime"] = ort_info
    if ort_info.get("error"):
        errors.append(f"onnxruntime CUDA provider check failed: {ort_info['error']}")
    elif "CUDAExecutionProvider" not in set(ort_info.get("available_providers") or []):
        errors.append(
            "onnxruntime does not expose CUDAExecutionProvider; "
            f"available providers are {ort_info.get('available_providers')}"
        )

    _require_cuda_device("YOLO_DEVICE", getattr(settings, "yolo_device", None), errors, enabled=getattr(settings, "detection_enabled", True))
    _require_cuda_device(
        "YOLO_FALL_DEVICE",
        getattr(settings, "yolo_fall_device", None),
        errors,
        enabled=getattr(settings, "fall_detector_enabled", True),
    )
    _require_cuda_device(
        "YOLO_POSE_DEVICE",
        getattr(settings, "yolo_pose_device", None),
        errors,
        enabled=getattr(settings, "enable_pose", False) and getattr(settings, "pose_provider", "") == "yolo",
    )
    _require_cuda_device(
        "YOLO11_POSE_DEVICE",
        getattr(settings, "yolo11_pose_device", None),
        errors,
        enabled=getattr(settings, "enable_pose", False) and getattr(settings, "pose_provider", "") == "yolo11_legacy",
    )
    _require_cuda_device(
        "RTMPOSE_DEVICE",
        getattr(settings, "rtmpose_device", None),
        errors,
        enabled=getattr(settings, "enable_pose", False) and getattr(settings, "pose_provider", "") in {"rtmpose", "mmpose_finetuned"},
    )

    if getattr(settings, "post_fall_v2_enabled", False):
        _require_cuda_provider_chain(
            "POST_FALL_V2_BINARY_ONNX_PROVIDERS",
            getattr(settings, "post_fall_v2_binary_onnx_providers", ""),
            errors,
        )
    if getattr(settings, "enable_temporal", False) and getattr(settings, "temporal_model_provider", "") == "onnx_lstm":
        _require_cuda_provider_chain(
            "TEMPORAL_ONNX_PROVIDERS",
            getattr(settings, "temporal_onnx_providers", ""),
            errors,
        )

    if getattr(settings, "post_fall_v2_qwen_enabled", False) and getattr(settings, "post_fall_v2_qwen_provider", "") == "qwen_keyframe":
        ollama_info = _inspect_ollama_cuda_model(
            endpoint_url=getattr(settings, "post_fall_v2_qwen_base_url", ""),
            model_name=getattr(settings, "post_fall_v2_qwen_model", ""),
        )
        evidence["ollama"] = ollama_info
        if ollama_info.get("error"):
            errors.append(f"Ollama CUDA check failed: {ollama_info['error']}")
        elif not ollama_info.get("model_loaded"):
            errors.append(f"Ollama model is not loaded: {getattr(settings, 'post_fall_v2_qwen_model', '')}")
        elif not ollama_info.get("processor_is_gpu"):
            errors.append(
                "Ollama model is not fully loaded in GPU memory: "
                f"size={ollama_info.get('size')} size_vram={ollama_info.get('size_vram')}"
            )

    if errors:
        logger.error("cuda_runtime_guard_rejected_startup errors=%s evidence=%s", errors, evidence)
        raise RuntimeError("CUDA runtime guard rejected app startup: " + "; ".join(errors))

    logger.info("cuda_runtime_guard_passed evidence=%s", evidence)
    return evidence


def _inspect_torch_cuda() -> dict[str, Any]:
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_available else 0
        device_name = torch.cuda.get_device_name(0) if device_count > 0 else None
        return {
            "version": getattr(torch, "__version__", None),
            "cuda_version": getattr(getattr(torch, "version", None), "cuda", None),
            "cuda_available": cuda_available,
            "device_count": device_count,
            "device_name": device_name,
        }
    except Exception as exc:  # pragma: no cover - depends on deployment env
        return {"error": str(exc)}


def _inspect_onnxruntime_cuda() -> dict[str, Any]:
    try:
        import onnxruntime as ort

        return {
            "version": getattr(ort, "__version__", None),
            "available_providers": list(ort.get_available_providers()),
        }
    except Exception as exc:  # pragma: no cover - depends on deployment env
        return {"error": str(exc)}


def _require_cuda_device(name: str, value: Any, errors: list[str], *, enabled: bool) -> None:
    if not enabled:
        return
    text = str(value or "").strip().lower()
    if not text.startswith("cuda"):
        errors.append(f"{name} must be cuda/cuda:0 when CUDA is required, got {value!r}")


def _require_cuda_provider_chain(name: str, value: Any, errors: list[str]) -> None:
    providers = [part.strip() for part in str(value or "").split(",") if part.strip()]
    if not providers:
        errors.append(f"{name} must include CUDAExecutionProvider first when CUDA is required")
        return
    if providers[0] != "CUDAExecutionProvider":
        errors.append(f"{name} must start with CUDAExecutionProvider, got {providers}")


def _inspect_ollama_cuda_model(*, endpoint_url: str, model_name: str) -> dict[str, Any]:
    try:
        api_ps_url = _ollama_api_url(endpoint_url, "/api/ps")
        with urlopen(api_ps_url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return {"error": "unexpected /api/ps response"}

    for model in models:
        if not isinstance(model, dict):
            continue
        name = str(model.get("name") or model.get("model") or "")
        if name != model_name:
            continue
        details = model.get("details") if isinstance(model.get("details"), dict) else {}
        processor = str(model.get("processor") or details.get("processor") or "")
        size = model.get("size")
        size_vram = model.get("size_vram")
        fully_in_vram = isinstance(size, int) and isinstance(size_vram, int) and size > 0 and size_vram >= size
        return {
            "model_loaded": True,
            "processor": processor,
            "size": size,
            "size_vram": size_vram,
            "processor_is_gpu": processor.strip().upper() == "100% GPU" or fully_in_vram,
        }
    return {"model_loaded": False}


def _ollama_api_url(endpoint_url: str, api_path: str) -> str:
    parsed = urlsplit(endpoint_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid Ollama endpoint URL: {endpoint_url!r}")
    return urlunsplit((parsed.scheme, parsed.netloc, api_path, "", ""))
