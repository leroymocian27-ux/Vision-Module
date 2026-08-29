from __future__ import annotations

from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import mask_source_url
from app.camera.frame_freshness import unavailable_result
from app.core.config import safe_configuration_snapshot
from app.fall.status_contract import camera_unavailable_reason, confidence_level, degraded_by_from_payload
from app.pose.placeholders import pose_has_visible_keypoints
from app.detection.realtime_result_store import RealtimeResultStore
from app.schemas.status import (
    BehaviorStatus,
    CameraStatus,
    ConfigurationStatus,
    DetectionStatus,
    DiagnosticsStatus,
    FallEventReporterStatus,
    LatestResultStatus,
    IdentityStatus,
    PipelineStatus,
    PollingAlertStatus,
    PoseStatus,
    StreamRuntimeAlias,
    StreamingStatus,
    TemporalStatus,
    TrackingStatus,
    VisionStatus,
)
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.fall_hint_worker_service import FallHintWorkerService
from app.services.behavior_service import BehaviorService
from app.services.detection_service import DetectionService
from app.services.identity_binding_service import IdentityBindingService
from app.services.identity_binding_worker_service import IdentityBindingWorkerService
from app.services.identity_service import IdentityService
from app.services.pose_service import PoseService
from app.services.result_publisher_service import ResultPublisherService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.temporal_service import TemporalService
from app.services.temporal_worker_service import TemporalWorkerService
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService
from app.fall.fusion import FallFusionService
from app.post_fall_v2.fall_binary_shadow_service import FallBinaryShadowService
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.streaming.peer_manager import PeerManager
from app.streaming.result_channel_manager import ResultChannelManager


class StatusService:
    def __init__(
        self,
        settings,
        source_manager: CameraSourceManager,
        detection_service: DetectionService,
        peer_manager: PeerManager,
        result_channels: ResultChannelManager,
        realtime_store: RealtimeResultStore,
        tracking_service: TrackingService | None = None,
        tracking_worker_service: TrackingWorkerService | None = None,
        identity_service: IdentityService | None = None,
        identity_binding_service: IdentityBindingService | None = None,
        identity_binding_worker_service: IdentityBindingWorkerService | None = None,
        pose_service: PoseService | None = None,
        behavior_service: BehaviorService | None = None,
        temporal_service: TemporalService | None = None,
        temporal_worker_service: TemporalWorkerService | None = None,
        fusion_worker_service: FusionWorkerService | None = None,
        fall_fusion_service: FallFusionService | None = None,
        result_publisher_service: ResultPublisherService | None = None,
        fall_event_reporter: FallEventReporterService | None = None,
        fall_hint_worker_service: FallHintWorkerService | None = None,
        post_fall_v2_shadow_service: FallBinaryShadowService | None = None,
        post_fall_v2_runtime_service: PostFallV2RuntimeService | None = None,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.detection_service = detection_service
        self.fall_hint_worker_service = fall_hint_worker_service
        self.peer_manager = peer_manager
        self.result_channels = result_channels
        self.realtime_store = realtime_store
        self.tracking_service = tracking_service
        self.tracking_worker_service = tracking_worker_service
        self.identity_service = identity_service
        self.identity_binding_service = identity_binding_service
        self.identity_binding_worker_service = identity_binding_worker_service
        self.pose_service = pose_service
        self.behavior_service = behavior_service
        self.temporal_service = temporal_service
        self.temporal_worker_service = temporal_worker_service
        self.fusion_worker_service = fusion_worker_service
        self.fall_fusion_service = fall_fusion_service
        self.result_publisher_service = result_publisher_service
        self.fall_event_reporter = fall_event_reporter
        self.post_fall_v2_shadow_service = post_fall_v2_shadow_service
        self.post_fall_v2_runtime_service = post_fall_v2_runtime_service

    def status(self, camera_id: str | None = None) -> VisionStatus:
        runtimes = self.source_manager.list_runtimes()
        if camera_id:
            runtimes = [runtime for runtime in runtimes if runtime.config.camera_id == camera_id]

        cameras: list[CameraStatus] = []
        detections: list[DetectionStatus] = []
        for runtime in runtimes:
            worker_status = runtime.worker.status()
            cameras.append(
                CameraStatus(
                    camera_id=runtime.config.camera_id,
                    running=worker_status.running,
                    connected=worker_status.connected,
                    source_url_masked=mask_source_url(runtime.config.source_url),
                    frame_seq=worker_status.frame_seq,
                    frame_width=worker_status.frame_width,
                    frame_height=worker_status.frame_height,
                    frame_age_ms=worker_status.frame_age_ms,
                    last_frame_at=worker_status.last_frame_at,
                    received_at=worker_status.received_at,
                    source=worker_status.source,
                    source_protocol=worker_status.source_protocol,
                    source_generation=worker_status.source_generation,
                    raw_jpeg_available=worker_status.raw_jpeg_available,
                    frame_status=worker_status.frame_status,
                    is_stale=worker_status.is_stale,
                    safe_to_interpret_as_no_fall=worker_status.safe_to_interpret_as_no_fall,
                    stream_state=worker_status.stream_state,
                    capture_fps=worker_status.capture_fps,
                    reconnect_count=worker_status.reconnect_count,
                    read_latency_ms=worker_status.read_latency_ms,
                    read_latency_max_ms=worker_status.read_latency_max_ms,
                    read_timeout_count=worker_status.read_timeout_count,
                    stale_count=worker_status.stale_count,
                    last_read_started_at=worker_status.last_read_started_at,
                    last_read_completed_at=worker_status.last_read_completed_at,
                    consecutive_slow_reads=worker_status.consecutive_slow_reads,
                    reconnect_reason=worker_status.reconnect_reason,
                    capture_backend=worker_status.capture_backend,
                    capture_process_alive=worker_status.capture_process_alive,
                    capture_process_pid=worker_status.capture_process_pid,
                    capture_process_restart_count=worker_status.capture_process_restart_count,
                    capture_process_last_frame_age_ms=worker_status.capture_process_last_frame_age_ms,
                    capture_process_last_error=worker_status.capture_process_last_error,
                    capture_process_last_exit_code=worker_status.capture_process_last_exit_code,
                    capture_ipc_decode_errors=worker_status.capture_ipc_decode_errors,
                    capture_ipc_dropped_frames=worker_status.capture_ipc_dropped_frames,
                    capture_output_width=worker_status.capture_output_width,
                    capture_output_height=worker_status.capture_output_height,
                    mjpeg_content_type=worker_status.mjpeg_content_type,
                    mjpeg_parsed_frames=worker_status.mjpeg_parsed_frames,
                    last_error=worker_status.last_error,
                )
            )
            detection_status = self.detection_service.status(runtime.config.camera_id)
            detections.append(
                DetectionStatus(
                    camera_id=detection_status.camera_id,
                    running=detection_status.running,
                    enabled=detection_status.enabled,
                    loaded=detection_status.loaded,
                    model_name=detection_status.model_name,
                    detection_fps=detection_status.detection_fps,
                    fall_hint_fps=detection_status.fall_hint_fps,
                    inference_latency_ms=detection_status.inference_latency_ms,
                    fall_inference_latency_ms=detection_status.fall_inference_latency_ms,
                    pipeline_mode=detection_status.pipeline_mode,
                    fall_hint_writer_source=detection_status.fall_hint_writer_source,
                    last_error=detection_status.last_error,
                    latest_raw_person_count=detection_status.latest_raw_person_count,
                    latest_fall_model_count=detection_status.latest_fall_model_count,
                    latest_person_boxes=detection_status.latest_person_boxes or [],
                    latest_person_confidences=detection_status.latest_person_confidences or [],
                    latest_fall_labels=detection_status.latest_fall_labels or [],
                    latest_fall_confidences=detection_status.latest_fall_confidences or [],
                    latest_fall_boxes=detection_status.latest_fall_boxes or [],
                )
            )

        tracking_status = TrackingStatus()
        if self.tracking_service is not None:
            tracking_camera_id = camera_id
            if tracking_camera_id is None and runtimes:
                tracking_camera_id = runtimes[0].config.camera_id
            if tracking_camera_id:
                raw_tracking_status = self.tracking_service.status(tracking_camera_id)
                tracking_status = TrackingStatus(**raw_tracking_status.model_dump())

        identity_status = IdentityStatus()
        if self.identity_service is not None:
            raw_identity_status = self.identity_service.status()
            identity_status = IdentityStatus(
                identity_enabled=raw_identity_status.identity_enabled,
                identity_binding_enabled=False,
                recognizer_loaded=raw_identity_status.recognizer_loaded,
                recognizer_name=raw_identity_status.recognizer_name,
                model_name=raw_identity_status.model_name,
                registered_count=raw_identity_status.registered_count,
                last_error=raw_identity_status.last_error,
            )
        if self.identity_binding_service is not None:
            identity_status.identity_binding_enabled = self.identity_binding_service.settings.enable_identity_binding
            identity_status.identity_service_available = self.identity_binding_service.service_available
            identity_status.recognizer_loaded = self.identity_binding_service.recognizer_loaded or identity_status.recognizer_loaded
            identity_status.registered_count = max(
                identity_status.registered_count,
                self.identity_binding_service.registered_count,
            )
            identity_status.bound_person_id = self.identity_binding_service.bound_person_id
            identity_status.bound_person_name = self.identity_binding_service.bound_person_name
            identity_status.last_match_score = self.identity_binding_service.last_match_score
            identity_status.cache_age_ms = self.identity_binding_service.cache_age_ms
            identity_status.last_match_latency_ms = self.identity_binding_service.last_match_latency_ms
            identity_status.pending_requests = self.identity_binding_service.pending_requests
            identity_status.skipped_due_to_inflight = self.identity_binding_service.skipped_due_to_inflight
            identity_status.health_cache_age_ms = self.identity_binding_service.health_cache_age_ms
            identity_status.last_error = self.identity_binding_service.last_error or identity_status.last_error
            if self.identity_binding_worker_service is not None:
                worker_error = self.identity_binding_worker_service.last_error(
                    camera_id or (runtimes[0].config.camera_id if runtimes else "")
                )
                identity_status.last_error = worker_error or identity_status.last_error

        pose_status = PoseStatus()
        if self.pose_service is not None:
            pose_camera_id = camera_id
            if pose_camera_id is None and runtimes:
                pose_camera_id = runtimes[0].config.camera_id
            raw_pose_status = self.pose_service.status(pose_camera_id)
            pose_status = PoseStatus(**raw_pose_status.model_dump())

        behavior_status = BehaviorStatus()
        if self.behavior_service is not None:
            behavior_camera_id = camera_id
            if behavior_camera_id is None and runtimes:
                behavior_camera_id = runtimes[0].config.camera_id
            raw_behavior_status = self.behavior_service.status(behavior_camera_id)
            behavior_status = BehaviorStatus(**raw_behavior_status.model_dump())

        temporal_status = TemporalStatus()
        if self.temporal_service is not None:
            temporal_camera_id = camera_id
            if temporal_camera_id is None and runtimes:
                temporal_camera_id = runtimes[0].config.camera_id
            raw_temporal_status = self.temporal_service.status(temporal_camera_id)
            temporal_status = TemporalStatus(**raw_temporal_status.model_dump())

        pipeline_status = PipelineStatus()
        latest_result_status = LatestResultStatus()
        workers_status: dict = {}
        pipeline_camera_id = camera_id
        if pipeline_camera_id is None and runtimes:
            pipeline_camera_id = runtimes[0].config.camera_id
        if pipeline_camera_id:
            snapshot = self.realtime_store.snapshot(pipeline_camera_id)
            fall_hint_status = (
                self.fall_hint_worker_service.status(pipeline_camera_id)
                if self.fall_hint_worker_service is not None
                else None
            )
            detection_for_pipeline = detections[0] if detections else None
            fall_hint_fps = (
                fall_hint_status.fps
                if fall_hint_status is not None and fall_hint_status.enabled
                else (detection_for_pipeline.fall_hint_fps if detection_for_pipeline is not None else 0.0)
            )
            fall_hint_latency_ms = (
                fall_hint_status.last_latency_ms
                if fall_hint_status is not None and fall_hint_status.enabled
                else (detection_for_pipeline.fall_inference_latency_ms if detection_for_pipeline is not None else None)
            )
            fall_hint_writer = (
                fall_hint_status.writer_source
                if fall_hint_status is not None and fall_hint_status.enabled
                else (detection_for_pipeline.fall_hint_writer_source if detection_for_pipeline is not None else "none")
            )
            evidence_freshness = {}
            evidence_age_ms = {}
            if snapshot.latest_published_result is not None:
                detector_debug = snapshot.latest_published_result.detector or {}
                evidence_freshness = detector_debug.get("evidence_freshness") or {}
                evidence_age_ms = detector_debug.get("evidence_age_ms") or {}
            workers_status = {
                "person_detector": {
                    "enabled": detection_for_pipeline.enabled if detection_for_pipeline is not None else False,
                    "running": detection_for_pipeline.running if detection_for_pipeline is not None else False,
                    "source": "DetectionService",
                    "fps": detection_for_pipeline.detection_fps if detection_for_pipeline is not None else 0.0,
                    "last_latency_ms": detection_for_pipeline.inference_latency_ms if detection_for_pipeline is not None else None,
                    "result_age_ms": self.realtime_store.age_ms(
                        snapshot.latest_detection.monotonic_at if snapshot.latest_detection else None
                    ),
                    "state": "healthy" if detection_for_pipeline and detection_for_pipeline.running else "stopped",
                    "last_error": detection_for_pipeline.last_error if detection_for_pipeline is not None else None,
                },
                "fall_hint_worker": (
                    fall_hint_status.__dict__
                    if fall_hint_status is not None
                    else {
                        "enabled": self.settings.fall_detector_enabled,
                        "running": False,
                        "source": "DetectionService",
                        "writer_source": fall_hint_writer,
                        "fps": fall_hint_fps,
                        "last_latency_ms": fall_hint_latency_ms,
                        "result_age_ms": self.realtime_store.age_ms(
                            snapshot.latest_fall_detection.monotonic_at if snapshot.latest_fall_detection else None
                        ),
                        "state": "healthy" if fall_hint_writer == "DetectionService" else "disabled",
                    }
                ),
            }
            if self.temporal_worker_service is not None:
                temporal_worker_status = self.temporal_worker_service.status(pipeline_camera_id)
                workers_status["temporal_worker"] = temporal_worker_status.__dict__
            if self.fusion_worker_service is not None:
                fusion_worker_status = self.fusion_worker_service.status(pipeline_camera_id)
                workers_status["fusion_worker"] = fusion_worker_status.__dict__
            if self.post_fall_v2_shadow_service is not None:
                workers_status["post_fall_v2_shadow"] = self.post_fall_v2_shadow_service.status(pipeline_camera_id)
            if self.post_fall_v2_runtime_service is not None:
                workers_status["post_fall_v2_runtime"] = self.post_fall_v2_runtime_service.status(pipeline_camera_id)
            publisher_error = (
                self.result_publisher_service.last_error(pipeline_camera_id)
                if self.result_publisher_service is not None
                else None
            )
            tracking_worker_error = (
                self.tracking_worker_service.last_error(pipeline_camera_id)
                if self.tracking_worker_service is not None
                else None
            )
            fusion_status = self.fall_fusion_service.status() if self.fall_fusion_service is not None else {}
            pipeline_status = PipelineStatus(
                detection_worker_fps=detection_for_pipeline.detection_fps if detection_for_pipeline else 0.0,
                fall_hint_worker_fps=fall_hint_fps,
                fall_hint_latency_ms=fall_hint_latency_ms,
                tracking_worker_fps=(
                    self.tracking_worker_service.status_fps(pipeline_camera_id)
                    if self.tracking_worker_service is not None
                    else 0.0
                ),
                result_publish_fps=(
                    self.result_publisher_service.status_fps(pipeline_camera_id)
                    if self.result_publisher_service is not None
                    else 0.0
                ),
                latest_detection_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_detection.monotonic_at if snapshot.latest_detection else None
                ),
                latest_fall_hint_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_fall_detection.monotonic_at if snapshot.latest_fall_detection else None
                ),
                latest_tracking_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_tracking.monotonic_at if snapshot.latest_tracking else None
                ),
                latest_pose_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_pose.monotonic_at if snapshot.latest_pose else None
                ),
                latest_temporal_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_temporal.monotonic_at if snapshot.latest_temporal else None
                ),
                latest_fused_age_ms=self.realtime_store.age_ms(
                    snapshot.latest_fused_result.detector.get("_monotonic_at")
                    if snapshot.latest_fused_result is not None
                    and isinstance(snapshot.latest_fused_result.detector, dict)
                    else None
                ),
                detection_to_publish_lag_ms=(
                    self.result_publisher_service.detection_to_publish_lag_ms(pipeline_camera_id)
                    if self.result_publisher_service is not None
                    else None
                ),
                fusion_confirmed_count=int(fusion_status.get("confirmed_count") or 0),
                fusion_candidate_count=int(fusion_status.get("candidate_count") or 0),
                fusion_suppressed_count=int(fusion_status.get("suppressed_count") or 0),
                fusion_latest_guard_reason=fusion_status.get("latest_guard_reason"),
                evidence_freshness=evidence_freshness,
                evidence_age_ms=evidence_age_ms,
                last_error=publisher_error or tracking_worker_error,
            )
            latest_result_status = self._latest_result_status(snapshot.latest_published_result)
            camera_status = self.source_manager.worker_status(pipeline_camera_id)
            latest_result_status = self._apply_camera_availability_guard(latest_result_status, camera_status)

        reporter_status = FallEventReporterStatus()
        polling_alert_status = PollingAlertStatus(camera_id=pipeline_camera_id)
        if self.fall_event_reporter is not None:
            reporter_status = FallEventReporterStatus(**self.fall_event_reporter.status())
            if pipeline_camera_id:
                polling_alert_status = PollingAlertStatus(
                    **self.fall_event_reporter.polling_alert(pipeline_camera_id)
                )

        main_stream = None
        analysis_stream = None
        diagnostics = DiagnosticsStatus()
        display_source_current = "single"
        display_source = "single"
        analysis_source = "single"
        display_fallback_active = False
        if runtimes:
            runtime = runtimes[0]
            worker_status = runtime.worker.status()
            alias = StreamRuntimeAlias(
                source_url_masked=mask_source_url(runtime.config.source_url),
                stream_state=worker_status.stream_state,
                connected=worker_status.connected,
                frame_age_ms=worker_status.frame_age_ms,
                frame_status=worker_status.frame_status,
                source_generation=worker_status.source_generation,
                is_stale=worker_status.is_stale,
                frame_width=worker_status.frame_width,
                frame_height=worker_status.frame_height,
                capture_fps=worker_status.capture_fps,
                source_protocol=worker_status.source_protocol,
                raw_jpeg_available=worker_status.raw_jpeg_available,
            )
            main_stream = alias
            analysis_stream = alias
            diagnostics = DiagnosticsStatus(
                camera_lost=worker_status.stream_state in {"disconnected", "reconnecting"} and not worker_status.connected,
                capture_stale=worker_status.stream_state in {"connecting", "connected", "delayed", "stale", "reconnecting", "unreachable"},
            )

        return VisionStatus(
            runtime_profile=self.settings.runtime_profile,
            cameras=cameras,
            detection=detections,
            streaming=StreamingStatus(
                webrtc_clients=self.peer_manager.client_count,
                ws_clients=self.result_channels.subscriber_count,
                webrtc_target_fps=self.settings.webrtc_video_fps,
            ),
            tracking=tracking_status,
            identity=identity_status,
            pose=pose_status,
            behavior=behavior_status,
            temporal=temporal_status,
            pipeline=pipeline_status,
            latest_result=latest_result_status,
            polling_alert=polling_alert_status,
            fall_event_reporter=reporter_status,
            main_stream=main_stream,
            analysis_stream=analysis_stream,
            display_source_current=display_source_current,
            display_source=display_source,
            analysis_source=analysis_source,
            display_fallback_active=display_fallback_active,
            diagnostics=diagnostics,
            workers=workers_status,
            configuration=ConfigurationStatus(**safe_configuration_snapshot(self.settings)),
        )

    def _latest_result_status(self, result) -> LatestResultStatus:
        if result is None:
            return LatestResultStatus()
        people = [item for item in result.objects if item.label == "person"]
        best = max(people, key=lambda item: item.confidence, default=None)
        if best is None:
            return LatestResultStatus(
                camera_id=result.camera_id,
                timestamp=result.timestamp,
                latest_objects_count=len(result.objects),
            )

        temporal = best.temporal or {}
        shadow = temporal.get("shadow") if isinstance(temporal.get("shadow"), dict) else {}
        fall_decision = best.fall_decision or {}
        alarm_preview = best.alarm_preview or {}
        incident_id = None
        snapshot_url = None
        snapshot_path = None
        metadata = {}
        if isinstance(temporal, dict):
            metadata = temporal.get("event_metadata") if isinstance(temporal.get("event_metadata"), dict) else {}
        if isinstance(metadata, dict):
            incident_id = metadata.get("incident_id")
            snapshot_url = metadata.get("snapshot_url")
            snapshot_path = metadata.get("snapshot_path")
        if self.fall_event_reporter is not None and (incident_id is None or snapshot_url is None or snapshot_path is None):
            latest_alert = self.fall_event_reporter.latest_alert(result.camera_id) or {}
            incident_id = incident_id or latest_alert.get("incident_id")
            snapshot_url = snapshot_url or latest_alert.get("snapshot_url")
            snapshot_path = snapshot_path or latest_alert.get("snapshot_path")
        fall_prob = StatusService._best_fall_probability(best, temporal, shadow)
        pose_debug = (best.pose or {}).get("debug", {}) if isinstance(best.pose, dict) else {}
        detector_debug = result.detector or {}
        normalized_state = str(fall_decision.get("fall_state") or "")
        alarm_confirmed = bool(alarm_preview.get("confirmed"))
        pose_available = pose_has_visible_keypoints(best.pose if isinstance(best.pose, dict) else None)
        return LatestResultStatus(
            camera_id=result.camera_id,
            timestamp=result.timestamp,
            latest_objects_count=len(result.objects),
            latest_person_confidence=best.confidence,
            latest_bbox=[float(value) for value in best.bbox],
            track_id=best.track_id,
            pose_available=pose_available,
            temporal_window_size=temporal.get("window_size"),
            temporal_source=temporal.get("source"),
            temporal_shadow_fall_probability=shadow.get("fall_probability") if isinstance(shadow, dict) else None,
            fall_state=normalized_state or "normal",
            alarm_confirmed=alarm_confirmed,
            risk_level=alarm_preview.get("risk_level") or fall_decision.get("risk_level"),
            fall_prob=fall_prob,
            fall_score=fall_prob,
            incident_id=incident_id,
            snapshot_url=snapshot_url,
            snapshot_path=snapshot_path,
            fall_candidate_source=fall_decision.get("source") or alarm_preview.get("source"),
            fall_suppressed_reason=(
                alarm_preview.get("suppressed_reason")
                or fall_decision.get("suppressed_reason")
                or alarm_preview.get("debug_reason")
                or fall_decision.get("debug_reason")
            ),
            confidence_level=confidence_level(
                fall_state=normalized_state,
                fall_probability=fall_prob,
                safe_to_interpret_as_no_fall=True,
            ),
            degraded_by=degraded_by_from_payload(
                pose_available=pose_available,
                pose_debug=pose_debug,
                detector_debug=detector_debug,
            ),
            detector_debug=detector_debug,
            pose_debug=pose_debug,
            temporal_debug=temporal,
        )

    def _apply_camera_availability_guard(self, status: LatestResultStatus, camera_status) -> LatestResultStatus:
        if camera_status is None:
            payload = unavailable_result("camera_disabled", camera_id=status.camera_id)
            return status.model_copy(update={
                "fall_state": payload["fall_state"],
                "reason": payload["reason"],
                "safe_to_interpret_as_no_fall": payload["safe_to_interpret_as_no_fall"],
                "camera_stream_state": "disabled",
                "frame_status": "no_frame",
                "confidence_level": "unavailable",
                "degraded_by": ["camera_disabled"],
            })
        frame_status = getattr(camera_status, "frame_status", "no_frame")
        stream_state = getattr(camera_status, "stream_state", None)
        reason = camera_unavailable_reason(camera_status)
        updates = {
            "camera_stream_state": stream_state,
            "frame_status": frame_status,
            "source_generation": getattr(camera_status, "source_generation", None),
            "safe_to_interpret_as_no_fall": True,
        }
        if reason:
            payload = unavailable_result(reason, camera_id=status.camera_id or getattr(camera_status, "camera_id", None))
            updates.update({
                "camera_id": status.camera_id or payload["camera_id"],
                "fall_state": payload["fall_state"],
                "reason": payload["reason"],
                "safe_to_interpret_as_no_fall": payload["safe_to_interpret_as_no_fall"],
                "alarm_confirmed": False,
                "risk_level": None,
                "fall_prob": None,
                "fall_score": None,
                "confidence_level": "unavailable",
                "degraded_by": list(dict.fromkeys([*status.degraded_by, reason])),
            })
        return status.model_copy(update=updates)

    @staticmethod
    def _best_fall_probability(best, temporal: dict, shadow: dict) -> float | None:
        candidates = [
            temporal.get("fall_probability"),
            shadow.get("fall_probability") if isinstance(shadow, dict) else None,
            (best.fall_decision or {}).get("fall_probability"),
            (best.alarm_preview or {}).get("fall_probability"),
        ]
        values: list[float] = []
        for candidate in candidates:
            try:
                if candidate is not None:
                    values.append(max(0.0, min(1.0, float(candidate))))
            except (TypeError, ValueError):
                continue
        return max(values) if values else None
