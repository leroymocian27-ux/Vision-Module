from __future__ import annotations

import queue
import threading
import time
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import RealtimeResultStore
from app.events.pipeline import EventPipelineService
from app.events.schemas import FallEventRecord
from app.post_fall_v2.binary_decision_aggregator import (
    BinaryDecisionAggregator,
    BinaryDecisionAggregatorConfig,
)
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.frame_sampler_service import FrameSamplerService
from app.post_fall_v2.follow_target import (
    FollowTargetReceiver,
    TargetRegionConfig,
    TargetRegionExtractor,
)
from app.post_fall_v2.evidence_exporter import PostFallEvidenceExporter
from app.post_fall_v2.keyframe_collection_session import KeyframeCollectionSession
from app.post_fall_v2.keyframe_package_service import KeyframePackageService
from app.post_fall_v2.model_log_bus import model_log_bus
from app.post_fall_v2.rolling_event_buffer import RollingEventBuffer
from app.post_fall_v2.safety_decision import evaluate_fall_safety
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.post_fall_v2.schemas import (
    FULL_FRAME_TRAIN_MATCHED,
    POST_FALL_V2_INPUT_MODE_AUTO,
    POST_FALL_V2_INPUT_MODE_FOLLOW_TARGET_ROI,
    POST_FALL_V2_INPUT_MODE_FULL_FRAME,
    BinaryAggregateDecision,
    BinaryFrameResult,
    FallDetailResult,
    FallEvent,
    FallSafetyDecision,
    KeyframePackage,
    SampledFrame,
    utc_now_iso,
)
from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.vlm_review_service import FUSION_VERSION, VLMReviewService, build_competition_decision
from app.schemas.vision_result import DetectedObject, VisionResult
from app.services.fall_event_reporter_service import FallEventReporterService
from app.streaming.result_channel_manager import ResultChannelManager

logger = get_logger(__name__)


@dataclass
class _RuntimeState:
    sampler_thread: threading.Thread
    worker_thread: threading.Thread
    stop_event: threading.Event
    queue: queue.Queue[SampledFrame]
    sampler: FrameSamplerService
    frames_sampled: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frames_invalid: int = 0
    target_unavailable_skips: int = 0
    last_probability: float | None = None
    last_label: str | None = None
    last_inference_at: str | None = None
    last_frame_age_ms: float | None = None
    last_queue_delay_ms: float | None = None
    last_preprocess_ms: float | None = None
    last_inference_ms: float | None = None
    inference_latency_avg_ms: float | None = None
    inference_latency_p95_ms: float | None = None
    inference_latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    target_roi_latency_p95_ms: float | None = None
    target_roi_latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=120))
    last_target_binding: dict | None = None
    last_binary_input_source: str | None = None
    last_total_ms: float | None = None
    last_error: str | None = None
    last_log_monotonic: float = 0.0
    last_target_log_monotonic: float = 0.0


class PostFallV2RuntimeService:
    """Formal Binary-First runtime chain for PIPELINE_MODE=post_fall_v2."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_manager: CameraSourceManager,
        realtime_store: RealtimeResultStore,
        result_channels: ResultChannelManager,
        event_pipeline: EventPipelineService | None = None,
        vlm_review_service: VLMReviewService | None = None,
        evidence_exporter: PostFallEvidenceExporter | None = None,
        test_archive_service: PostFallTestArchiveService | None = None,
        fall_event_reporter: FallEventReporterService | None = None,
        classifier: FallBinaryClassifierService | None = None,
        follow_target_receiver: FollowTargetReceiver | None = None,
        manual_control_enabled: bool = False,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.realtime_store = realtime_store
        self.result_channels = result_channels
        self.event_pipeline = event_pipeline
        self.enabled = bool(settings.post_fall_v2_enabled)
        self._classifier = classifier
        self._classifier_error: str | None = None
        self._input_mode = settings.post_fall_v2_input_mode
        self._follow_target_required_for_binary = self._input_mode == POST_FALL_V2_INPUT_MODE_FOLLOW_TARGET_ROI
        self._aggregator = BinaryDecisionAggregator(
            BinaryDecisionAggregatorConfig(
                threshold=settings.post_fall_v2_binary_threshold,
                window_size=settings.post_fall_v2_window_size,
                min_positive_frames=settings.post_fall_v2_min_positive_frames,
                min_consecutive_frames=settings.post_fall_v2_min_consecutive_frames,
                candidate_min_ms=settings.post_fall_v2_candidate_min_ms,
                recovery_min_ms=settings.post_fall_v2_recovery_min_ms,
                cooldown_ms=settings.post_fall_v2_cooldown_ms,
            )
        )
        self._event_buffer = RollingEventBuffer(
            window_seconds=settings.post_fall_v2_event_buffer_seconds,
            max_frames_per_camera=max(16, int(settings.post_fall_v2_event_buffer_seconds * settings.post_fall_v2_sample_fps * 2)),
        )
        self._keyframes = KeyframePackageService(
            offsets_ms=settings.event_keyframe_offsets_ms,
            tolerance_ms=settings.post_fall_v2_keyframe_tolerance_ms,
        )
        self._vlm = vlm_review_service or VLMReviewService(
            enabled=settings.post_fall_v2_vlm_enabled,
            timeout_seconds=settings.post_fall_v2_vlm_timeout_seconds,
        )
        self._evidence_exporter = evidence_exporter
        self._test_archive = test_archive_service
        self._fall_event_reporter = fall_event_reporter
        self._follow_target_receiver = follow_target_receiver
        self._target_regions = TargetRegionExtractor(
            TargetRegionConfig(
                enabled=settings.follow_target_enabled,
                fresh_ms=settings.follow_target_fresh_ms,
                grace_ms=settings.follow_target_grace_ms,
                camera_hfov_deg=settings.follow_target_camera_hfov_deg,
                camera_yaw_offset_deg=settings.follow_target_camera_yaw_offset_deg,
                fresh_width_ratio=settings.follow_target_roi_width_ratio,
                grace_width_ratio=settings.follow_target_grace_roi_width_ratio,
            )
        )
        self.manual_control_enabled = bool(manual_control_enabled)
        self.binary_control_enabled = not self.manual_control_enabled
        self.qwen_control_enabled = bool(self._vlm.enabled) and not self.manual_control_enabled
        if self.manual_control_enabled:
            self._vlm.enabled = False
        self._states: dict[str, _RuntimeState] = {}
        self._events: dict[str, FallEvent] = {}
        self._vlm_threads: dict[str, threading.Thread] = {}
        self._keyframe_sessions: dict[str, KeyframeCollectionSession] = {}
        self._keyframe_threads: dict[str, threading.Thread] = {}
        self._keyframe_stops: dict[str, threading.Event] = {}
        self._keyframe_statuses: dict[str, dict] = {}
        self._qwen_media: dict[str, tuple[list[QwenImageInput], list[str]]] = {}
        self._vlm_submitted: set[str] = set()
        self._vlm_finished: set[str] = set()
        self._alerted_incidents: set[str] = set()
        self._lock = threading.Lock()
        self._classifier_load_lock = threading.Lock()
        self._classifier_loading = False
        if self.enabled:
            logger.info(
                "post_fall_v2_input_mode=%s follow_target_required_for_binary=%s",
                self._input_mode,
                self._follow_target_required_for_binary,
            )
            model_log_bus.publish(
                "binary",
                "binary_input_mode",
                input_mode=self._input_mode,
                follow_target_required_for_binary=self._follow_target_required_for_binary,
            )
        if self.enabled and self.settings.post_fall_v2_binary_preload:
            self._preload_classifier_async()

    def start_for_camera(self, camera_id: str) -> None:
        if not self.enabled:
            return
        if self.manual_control_enabled and not self.binary_control_enabled:
            return
        if self._classifier is None:
            self._load_classifier_safely()
        if self._classifier is None:
            return
        with self._lock:
            existing = self._states.get(camera_id)
            if existing and existing.worker_thread.is_alive():
                return
            stop_event = threading.Event()
            frame_queue: queue.Queue[SampledFrame] = queue.Queue(maxsize=max(1, self.settings.post_fall_v2_queue_size))
            sampler = FrameSamplerService(
                sample_fps=self.settings.post_fall_v2_sample_fps,
                max_frame_age_ms=self.settings.post_fall_v2_max_frame_age_ms,
            )
            state = _RuntimeState(
                sampler_thread=threading.Thread(
                    target=self._sample_loop,
                    args=(camera_id, stop_event, frame_queue, sampler),
                    name=f"post-fall-v2-runtime-sampler-{camera_id}",
                    daemon=True,
                ),
                worker_thread=threading.Thread(
                    target=self._worker_loop,
                    args=(camera_id, stop_event, frame_queue),
                    name=f"post-fall-v2-runtime-worker-{camera_id}",
                    daemon=True,
                ),
                stop_event=stop_event,
                queue=frame_queue,
                sampler=sampler,
            )
            self._states[camera_id] = state
            state.sampler_thread.start()
            state.worker_thread.start()
        logger.info("post_fall_v2_runtime_started camera_id=%s", camera_id)
        model_log_bus.publish(
            "binary",
            "binary_runtime_started",
            camera_id=camera_id,
            sample_fps=self.settings.post_fall_v2_sample_fps,
            queue_size=self.settings.post_fall_v2_queue_size,
            input_mode=self._input_mode,
            follow_target_required_for_binary=self._follow_target_required_for_binary,
        )

    def set_binary_enabled(self, camera_id: str, enabled: bool) -> dict:
        if not self.enabled:
            raise ValueError("Post-Fall V2 runtime is disabled by configuration")
        if enabled:
            if self.source_manager.get_runtime(camera_id) is None:
                raise ValueError("please connect video stream before enabling binary model")
            self.binary_control_enabled = True
            if self._classifier is None:
                self._load_classifier_safely()
            if self._classifier is None:
                raise ValueError(self._classifier_error or "binary classifier unavailable")
            self.start_for_camera(camera_id)
            logger.info("post_fall_v2_binary_enabled camera_id=%s", camera_id)
            model_log_bus.publish(
                "binary",
                "binary_enabled",
                camera_id=camera_id,
                provider=getattr(self._classifier, "provider", None),
                active_providers=getattr(self._classifier, "active_providers", None),
                sample_fps=self.settings.post_fall_v2_sample_fps,
            )
        else:
            self.binary_control_enabled = False
            self.qwen_control_enabled = False
            self._vlm.enabled = False
            self.stop_for_camera(camera_id)
            logger.info("post_fall_v2_binary_disabled camera_id=%s", camera_id)
            model_log_bus.publish("binary", "binary_disabled", camera_id=camera_id)
            model_log_bus.publish("qwen", "qwen_disabled", camera_id=camera_id, reason="binary_disabled")
        return self.control_status(camera_id)

    def set_qwen_enabled(self, camera_id: str, enabled: bool) -> dict:
        if enabled:
            if not self.binary_control_enabled:
                raise ValueError("please enable binary model before enabling Qwen review")
            state = self._states.get(camera_id)
            if state is None or not state.worker_thread.is_alive():
                raise ValueError("binary model is not running for this camera")
            self.qwen_control_enabled = True
            self._vlm.enabled = True
            logger.info("post_fall_v2_qwen_enabled camera_id=%s", camera_id)
            model_log_bus.publish(
                "qwen",
                "qwen_enabled",
                camera_id=camera_id,
                provider=getattr(self.settings, "post_fall_v2_qwen_provider", "dummy"),
                model=getattr(self.settings, "post_fall_v2_qwen_model", None),
                queue_capacity=getattr(self._vlm, "_queue_capacity", None),
            )
        else:
            self.qwen_control_enabled = False
            self._vlm.enabled = False
            logger.info("post_fall_v2_qwen_disabled camera_id=%s", camera_id)
            model_log_bus.publish("qwen", "qwen_disabled", camera_id=camera_id)
        return self.control_status(camera_id)

    def stream_ready_for_processing(self, camera_id: str) -> bool:
        runtime = self.source_manager.get_runtime(camera_id)
        if runtime is None:
            return False
        worker_status = self.source_manager.worker_status(camera_id)
        if worker_status is not None and getattr(worker_status, "connected", False):
            return True
        packet = runtime.frame_buffer.latest()
        if packet is None:
            return False
        max_age_ms = max(
            float(self.settings.post_fall_v2_max_frame_age_ms),
            float(self.settings.stream_stale_threshold_ms),
        )
        return packet.age_ms <= max_age_ms

    def control_status(self, camera_id: str | None = None) -> dict:
        stream_connected = self.stream_ready_for_processing(camera_id) if camera_id else False
        runtime_status = self.status(camera_id)
        test_status = self._test_archive.status() if self._test_archive is not None else None
        test_payload = test_status.__dict__ if test_status is not None else None
        return {
            "camera_id": camera_id,
            "server_ready": True,
            "stream_connected": stream_connected,
            "binary_enabled": bool(self.binary_control_enabled and runtime_status.get("running")),
            "binary_requested": bool(self.binary_control_enabled),
            "qwen_enabled": bool(self.qwen_control_enabled and self._vlm.enabled),
            "qwen_requested": bool(self.qwen_control_enabled),
            "manual_control_enabled": self.manual_control_enabled,
            "runtime": runtime_status,
            "test": test_payload,
            "performance": self._performance_status(camera_id, runtime_status, test_payload),
        }

    def _performance_status(
        self,
        camera_id: str | None,
        runtime_status: dict,
        test_status: dict | None,
    ) -> dict:
        sample = (test_status or {}).get("latest_performance") or {}
        worker_status = self.source_manager.worker_status(camera_id) if camera_id else None
        capture_fps = getattr(worker_status, "fps", None) if worker_status is not None else None
        frame_age_ms = getattr(worker_status, "frame_age_ms", None) if worker_status is not None else None
        return {
            "capture_fps": capture_fps,
            "display_fps": capture_fps,
            "sample_fps": runtime_status.get("binary_sample_fps") or runtime_status.get("sample_fps"),
            "inference_fps": runtime_status.get("binary_sample_fps") if runtime_status.get("running") else 0,
            "frame_age_ms": frame_age_ms,
            "ai_frame_age_ms": runtime_status.get("frame_age_ms"),
            "ai_queue_depth": runtime_status.get("queue_depth", 0),
            "frames_dropped": runtime_status.get("frames_dropped", 0),
            "frames_sampled": runtime_status.get("frames_sampled", 0),
            "frames_processed": runtime_status.get("frames_processed", 0),
            "binary_inference_ms_last": runtime_status.get("binary_inference_latency_ms"),
            "binary_inference_ms_avg": runtime_status.get("binary_inference_latency_avg_ms"),
            "binary_inference_ms_p95": runtime_status.get("binary_inference_latency_p95_ms"),
            "system_cpu_percent": sample.get("cpu_percent"),
            "system_ram_percent": sample.get("memory_percent"),
            "system_ram_used_mb": sample.get("memory_used_mb"),
            "process_cpu_percent": sample.get("process_cpu_percent"),
            "process_rss_mb": sample.get("process_rss_mb"),
            "gpu_util_percent": sample.get("gpu_util_percent"),
            "gpu_memory_used_mb": sample.get("gpu_memory_used_mb"),
            "gpu_memory_total_mb": sample.get("gpu_memory_total_mb"),
            "gpu_memory_percent": sample.get("gpu_memory_percent"),
            "onnx_provider": runtime_status.get("binary_provider"),
            "onnx_fallback": bool(runtime_status.get("binary_provider_degraded")),
            "qwen": {
                "armed": bool(self.qwen_control_enabled and self._vlm.enabled),
                "busy": bool(runtime_status.get("vlm_active_count", 0)),
                "requests": runtime_status.get("vlm_submitted_count", 0),
                "finished": runtime_status.get("vlm_finished_count", 0),
                "queue_depth": runtime_status.get("vlm_queue_depth", 0),
                "rejected": runtime_status.get("vlm_rejected_count", 0),
            },
        }

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            state = self._states.pop(camera_id, None)
        if state is None:
            return
        state.stop_event.set()
        self._cancel_keyframe_sessions(camera_id)
        for worker in (state.sampler_thread, state.worker_thread):
            if worker.is_alive():
                worker.join(timeout=3)
        self._event_buffer.clear(camera_id)
        self._aggregator.reset(camera_id)
        logger.info("post_fall_v2_runtime_stopped camera_id=%s", camera_id)
        model_log_bus.publish("binary", "binary_runtime_stopped", camera_id=camera_id)

    def stop_all(self) -> None:
        for camera_id in list(self._states.keys()):
            self.stop_for_camera(camera_id)
        for stop_event in list(self._keyframe_stops.values()):
            stop_event.set()
        for session in list(self._keyframe_sessions.values()):
            session.cancel()
        for thread in list(self._keyframe_threads.values()):
            if thread.is_alive():
                thread.join(timeout=1)
        for thread in list(self._vlm_threads.values()):
            if thread.is_alive():
                thread.join(timeout=1)
        self._vlm.shutdown()

    def status(self, camera_id: str | None = None) -> dict:
        with self._lock:
            selected = self._states.get(camera_id) if camera_id else next(iter(self._states.values()), None)
            selected_camera_id = camera_id or (next(iter(self._states.keys()), None) if self._states else None)
            active_vlm = sum(1 for thread in self._vlm_threads.values() if thread.is_alive())
            camera_events = [
                event
                for event in self._events.values()
                if selected_camera_id is None or event.camera_id == selected_camera_id
            ]
            event_count = len(camera_events)
            active_collectors = sum(1 for thread in self._keyframe_threads.values() if thread.is_alive())
            latest_incident_id = camera_events[-1].incident_id if camera_events else None
            keyframe_status = self._keyframe_statuses.get(latest_incident_id or "", {})
            last_target_binding = dict(selected.last_target_binding) if selected and selected.last_target_binding else None
            target_unavailable_skips = selected.target_unavailable_skips if selected else 0
            target_roi_latency_p95_ms = selected.target_roi_latency_p95_ms if selected else None
        running = bool(selected and selected.worker_thread.is_alive() and selected.sampler_thread.is_alive())
        follow_status = self._follow_target_status(last_target_binding)
        return {
            "camera_id": selected_camera_id,
            "pipeline_mode": self.settings.pipeline_mode,
            "post_fall_v2_input_mode": self._input_mode,
            "binary_input_source": selected.last_binary_input_source if selected else None,
            "follow_target_required_for_binary": self._follow_target_required_for_binary,
            "enabled": self.enabled,
            "running": running,
            "state": self._aggregator.status(selected_camera_id) if selected_camera_id else "idle",
            "active_incident_id": latest_incident_id,
            "binary_model_loaded": bool(self._classifier and self._classifier.loaded),
            "binary_model_loading": self._classifier_loading,
            "binary_model_load_timings_ms": getattr(self._classifier, "load_timings_ms", None) if self._classifier else None,
            "binary_model_sha256": self._classifier.model_sha256 if self._classifier else None,
            "binary_provider": self._classifier.provider if self._classifier else None,
            "binary_requested_providers": getattr(self._classifier, "requested_providers", None) if self._classifier else None,
            "binary_available_providers": getattr(self._classifier, "available_providers", None) if self._classifier else None,
            "binary_active_providers": getattr(self._classifier, "active_providers", None) if self._classifier else None,
            "binary_provider_degraded": bool(getattr(self._classifier, "provider_degraded", False)) if self._classifier else False,
            "binary_provider_warning": getattr(self._classifier, "provider_warning", None) if self._classifier else None,
            "binary_last_inference_at": selected.last_inference_at if selected else None,
            "binary_last_probability": selected.last_probability if selected else None,
            "binary_last_label": selected.last_label if selected else None,
            "binary_sample_fps": self.settings.post_fall_v2_sample_fps,
            "binary_inference_latency_ms": selected.last_inference_ms if selected else None,
            "binary_inference_latency_avg_ms": selected.inference_latency_avg_ms if selected else None,
            "binary_inference_latency_p95_ms": selected.inference_latency_p95_ms if selected else None,
            "binary_preprocess_ms": selected.last_preprocess_ms if selected else None,
            "binary_total_ms": selected.last_total_ms if selected else None,
            "binary_queue_delay_ms": selected.last_queue_delay_ms if selected else None,
            "frame_age_ms": selected.last_frame_age_ms if selected else None,
            "sample_fps": self.settings.post_fall_v2_sample_fps,
            "queue_depth": selected.queue.qsize() if selected else 0,
            "frames_sampled": selected.frames_sampled if selected else 0,
            "frames_processed": selected.frames_processed if selected else 0,
            "frames_dropped": selected.frames_dropped if selected else 0,
            "frames_invalid": selected.frames_invalid if selected else 0,
            "target_unavailable_skips": target_unavailable_skips,
            "target_roi_latency_p95_ms": target_roi_latency_p95_ms,
            "follow_target_receiver_running": follow_status["receiver_running"],
            "follow_target_valid": follow_status["valid"],
            "follow_target_state": follow_status["state"],
            "follow_target_age_ms": follow_status["age_ms"],
            "follow_target_bearing_deg": follow_status["bearing_deg"],
            "follow_target_distance_m": follow_status["distance_m"],
            "follow_target_sequence": follow_status["sequence"],
            "follow_target_roi": follow_status["roi"],
            "follow_target_packet_count": follow_status["packet_count"],
            "follow_target_invalid_count": follow_status["invalid_count"],
            "follow_target_out_of_order_count": follow_status["out_of_order_count"],
            "vlm_enabled": self._vlm.enabled,
            "vlm_provider": getattr(self.settings, "post_fall_v2_qwen_provider", "dummy"),
            "vlm_model": getattr(self.settings, "post_fall_v2_qwen_model", None),
            "vlm_active_count": active_vlm,
            "vlm_call_count": self._vlm.call_count,
            "vlm_queue_depth": self._vlm.queue_depth,
            "vlm_queue_capacity": getattr(self._vlm, "_queue_capacity", None),
            "vlm_rejected_count": self._vlm.rejected_count,
            "vlm_submitted_count": len(self._vlm_submitted),
            "vlm_finished_count": len(self._vlm_finished),
            "keyframe_collection_active_count": active_collectors,
            "keyframe_collection_status": keyframe_status,
            "event_count": event_count,
            "last_error": self._classifier_error or (selected.last_error if selected else None),
        }

    def latest_event(self, incident_id: str) -> FallEvent | None:
        with self._lock:
            return self._events.get(incident_id)

    def events(self) -> list[FallEvent]:
        with self._lock:
            return list(self._events.values())

    def qwen_images_for_incident(self, incident_id: str) -> tuple[list[QwenImageInput], list[str]]:
        with self._lock:
            images, missing = self._qwen_media.get(incident_id, ([], ["qwen_media_not_available"]))
        return list(images), list(missing)

    def _apply_target_region(self, camera_id: str, sampled: SampledFrame) -> SampledFrame:
        target_state = self._follow_target_receiver.latest() if self._follow_target_receiver is not None else None
        result = self._target_regions.extract(sampled.frame, target_state)
        input_mode = self._input_mode
        input_source = POST_FALL_V2_INPUT_MODE_FULL_FRAME
        frame = sampled.frame
        if input_mode == POST_FALL_V2_INPUT_MODE_FOLLOW_TARGET_ROI:
            if result.tracking_state in {"fresh", "grace"} and result.frame is not None:
                input_source = "follow_target_roi"
                frame = result.frame
            else:
                input_source = "unavailable"
        elif input_mode == POST_FALL_V2_INPUT_MODE_AUTO:
            if result.tracking_state in {"fresh", "grace"} and result.frame is not None:
                input_source = "follow_target_roi"
                frame = result.frame
            else:
                input_source = "full_frame_fallback"
        height, width = frame.shape[:2]
        target_binding = {
            **result.target_binding,
            "post_fall_v2_input_mode": input_mode,
            "binary_input_source": input_source,
            "follow_target_required_for_binary": self._follow_target_required_for_binary,
        }
        updated = replace(
            sampled,
            frame=frame,
            source_width=width,
            source_height=height,
            target_binding=target_binding,
        )
        self._record_target_binding(camera_id, target_binding, result.processing_ms)
        if self.settings.follow_target_calibration_log_enabled:
            self._log_target_region(camera_id, target_binding)
        return updated

    def _record_target_binding(self, camera_id: str, target_binding: dict, processing_ms: float) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return
            state.last_target_binding = target_binding
            state.target_roi_latencies_ms.append(float(processing_ms))
            state.target_roi_latency_p95_ms = _percentile(list(state.target_roi_latencies_ms), 0.95)

    def _log_target_region(self, camera_id: str, target_binding: dict) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._states.get(camera_id)
            if state is None or now - state.last_target_log_monotonic < 1.0:
                return
            state.last_target_log_monotonic = now
        model_log_bus.publish(
            "binary",
            "follow_target_roi",
            camera_id=camera_id,
            target_tracking_state=target_binding.get("target_tracking_state"),
            bearing_deg=target_binding.get("bearing_deg"),
            distance_m=target_binding.get("distance_m"),
            target_age_ms=target_binding.get("target_age_ms"),
            sequence=target_binding.get("sequence"),
            roi=target_binding.get("roi"),
            processing_ms=target_binding.get("processing_ms"),
            reason=target_binding.get("reason"),
        )

    def _target_unavailable_binary(self, sampled: SampledFrame) -> BinaryFrameResult:
        binding = sampled.target_binding or {}
        return BinaryFrameResult(
            frame_id=sampled.frame_id,
            camera_id=sampled.camera_id,
            frame_seq=sampled.frame_seq,
            captured_at=sampled.captured_at,
            inferred_at=utc_now_iso(),
            fall_probability=None,
            non_fall_probability=None,
            raw_label=None,
            decision_label="UNKNOWN",
            threshold=self.settings.post_fall_v2_binary_threshold,
            model_name=getattr(self._classifier, "model_name", "efficientnet_b0_post_fall") if self._classifier else "efficientnet_b0_post_fall",
            model_version=(self._classifier.model_sha256 or "")[:12] if self._classifier else "",
            valid=False,
            source_width=sampled.source_width,
            source_height=sampled.source_height,
            target_binding=sampled.target_binding,
            error_code="FOLLOW_TARGET_UNAVAILABLE",
            error_message=str(binding.get("reason") or binding.get("target_tracking_state") or "follow target unavailable"),
        )

    def _follow_target_status(self, last_target_binding: dict | None) -> dict:
        receiver_status = (
            self._follow_target_receiver.status()
            if self._follow_target_receiver is not None
            else {
                "enabled": False,
                "running": False,
                "packet_count": 0,
                "invalid_count": 0,
                "out_of_order_count": 0,
                "latest_state": None,
            }
        )
        latest_state = self._follow_target_receiver.latest() if self._follow_target_receiver is not None else None
        derived = self._target_regions.status_from_state(latest_state)
        binding = last_target_binding or {}
        state = binding.get("target_tracking_state") or derived.get("tracking_state")
        age_ms = binding.get("target_age_ms")
        if age_ms is None:
            age_ms = derived.get("age_ms")
        return {
            "receiver_running": bool(receiver_status.get("running")),
            "valid": bool(
                self.settings.follow_target_enabled
                and state in {"fresh", "grace"}
                and (binding.get("target_valid", derived.get("valid")) is True or derived.get("valid") is True)
            ),
            "state": state,
            "age_ms": age_ms,
            "bearing_deg": binding.get("bearing_deg", derived.get("bearing_deg")),
            "distance_m": binding.get("distance_m", derived.get("distance_m")),
            "sequence": binding.get("sequence", derived.get("sequence")),
            "roi": binding.get("roi"),
            "packet_count": receiver_status.get("packet_count", 0),
            "invalid_count": receiver_status.get("invalid_count", 0),
            "out_of_order_count": receiver_status.get("out_of_order_count", 0),
        }

    def _sample_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
        sampler: FrameSamplerService,
    ) -> None:
        tick_interval = min(0.05, 1.0 / max(self.settings.post_fall_v2_sample_fps * 4, 1.0))
        while not stop_event.is_set():
            try:
                buffer = self.source_manager.get_buffer(camera_id)
                decision = sampler.try_sample(buffer.latest() if buffer else None)
                if decision.sampled is not None:
                    sampled = self._apply_target_region(camera_id, decision.sampled)
                    target_state = (sampled.target_binding or {}).get("target_tracking_state")
                    input_source = (sampled.target_binding or {}).get("binary_input_source")
                    if (
                        self._input_mode in {POST_FALL_V2_INPUT_MODE_FULL_FRAME, POST_FALL_V2_INPUT_MODE_AUTO}
                        or input_source == "follow_target_roi"
                        or not self.settings.follow_target_enabled
                        or target_state in {"fresh", "grace"}
                    ):
                        buffered = self._event_buffer.add_sampled_frame(sampled)
                        self._observe_keyframe_sessions(buffered)
                    self._put_latest(camera_id, frame_queue, sampled)
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_runtime_sampler_error camera_id=%s", camera_id)
            stop_event.wait(tick_interval)

    def _worker_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
    ) -> None:
        while not stop_event.is_set():
            try:
                sampled = frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                classifier = self._classifier
                if classifier is None:
                    self._set_error(camera_id, "classifier unavailable")
                    continue
                input_source = (sampled.target_binding or {}).get("binary_input_source")
                if (
                    self._input_mode == POST_FALL_V2_INPUT_MODE_FOLLOW_TARGET_ROI
                    and input_source != "follow_target_roi"
                ):
                    self._aggregator.reset(camera_id)
                    binary = self._target_unavailable_binary(sampled)
                    aggregate = self._aggregator.update(binary)
                    aggregate = replace(aggregate, reason="follow_target_unavailable")
                    self._update_state(camera_id, binary, None, sampled)
                    with self._lock:
                        state = self._states.get(camera_id)
                        if state is not None:
                            state.target_unavailable_skips += 1
                    if self._test_archive is not None:
                        self._test_archive.archive_binary_frame(binary, aggregate, None, sampled)
                    self._publish(binary, aggregate, None)
                    continue
                binary_started_at = utc_now_iso()
                raw_result = classifier.infer(sampled)
                binary_finished_at = utc_now_iso()
                raw = SimpleNamespace(
                    model=getattr(raw_result, "model", None),
                    performance=getattr(raw_result, "performance", None),
                    timing=SimpleNamespace(
                        started_at=binary_started_at,
                        finished_at=binary_finished_at,
                    ),
                    result=raw_result,
                )
                binary = BinaryFrameResult.from_classifier_result(raw_result)
                binary = BinaryFrameResult(**{**binary.to_record(), "frame_seq": sampled.frame_seq, "target_binding": sampled.target_binding})
                aggregate = self._aggregator.update(binary)
                self._update_state(camera_id, binary, raw, sampled)
                self._log_binary_progress(camera_id, binary, aggregate)
                event = self._maybe_create_event(aggregate, sampled, raw)
                if self._test_archive is not None:
                    self._test_archive.archive_binary_frame(binary, aggregate, raw, sampled)
                self._publish(binary, aggregate, event)
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_runtime_worker_error camera_id=%s", camera_id)
                model_log_bus.publish("binary", "binary_worker_error", level="error", camera_id=camera_id, error=str(exc))

    def _maybe_create_event(
        self,
        decision: BinaryAggregateDecision,
        sampled: SampledFrame,
        raw: object | None = None,
    ) -> FallEvent | None:
        if not decision.event_created or not decision.incident_id:
            return None
        session = self._new_keyframe_session(decision, sampled)
        session.prime_buffer(self._event_buffer.window(decision.camera_id))
        keyframes = replace(
            session.build_package(now_monotonic=sampled.captured_monotonic),
            fall_probability_summary=decision.evidence.to_record(),
            target_binding=sampled.target_binding,
        )
        collect_keyframes = self._vlm.enabled and self.settings.post_fall_v2_keyframe_post_collection_enabled
        binary_evidence = {
            **decision.evidence.to_record(),
            "frame_id": decision.frame_id,
            "frame_seq": decision.frame_seq,
            "fall_probability": decision.fall_probability,
            "target_binding": sampled.target_binding,
            "capture_timestamp": sampled.captured_at,
            "binary_sample_timestamp": sampled.sampled_at,
            "captured_at": sampled.captured_at,
            "sampled_at": sampled.sampled_at,
            "captured_monotonic": sampled.captured_monotonic,
            "sampled_monotonic": sampled.sampled_monotonic,
            "candidate_created_timestamp": decision.updated_at,
            "candidate_latency_ms": round((time.monotonic() - sampled.captured_monotonic) * 1000, 3),
            "prompt_version": "compact_v2",
            "schema_version": "compact_v1",
            "fusion_version": FUSION_VERSION,
        }
        performance = getattr(raw, "performance", None)
        if performance is not None:
            binary_evidence["preprocess_ms"] = getattr(performance, "preprocess_ms", None)
            binary_evidence["onnx_inference_ms"] = getattr(performance, "inference_ms", None)
            binary_evidence["binary_queue_delay_ms"] = getattr(performance, "queue_delay_ms", None)
            binary_evidence["binary_total_ms"] = getattr(performance, "total_ms", None)
        timing = getattr(raw, "timing", None)
        if timing is not None:
            binary_evidence["binary_started_at"] = getattr(timing, "started_at", None)
            binary_evidence["binary_finished_at"] = getattr(timing, "finished_at", None)
        event = FallEvent(
            incident_id=decision.incident_id,
            camera_id=decision.camera_id,
            state="fall_candidate",
            started_at=decision.updated_at,
            confirmed_at=decision.updated_at,
            binary_evidence=binary_evidence,
            keyframes=keyframes,
            vlm_status="collecting_keyframes" if collect_keyframes else ("pending" if self._vlm.enabled else "disabled"),
            target_binding=sampled.target_binding,
        )
        with self._lock:
            self._events[event.incident_id] = event
            self._keyframe_statuses[event.incident_id] = {
                "status": keyframes.status if not collect_keyframes else "collecting",
                "requested_offsets_ms": keyframes.requested_offsets_ms,
                "resolved_offsets_ms": keyframes.resolved_offsets_ms,
                "missing_offsets_ms": keyframes.missing_offsets_ms,
            }
        if self._test_archive is not None:
            try:
                missing = ["collecting_future_keyframes"] if collect_keyframes else []
                self._test_archive.archive_binary_event(event, keyframes, [], missing)
            except Exception:
                logger.exception("post_fall_v2_test_binary_archive_stub_failed incident_id=%s", event.incident_id)
        if collect_keyframes:
            self._schedule_keyframe_collection(event, session)
        else:
            # The fast path still needs to encode the frames selected from the
            # rolling buffer before the VLM worker is started. Without this,
            # the metadata package exists but the Qwen media provider is empty.
            images: list[QwenImageInput] = []
            missing: list[str] = []
            if self._vlm.enabled or self._evidence_exporter is not None or self._test_archive is not None:
                images, missing = session.export_qwen_images(
                    max_images=self.settings.post_fall_v2_qwen_max_images,
                    max_image_bytes=self.settings.post_fall_v2_qwen_max_image_bytes,
                    max_edge=self.settings.post_fall_v2_qwen_image_max_edge,
                    jpeg_quality=self.settings.post_fall_v2_qwen_jpeg_quality,
                    now_monotonic=sampled.captured_monotonic,
                )
                export_timing = session.last_export_timing
                if export_timing:
                    binary_evidence = {**binary_evidence, **export_timing}
                    event = replace(event, binary_evidence=binary_evidence)
                    keyframes = replace(keyframes, fall_probability_summary=binary_evidence)
                    with self._lock:
                        self._events[event.incident_id] = event
            if self._evidence_exporter is not None:
                try:
                    self._evidence_exporter.export_binary(event, keyframes, images)
                except Exception:
                    logger.exception("post_fall_v2_binary_evidence_export_failed incident_id=%s", event.incident_id)
            if self._test_archive is not None:
                try:
                    self._test_archive.archive_binary_event(event, keyframes, images, missing)
                except Exception:
                    logger.exception("post_fall_v2_test_binary_archive_failed incident_id=%s", event.incident_id)
            if self._vlm.enabled:
                with self._lock:
                    self._qwen_media[event.incident_id] = (images, missing)
            session.release_media()
            self._schedule_vlm(event, keyframes)
        logger.info("fall_event_created incident_id=%s camera_id=%s", event.incident_id, event.camera_id)
        model_log_bus.publish(
            "binary",
            "fall_event_created",
            camera_id=event.camera_id,
            incident_id=event.incident_id,
            fall_state=decision.fall_state,
            reason=decision.reason,
            max_fall_probability=decision.evidence.max_fall_probability,
            qwen_enabled=self._vlm.enabled,
        )
        return event

    def _new_keyframe_session(self, decision: BinaryAggregateDecision, sampled: SampledFrame) -> KeyframeCollectionSession:
        return KeyframeCollectionSession(
            incident_id=decision.incident_id or "",
            camera_id=decision.camera_id,
            confirmed_monotonic=sampled.captured_monotonic,
            confirmed_at=decision.updated_at,
            required_offsets_ms=self.settings.event_keyframe_offsets_ms,
            tolerance_ms=self.settings.post_fall_v2_keyframe_tolerance_ms,
            collection_window_seconds=self.settings.post_fall_v2_keyframe_collection_timeout_seconds,
            max_observations=max(16, int(self.settings.post_fall_v2_event_buffer_seconds * self.settings.post_fall_v2_sample_fps * 2)),
        )

    def _schedule_keyframe_collection(self, event: FallEvent, session: KeyframeCollectionSession) -> None:
        with self._lock:
            existing = self._keyframe_threads.get(event.incident_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_keyframe_collection,
                args=(event.incident_id, stop_event),
                name=f"post-fall-v2-keyframes-{event.incident_id}",
                daemon=True,
            )
            self._keyframe_sessions[event.incident_id] = session
            self._keyframe_stops[event.incident_id] = stop_event
            self._keyframe_threads[event.incident_id] = thread
            thread.start()
        logger.info("keyframe_collection_started incident_id=%s", event.incident_id)
        model_log_bus.publish(
            "qwen",
            "keyframe_collection_started",
            camera_id=event.camera_id,
            incident_id=event.incident_id,
            requested_offsets_ms=session.required_offsets_ms,
        )

    def _run_keyframe_collection(self, incident_id: str, stop_event: threading.Event) -> None:
        try:
            while not stop_event.wait(0.05):
                with self._lock:
                    session = self._keyframe_sessions.get(incident_id)
                if session is None:
                    return
                snapshot = session.snapshot()
                with self._lock:
                    self._keyframe_statuses[incident_id] = snapshot.to_record()
                if snapshot.status in {"ready", "degraded", "expired", "cancelled"}:
                    break
            with self._lock:
                session = self._keyframe_sessions.get(incident_id)
            if stop_event.is_set() or (session is not None and session.status() == "cancelled"):
                with self._lock:
                    if session is not None:
                        self._keyframe_statuses[incident_id] = session.snapshot().to_record()
                    self._keyframe_sessions.pop(incident_id, None)
                return
            self._complete_keyframe_collection(incident_id)
        except Exception:
            logger.exception("keyframe_collection_failed incident_id=%s", incident_id)
            self._complete_keyframe_collection(incident_id, forced_error="keyframe_collection_failed")
        finally:
            with self._lock:
                self._keyframe_threads.pop(incident_id, None)
                self._keyframe_stops.pop(incident_id, None)

    def _complete_keyframe_collection(self, incident_id: str, forced_error: str | None = None) -> None:
        with self._lock:
            session = self._keyframe_sessions.pop(incident_id, None)
            event = self._events.get(incident_id)
        if session is None or event is None:
            return
        package = replace(
            session.build_package(),
            fall_probability_summary=event.binary_evidence,
            target_binding=event.target_binding,
        )
        images, missing = session.export_qwen_images(
            max_images=self.settings.post_fall_v2_qwen_max_images,
            max_image_bytes=self.settings.post_fall_v2_qwen_max_image_bytes,
            max_edge=self.settings.post_fall_v2_qwen_image_max_edge,
            jpeg_quality=self.settings.post_fall_v2_qwen_jpeg_quality,
        )
        export_timing = session.last_export_timing
        if export_timing:
            event = replace(event, binary_evidence={**event.binary_evidence, **export_timing})
            package = replace(package, fall_probability_summary=event.binary_evidence)
        if self._evidence_exporter is not None:
            try:
                self._evidence_exporter.export_binary(event, package, images)
            except Exception:
                logger.exception("post_fall_v2_binary_evidence_export_failed incident_id=%s", incident_id)
        if self._test_archive is not None:
            try:
                self._test_archive.archive_binary_event(event, package, images, missing)
            except Exception:
                logger.exception("post_fall_v2_test_binary_archive_failed incident_id=%s", incident_id)
        session.release_media()
        if forced_error:
            missing = list(dict.fromkeys([*missing, forced_error]))
        with self._lock:
            self._qwen_media[incident_id] = (images, missing)
            latest = self._events.get(incident_id, event)
            updated = replace(
                latest,
                keyframes=package,
                vlm_status="pending" if self._vlm.enabled else "disabled",
            )
            self._events[incident_id] = updated
            self._keyframe_statuses[incident_id] = {
                "status": package.status,
                "requested_offsets_ms": package.requested_offsets_ms,
                "resolved_offsets_ms": package.resolved_offsets_ms,
                "missing_offsets_ms": package.missing_offsets_ms,
                "missing_reasons": missing,
            }
        self._publish_vlm_update(updated)
        model_log_bus.publish(
            "qwen",
            "keyframes_ready",
            camera_id=updated.camera_id,
            incident_id=incident_id,
            status=package.status,
            image_count=len(images),
            missing_offsets_ms=package.missing_offsets_ms,
            missing_reasons=missing,
        )
        self._schedule_vlm(updated, package)

    def _observe_keyframe_sessions(self, buffered) -> None:
        with self._lock:
            sessions = list(self._keyframe_sessions.values())
        for session in sessions:
            session.observe_buffered_frame(buffered)

    def _schedule_vlm(self, event: FallEvent, keyframes: KeyframePackage) -> None:
        if not self._vlm.enabled:
            return
        with self._lock:
            if event.incident_id in self._vlm_submitted:
                return
            existing = self._vlm_threads.get(event.incident_id)
            if existing and existing.is_alive():
                return
            self._vlm_submitted.add(event.incident_id)
            thread = threading.Thread(
                target=self._run_vlm,
                args=(event.incident_id, keyframes),
                name=f"post-fall-v2-vlm-{event.incident_id}",
                daemon=True,
            )
            self._vlm_threads[event.incident_id] = thread
            self._events[event.incident_id] = replace(event, vlm_status="running")
            thread.start()
        logger.info("vlm_review_started incident_id=%s", event.incident_id)
        model_log_bus.publish(
            "qwen",
            "qwen_review_started",
            camera_id=event.camera_id,
            incident_id=event.incident_id,
            model=getattr(self.settings, "post_fall_v2_qwen_model", None),
            keyframe_status=keyframes.status,
        )

    def _run_vlm(self, incident_id: str, keyframes: KeyframePackage) -> None:
        with self._lock:
            event = self._events[incident_id]
        qwen_start_frames_received = self._worker_frame_seq(event.camera_id)
        detail = self._vlm.analyze_fall_event(event, keyframes)
        qwen_end_frames_received = self._worker_frame_seq(event.camera_id)
        frames_received_during_qwen = None
        if qwen_start_frames_received is not None and qwen_end_frames_received is not None:
            frames_received_during_qwen = max(0, qwen_end_frames_received - qwen_start_frames_received)
        fusion_started = time.perf_counter()
        _ = build_competition_decision(
            detail=detail,
            binary_probability=_as_float(event.binary_evidence.get("fall_probability") or event.binary_evidence.get("max_fall_probability")),
            persistent_strong_candidate=bool(event.binary_evidence.get("persistent_strong_candidate")),
            candidate_alert_active=True,
        )
        fusion_ms = round((time.perf_counter() - fusion_started) * 1000, 3)
        timing = {
            **(detail.timing or {}),
            "fusion_ms": fusion_ms,
            "final_latency_ms": _elapsed_ms_since(event.confirmed_at),
        }
        detail = FallDetailResult(
            **{
                **detail.to_record(),
                "qwen_start_frames_received": qwen_start_frames_received,
                "qwen_end_frames_received": qwen_end_frames_received,
                "frames_received_during_qwen": frames_received_during_qwen,
                "fusion_version": detail.fusion_version or FUSION_VERSION,
                "timing": timing,
            }
        )
        with self._lock:
            latest = self._events[incident_id]
            updated = replace(
                latest,
                vlm_status=detail.analysis_status,
                vlm_analysis=detail,
                vlm_reviews=[*latest.vlm_reviews, detail],
            )
            self._events[incident_id] = updated
            self._qwen_media.pop(incident_id, None)
            self._vlm_finished.add(incident_id)
        aggregate = self._aggregator.latest(updated.camera_id)
        updated = self._apply_safety_decision(updated, aggregate)
        if self._evidence_exporter is not None:
            try:
                self._evidence_exporter.export_qwen_confirmation(updated)
            except Exception:
                logger.exception("post_fall_v2_qwen_evidence_export_failed incident_id=%s", incident_id)
        if self._test_archive is not None:
            try:
                self._test_archive.archive_qwen_result(updated)
            except Exception:
                logger.exception("post_fall_v2_test_qwen_archive_failed incident_id=%s", incident_id)
        self._publish_vlm_update(updated)
        self._dispatch_safety_alert(updated, updated.keyframes or keyframes)
        logger.info("vlm_review_finished incident_id=%s status=%s", incident_id, detail.analysis_status)
        model_log_bus.publish(
            "qwen",
            "qwen_review_finished",
            camera_id=updated.camera_id,
            incident_id=incident_id,
            status=detail.analysis_status,
            fall_verdict=detail.fall_verdict,
            confidence=detail.confidence,
            model=detail.model_name,
            summary=detail.summary,
            error=detail.error_message,
            qwen_start_frames_received=qwen_start_frames_received,
            qwen_end_frames_received=qwen_end_frames_received,
            frames_received_during_qwen=frames_received_during_qwen,
        )

    def _worker_frame_seq(self, camera_id: str) -> int | None:
        if not hasattr(self.source_manager, "worker_status"):
            return None
        worker_status = self.source_manager.worker_status(camera_id)
        if worker_status is None:
            return None
        try:
            return int(worker_status.frame_seq)
        except (TypeError, ValueError):
            return None

    def _report_safety_alert(self, event: FallEvent) -> None:
        if self._fall_event_reporter is None or event.safety_decision is None:
            return
        safety = event.safety_decision
        if safety.outcome != "alert":
            return
        detail = event.vlm_analysis
        transition_alert = safety.path == "transition_fall"
        fall_state = "fallen_confirmed"
        confirm_source = "event_state_transition_fall" if transition_alert else "event_state_post_fall_persistent_abnormality"
        source = "post_fall_v2_transition" if transition_alert else "post_fall_v2_persistent_abnormality"
        keyframes = event.keyframes
        evidence = event.binary_evidence if isinstance(event.binary_evidence, dict) else {}
        target_binding = event.target_binding or evidence.get("target_binding") or {}
        frame_width = int(target_binding.get("original_width") or (keyframes.source_width if keyframes is not None else 0)) or 1
        frame_height = int(target_binding.get("original_height") or (keyframes.source_height if keyframes is not None else 0)) or 1
        roi = target_binding.get("roi") if isinstance(target_binding.get("roi"), list) else None
        bbox = (
            [float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3])]
            if roi and len(roi) == 4
            else [0.0, 0.0, float(frame_width), float(frame_height)]
        )
        probability = _as_float(evidence.get("max_fall_probability") or evidence.get("mean_fall_probability") or evidence.get("fall_probability")) or 0.91
        result = VisionResult(
            camera_id=event.camera_id,
            timestamp=event.confirmed_at,
            frame_seq=_as_int(evidence.get("frame_seq")) or 0,
            frame_width=frame_width,
            frame_height=frame_height,
            objects=[
                DetectedObject(
                    label="person",
                    confidence=1.0,
                    bbox=bbox,
                    track_id=0,
                    is_target=True,
                    temporal={
                        "source": source,
                        "fall_probability": probability,
                        "binary_evidence": event.binary_evidence,
                        "qwen": detail.to_record() if detail is not None else {},
                        "target_binding": target_binding or None,
                    },
                    fall_decision={
                        "pipeline": "post_fall_v2",
                        "source": source,
                        "fall_state": fall_state,
                        "status": fall_state,
                        "confirm_source": confirm_source,
                        "decision_authority": "event_state_machine",
                        "safety_outcome": safety.outcome,
                        "safety_path": safety.path,
                        "safety_reason": safety.reason,
                        "fall_probability": probability,
                        "incident_id": event.incident_id,
                        "vlm_status": detail.analysis_status if detail is not None else event.vlm_status,
                        "fall_verdict": detail.fall_verdict if detail is not None else None,
                        "high_risk_fall": detail.high_risk_fall if detail is not None else 0,
                        "scene_type": detail.scene_type if detail is not None else "unknown",
                        "recommended_action": detail.recommended_action if detail is not None else "manual_review",
                        "vlm_summary": detail.summary if detail is not None else "持续异常低姿态，未获得明确非跌倒证据。",
                        "qwen_gate": _qwen_gate_state(event),
                        "person_evidence": True,
                        "target_binding": target_binding or None,
                        "target_tracking_state": target_binding.get("target_tracking_state"),
                    },
                    alarm_preview={
                        "confirmed": True,
                        "requires_attention": True,
                        "risk_level": "high",
                        "fall_probability": probability,
                        "source": source,
                        "confirm_source": confirm_source,
                        "fall_verdict": detail.fall_verdict if detail is not None else None,
                        "high_risk_fall": detail.high_risk_fall if detail is not None else 0,
                        "scene_type": detail.scene_type if detail is not None else "unknown",
                        "recommended_action": detail.recommended_action if detail is not None else "manual_review",
                        "summary": detail.summary if detail is not None else "持续异常低姿态，需要立即查看。",
                        "qwen_gate": _qwen_gate_state(event),
                        "safety_outcome": safety.outcome,
                        "safety_path": safety.path,
                        "person_evidence": True,
                        "target_tracking_state": target_binding.get("target_tracking_state"),
                    },
                )
            ],
            detector={
                "pipeline": "post_fall_v2",
                "model": "post_fall_v2_safety_decision",
                "binary_model": "efficientnet_b0_post_fall",
                "qwen_model": detail.model_name if detail is not None else None,
                "fall_verdict": detail.fall_verdict if detail is not None else None,
                "vlm_status": detail.analysis_status if detail is not None else event.vlm_status,
                "safety_decision": safety.to_record(),
                "target_binding": target_binding or None,
                "_monotonic_at": time.monotonic(),
            },
        )
        self._fall_event_reporter.inspect_result(result)

    def _apply_safety_decision(
        self,
        event: FallEvent,
        aggregate: BinaryAggregateDecision | None,
    ) -> FallEvent:
        with self._lock:
            latest = self._events.get(event.incident_id, event)
        binary_state = aggregate.state if aggregate is not None else "NORMAL"
        elapsed_ms = max(
            aggregate.evidence.candidate_duration_ms if aggregate is not None else int(latest.binary_evidence.get("candidate_duration_ms") or 0),
            _elapsed_ms_since(latest.confirmed_at),
        )
        safety = evaluate_fall_safety(
            latest,
            binary_state=binary_state,
            observation_elapsed_ms=elapsed_ms,
            post_fall_alert_min_ms=self.settings.post_fall_v2_post_fall_alert_min_ms,
            followup_complete=(
                not self._vlm.enabled
                or latest.vlm_status in {"disabled", "completed", "failed", "timeout", "parse_failed"}
            ),
        )
        previous = latest.safety_decision
        if previous is not None and _same_safety_decision(previous, safety):
            return latest
        updated = replace(latest, safety_decision=safety)
        with self._lock:
            self._events[event.incident_id] = updated
        model_log_bus.publish(
            "qwen",
            "safety_decision_changed",
            camera_id=event.camera_id,
            incident_id=event.incident_id,
            outcome=safety.outcome,
            path=safety.path,
            reason=safety.reason,
            observation_elapsed_ms=safety.observation_elapsed_ms,
        )
        return updated

    def _dispatch_safety_alert(self, event: FallEvent, keyframes: KeyframePackage | None) -> None:
        safety = event.safety_decision
        if safety is None or safety.outcome != "alert":
            return
        with self._lock:
            if event.incident_id in self._alerted_incidents:
                return
            self._alerted_incidents.add(event.incident_id)
        if keyframes is not None:
            self._send_to_event_outbox(event, keyframes)
        self._report_safety_alert(event)

    def _publish(
        self,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
        event: FallEvent | None,
    ) -> None:
        active_event = event
        if active_event is None and decision.incident_id:
            active_event = self.latest_event(decision.incident_id)
        if active_event is not None:
            active_event = self._apply_safety_decision(active_event, decision)
            self._dispatch_safety_alert(active_event, active_event.keyframes)
        binary_event_active = decision.state in {"EVENT_ACTIVE", "FALL_CONFIRMED"}
        qwen_gate = _qwen_gate_state(active_event)
        safety = active_event.safety_decision if active_event is not None else None
        alert_active = bool(safety is not None and safety.outcome == "alert")
        candidate_alert_active = bool(
            binary.valid
            and binary.fall_probability is not None
            and binary.fall_probability >= binary.threshold
        )
        business_decision = _business_decision_payload(
            event=active_event,
            binary=binary,
            safety=safety,
            candidate_alert_active=candidate_alert_active,
        )
        final_alert_active = bool(
            business_decision.get("is_true_fall")
            if active_event is not None and active_event.vlm_analysis is not None
            else alert_active
        )
        if active_event is not None:
            public_fall_state = _public_fall_state(safety)
        else:
            public_fall_state = decision.state.lower()
        target_binding = binary.target_binding or {}
        frame_width = int(target_binding.get("original_width") or binary.source_width or 1)
        frame_height = int(target_binding.get("original_height") or binary.source_height or 1)
        roi = target_binding.get("roi") if isinstance(target_binding.get("roi"), list) else None
        bbox = (
            [float(roi[0]), float(roi[1]), float(roi[2]), float(roi[3])]
            if roi and len(roi) == 4
            else [0.0, 0.0, float(frame_width), float(frame_height)]
        )
        fall_decision = {
            "pipeline": "post_fall_v2",
            "source": "post_fall_v2_binary",
            "post_fall_v2_input_mode": self._input_mode,
            "binary_input_source": target_binding.get("binary_input_source"),
            "fall_state": public_fall_state,
            "status": public_fall_state,
            "binary_fall_state": decision.state,
            "binary_label": binary.decision_label,
            "fall_probability": binary.fall_probability,
            "non_fall_probability": binary.non_fall_probability,
            "threshold": binary.threshold,
            "incident_id": decision.incident_id,
            "event_created": decision.event_created,
            "reason": decision.reason,
            "evidence": decision.evidence.to_record(),
            "candidate_alert": candidate_alert_active,
            "final_alert": final_alert_active,
            "decision": business_decision,
            "qwen_gate": qwen_gate,
            "decision_authority": "event_state_machine",
            "target_binding": target_binding or None,
            "target_tracking_state": target_binding.get("target_tracking_state"),
        }
        if safety is not None:
            fall_decision["safety_decision"] = safety.to_record()
            fall_decision["safety_outcome"] = safety.outcome
            fall_decision["safety_path"] = safety.path
        if active_event is not None:
            fall_decision["vlm_status"] = active_event.vlm_status
            if active_event.keyframes is not None:
                fall_decision["keyframe_status"] = active_event.keyframes.status
                fall_decision["keyframe_missing_offsets_ms"] = active_event.keyframes.missing_offsets_ms
            if active_event.vlm_analysis is not None:
                fall_decision["vlm_summary"] = active_event.vlm_analysis.summary
                fall_decision["high_risk_fall"] = active_event.vlm_analysis.high_risk_fall
                fall_decision["scene_type"] = active_event.vlm_analysis.scene_type
                fall_decision["recommended_action"] = active_event.vlm_analysis.recommended_action
            else:
                fall_decision["vlm_summary"] = None
                fall_decision["high_risk_fall"] = 0
        obj = DetectedObject(
            label="person",
            confidence=1.0,
            bbox=bbox,
            track_id=0,
            is_target=True,
            temporal={
                "source": "post_fall_v2_binary",
                "fall_probability": binary.fall_probability,
                "window_size": decision.evidence.window_size,
                "binary_input_source": target_binding.get("binary_input_source"),
                "target_binding": target_binding or None,
            },
            fall_decision=fall_decision,
            alarm_preview={
                "confirmed": bool(final_alert_active and safety is not None and safety.path == "transition_fall"),
                "requires_attention": final_alert_active,
                "candidate_alert": candidate_alert_active,
                "final_alert": final_alert_active,
                "decision": business_decision,
                "risk_level": "high" if final_alert_active else "low",
                "fall_probability": binary.fall_probability,
                "source": "post_fall_v2_binary",
                "qwen_gate": qwen_gate,
                "safety_outcome": safety.outcome if safety is not None else "observe",
                "safety_path": safety.path if safety is not None else "uncertain_evidence",
                "target_tracking_state": target_binding.get("target_tracking_state"),
            },
        )
        result = VisionResult(
            camera_id=binary.camera_id,
            timestamp=binary.inferred_at,
            frame_seq=binary.frame_seq,
            frame_width=frame_width,
            frame_height=frame_height,
            objects=[obj],
            detector={
                "pipeline": "post_fall_v2",
                "model": binary.model_name,
                "model_version": binary.model_version,
                "post_fall_v2_input_mode": self._input_mode,
                "binary_input_source": target_binding.get("binary_input_source"),
                "binary_label": binary.decision_label,
                "fall_probability": binary.fall_probability,
                "target_binding": target_binding or None,
                "_monotonic_at": time.monotonic(),
            },
        )
        self.realtime_store.update_published(result)
        self.result_channels.publish(result)

    def _publish_vlm_update(self, event: FallEvent) -> None:
        latest = self.realtime_store.latest_published(event.camera_id)
        if latest is None:
            return
        objects = []
        changed = False
        for obj in latest.objects:
            fall_decision = dict(obj.fall_decision or {})
            if fall_decision.get("incident_id") != event.incident_id:
                objects.append(obj)
                continue
            fall_decision["vlm_status"] = event.vlm_status
            qwen_gate = _qwen_gate_state(event)
            fall_decision["qwen_gate"] = qwen_gate
            fall_decision["fall_verdict"] = (
                event.vlm_analysis.fall_verdict if event.vlm_analysis is not None else None
            )
            fall_decision["high_risk_fall"] = (
                event.vlm_analysis.high_risk_fall if event.vlm_analysis is not None else 0
            )
            fall_decision["scene_type"] = (
                event.vlm_analysis.scene_type if event.vlm_analysis is not None else "unknown"
            )
            fall_decision["recommended_action"] = (
                event.vlm_analysis.recommended_action if event.vlm_analysis is not None else "manual_review"
            )
            safety = event.safety_decision
            alert_active = bool(safety is not None and safety.outcome == "alert")
            business_decision = _business_decision_payload(
                event=event,
                binary=None,
                safety=safety,
                candidate_alert_active=bool(fall_decision.get("candidate_alert")),
            )
            final_alert_active = bool(
                business_decision.get("is_true_fall")
                if event.vlm_analysis is not None
                else alert_active
            )
            fall_decision["fall_state"] = _public_fall_state(safety)
            fall_decision["status"] = fall_decision["fall_state"]
            fall_decision["decision_authority"] = "event_state_machine"
            fall_decision["final_alert"] = final_alert_active
            fall_decision["decision"] = business_decision
            if safety is not None:
                fall_decision["safety_decision"] = safety.to_record()
                fall_decision["safety_outcome"] = safety.outcome
                fall_decision["safety_path"] = safety.path
            if event.vlm_analysis is not None:
                fall_decision["vlm_summary"] = event.vlm_analysis.summary
            else:
                fall_decision["vlm_summary"] = None
            if event.keyframes is not None:
                fall_decision["keyframe_status"] = event.keyframes.status
                fall_decision["keyframe_missing_offsets_ms"] = event.keyframes.missing_offsets_ms
            alarm_preview = dict(obj.alarm_preview or {})
            alarm_preview.update(
                {
                    "confirmed": bool(final_alert_active and safety is not None and safety.path == "transition_fall"),
                    "requires_attention": final_alert_active,
                    "risk_level": "high" if final_alert_active else "low",
                    "qwen_gate": qwen_gate,
                    "fall_verdict": fall_decision["fall_verdict"],
                    "high_risk_fall": fall_decision["high_risk_fall"],
                    "scene_type": fall_decision["scene_type"],
                    "recommended_action": fall_decision["recommended_action"],
                    "final_alert": final_alert_active,
                    "decision": business_decision,
                    "safety_outcome": safety.outcome if safety is not None else "observe",
                    "safety_path": safety.path if safety is not None else "uncertain_evidence",
                }
            )
            objects.append(obj.model_copy(update={"fall_decision": fall_decision, "alarm_preview": alarm_preview}))
            changed = True
        if not changed:
            return
        updated = latest.model_copy(
            update={
                "objects": objects,
                "detector": {
                    **latest.detector,
                    "vlm_status": event.vlm_status,
                    "_monotonic_at": time.monotonic(),
                },
            }
        )
        self.realtime_store.update_published(updated)
        self.result_channels.publish(updated)

    def _send_to_event_outbox(self, event: FallEvent, keyframes: KeyframePackage) -> None:
        if self.event_pipeline is None:
            return
        evidence = event.binary_evidence if isinstance(event.binary_evidence, dict) else {}
        safety = event.safety_decision
        record = FallEventRecord(
            incident_id=event.incident_id,
            camera_id=event.camera_id,
            track_id=0,
            event_type="fallen_confirmed",
            fall_state="fallen_confirmed",
            risk_level="high",
            risk_score=_as_float(evidence.get("max_fall_probability") or evidence.get("mean_fall_probability")),
            trigger_frame_seq=_as_int(evidence.get("frame_seq")),
            trigger_timestamp=event.confirmed_at,
            bbox=None,
            fall_probability=_as_float(evidence.get("fall_probability") or evidence.get("max_fall_probability")),
            fall_evidence_score=_as_float(evidence.get("max_fall_probability")),
            metadata={
                "pipeline": "post_fall_v2",
                "binary_evidence": event.binary_evidence,
                "keyframes": keyframes.to_record(),
                "safety_decision": safety.to_record() if safety is not None else None,
                "qwen_review": event.vlm_analysis.to_record() if event.vlm_analysis is not None else None,
                "target_binding": event.target_binding,
            },
        )
        try:
            self.event_pipeline.outbox.add_event(record)
        except Exception:
            logger.exception("post_fall_v2_event_outbox_add_failed incident_id=%s", event.incident_id)

    def _cancel_keyframe_sessions(self, camera_id: str) -> None:
        with self._lock:
            sessions = [
                (incident_id, session, self._keyframe_stops.get(incident_id), self._keyframe_threads.get(incident_id))
                for incident_id, session in self._keyframe_sessions.items()
                if session.camera_id == camera_id
            ]
        for incident_id, session, stop_event, thread in sessions:
            if stop_event is not None:
                stop_event.set()
            session.cancel()
            if thread is not None and thread.is_alive():
                thread.join(timeout=1)
            with self._lock:
                self._keyframe_sessions.pop(incident_id, None)
                self._qwen_media.pop(incident_id, None)

    def _put_latest(self, camera_id: str, frame_queue: queue.Queue[SampledFrame], sampled: SampledFrame) -> None:
        dropped = 0
        while frame_queue.full():
            try:
                frame_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        try:
            frame_queue.put_nowait(sampled)
        except queue.Full:
            dropped += 1
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.frames_sampled += 1
                state.frames_dropped += dropped

    def _update_state(self, camera_id: str, binary: BinaryFrameResult, raw, sampled: SampledFrame) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return
            state.frames_processed += 1
            state.last_probability = binary.fall_probability
            state.last_label = binary.decision_label
            state.last_inference_at = binary.inferred_at
            state.last_binary_input_source = (sampled.target_binding or {}).get("binary_input_source")
            performance = getattr(raw, "performance", None)
            state.last_frame_age_ms = round((time.monotonic() - sampled.captured_monotonic) * 1000, 2)
            state.last_queue_delay_ms = getattr(performance, "queue_delay_ms", None)
            state.last_preprocess_ms = getattr(performance, "preprocess_ms", None)
            state.last_inference_ms = getattr(performance, "inference_ms", None)
            state.last_total_ms = getattr(performance, "total_ms", None)
            if state.last_inference_ms is not None:
                state.inference_latencies_ms.append(float(state.last_inference_ms))
                if state.inference_latency_avg_ms is None:
                    state.inference_latency_avg_ms = state.last_inference_ms
                else:
                    state.inference_latency_avg_ms = round(
                        state.inference_latency_avg_ms * 0.85 + state.last_inference_ms * 0.15,
                        2,
                    )
                state.inference_latency_p95_ms = _percentile(list(state.inference_latencies_ms), 0.95)
            if not binary.valid:
                state.frames_invalid += 1
                state.last_error = binary.error_message
            else:
                state.last_error = None

    def _log_binary_progress(
        self,
        camera_id: str,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
    ) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._states.get(camera_id)
            if state is None or now - state.last_log_monotonic < 1.0:
                return
            state.last_log_monotonic = now
            frames_processed = state.frames_processed
            frames_dropped = state.frames_dropped
            queue_depth = state.queue.qsize()
            frame_age_ms = state.last_frame_age_ms
            inference_ms = state.last_inference_ms
            avg_latency_ms = state.inference_latency_avg_ms
            queue_delay_ms = state.last_queue_delay_ms
            input_source = state.last_binary_input_source
        model_log_bus.publish(
            "binary",
            "binary_progress",
            camera_id=camera_id,
            provider=getattr(self._classifier, "provider", None),
            input_mode=self._input_mode,
            input_source=input_source,
            frame_seq=binary.frame_seq,
            label=binary.decision_label,
            fall_probability=binary.fall_probability,
            aggregate_state=decision.state,
            aggregate_reason=decision.reason,
            incident_id=decision.incident_id,
            frames_processed=frames_processed,
            frames_dropped=frames_dropped,
            queue_depth=queue_depth,
            frame_age_ms=frame_age_ms,
            inference_ms=inference_ms,
            avg_latency_ms=avg_latency_ms,
            queue_delay_ms=queue_delay_ms,
        )

    def _set_error(self, camera_id: str, message: str) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.last_error = message
        model_log_bus.publish("binary", "binary_error", level="error", camera_id=camera_id, error=message)

    def _load_classifier_safely(self) -> None:
        with self._classifier_load_lock:
            if self._classifier is not None and self._classifier.loaded:
                return
            if self.settings.post_fall_v2_input_policy != FULL_FRAME_TRAIN_MATCHED:
                self._classifier_error = f"unsupported input policy: {self.settings.post_fall_v2_input_policy}"
                model_log_bus.publish("binary", "binary_model_load_skipped", level="error", error=self._classifier_error)
                return
            try:
                self._classifier_loading = True
                model_log_bus.publish(
                    "binary",
                    "binary_model_loading",
                    model_path=str(self._resolve_path(self.settings.post_fall_v2_model_path)),
                    providers=self.settings.post_fall_v2_binary_onnx_providers,
                )
                self._classifier = FallBinaryClassifierService(
                    model_path=self._resolve_path(self.settings.post_fall_v2_model_path),
                    expected_sha256=self.settings.post_fall_v2_binary_model_sha256,
                    threshold=self.settings.post_fall_v2_binary_threshold,
                    input_policy=self.settings.post_fall_v2_input_policy,
                    providers=[
                        part.strip()
                        for part in self.settings.post_fall_v2_binary_onnx_providers.split(",")
                        if part.strip()
                    ],
                    warmup_runs=self.settings.post_fall_v2_binary_warmup_runs,
                )
                self._classifier_error = None
            except Exception as exc:
                self._classifier = None
                self._classifier_error = str(exc)
                logger.exception("post_fall_v2_runtime_classifier_load_failed")
                model_log_bus.publish("binary", "binary_model_load_failed", level="error", error=str(exc))
            finally:
                self._classifier_loading = False

    def _preload_classifier_async(self) -> None:
        thread = threading.Thread(
            target=self._load_classifier_safely,
            name="post-fall-v2-binary-preload",
            daemon=True,
        )
        thread.start()
        model_log_bus.publish("binary", "binary_model_preload_started")

    @staticmethod
    def _resolve_path(path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parents[2] / candidate


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _business_decision_payload(
    *,
    event: FallEvent | None,
    binary: BinaryFrameResult | None,
    safety: FallSafetyDecision | None,
    candidate_alert_active: bool,
) -> dict[str, object]:
    detail = event.vlm_analysis if event is not None else None
    evidence = event.binary_evidence if event is not None and isinstance(event.binary_evidence, dict) else {}
    binary_probability = _as_float(
        (binary.fall_probability if binary is not None else None)
        or evidence.get("fall_probability")
        or evidence.get("max_fall_probability")
    )
    decision = build_competition_decision(
        detail=detail,
        binary_probability=binary_probability,
        persistent_strong_candidate=bool(evidence.get("persistent_strong_candidate")),
        candidate_alert_active=candidate_alert_active,
    )
    final_alert = bool(
        decision.get("is_true_fall")
        if detail is not None
        else (safety is not None and safety.outcome == "alert")
    )
    return {
        **decision,
        "candidate_alert": candidate_alert_active,
        "final_alert": final_alert,
    }


def _qwen_gate_state(event: FallEvent | None) -> str:
    """Expose semantic review state without making it the alert authority."""
    if event is None:
        return "pending"
    if event.vlm_status == "disabled":
        return "observe"
    detail = event.vlm_analysis
    if detail is None:
        return "pending"
    if detail.analysis_status != "completed":
        return "observe"
    if detail.activity in {"confirmed_fall", "possible_fall_or_distress"}:
        return "confirmed"
    if detail.activity in {"lying_using_phone", "lying_reading", "normal_activity"}:
        return "denied"
    if detail.activity == "uncertain":
        return "observe"
    if detail.fall_verdict == "confirmed_fall" and int(detail.high_risk_fall or 0) == 1:
        return "confirmed"
    if detail.fall_verdict in {"normal_activity", "intentional_low_posture", "non_fall"}:
        return "denied"
    return "observe"


def _public_fall_state(safety: FallSafetyDecision | None) -> str:
    if safety is None:
        return "observe_post_fall"
    if safety.outcome == "dismiss":
        return "qwen_denied"
    if safety.outcome == "observe":
        return "observe_post_fall"
    return "fallen_confirmed"


def _same_safety_decision(left: FallSafetyDecision, right: FallSafetyDecision) -> bool:
    return (
        left.outcome == right.outcome
        and left.path == right.path
        and left.alert_level == right.alert_level
        and left.reason == right.reason
        and left.qwen_verdict == right.qwen_verdict
        and left.review_required == right.review_required
    )


def _elapsed_ms_since(iso_timestamp: str | None) -> int:
    if not iso_timestamp:
        return 0
    try:
        normalized = iso_timestamp.replace("Z", "+00:00")
        started = datetime.fromisoformat(normalized)
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds() * 1000))
    except Exception:
        return 0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * max(0.0, min(1.0, percentile))))
    return round(float(ordered[index]), 2)
