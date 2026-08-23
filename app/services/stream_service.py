from __future__ import annotations

from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import CameraSourceConfig, mask_source_url
from app.core.config import Settings
from app.core.logger import get_logger
from app.services.detection_service import DetectionService
from app.services.fall_hint_worker_service import FallHintWorkerService
from app.services.identity_binding_worker_service import IdentityBindingWorkerService
from app.services.identity_binding_service import IdentityBindingService
from app.services.pose_worker_service import PoseWorkerService
from app.services.result_publisher_service import ResultPublisherService
from app.services.temporal_service import TemporalService
from app.services.temporal_worker_service import TemporalWorkerService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService
from app.detection.realtime_result_store import RealtimeResultStore
from app.fall.fusion import FallFusionService
from app.post_fall_v2.fall_binary_shadow_service import FallBinaryShadowService
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService

logger = get_logger(__name__)


class StreamService:
    def __init__(
        self,
        settings: Settings,
        source_manager: CameraSourceManager,
        detection_service: DetectionService,
        realtime_store: RealtimeResultStore,
        tracking_service: TrackingService,
        identity_binding_service: IdentityBindingService,
        temporal_service: TemporalService,
        tracking_worker_service: TrackingWorkerService,
        identity_binding_worker_service: IdentityBindingWorkerService,
        pose_worker_service: PoseWorkerService,
        result_publisher_service: ResultPublisherService,
        fall_fusion_service: FallFusionService | None = None,
        fall_hint_worker_service: FallHintWorkerService | None = None,
        temporal_worker_service: TemporalWorkerService | None = None,
        fusion_worker_service: FusionWorkerService | None = None,
        post_fall_v2_shadow_service: FallBinaryShadowService | None = None,
        post_fall_v2_runtime_service: PostFallV2RuntimeService | None = None,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.detection_service = detection_service
        self.realtime_store = realtime_store
        self.tracking_service = tracking_service
        self.fall_hint_worker_service = fall_hint_worker_service
        self.identity_binding_service = identity_binding_service
        self.temporal_service = temporal_service
        self.temporal_worker_service = temporal_worker_service
        self.fusion_worker_service = fusion_worker_service
        self.post_fall_v2_shadow_service = post_fall_v2_shadow_service
        self.post_fall_v2_runtime_service = post_fall_v2_runtime_service
        self.fall_fusion_service = fall_fusion_service
        self.tracking_worker_service = tracking_worker_service
        self.identity_binding_worker_service = identity_binding_worker_service
        self.pose_worker_service = pose_worker_service
        self.result_publisher_service = result_publisher_service

    def start(
        self,
        camera_id: str,
        source_url: str | None,
        *,
        main_source_url: str | None = None,
        analysis_source_url: str | None = None,
    ) -> tuple[bool, str]:
        selected_url, provided_urls = self._select_authoritative_source_url(
            source_url=source_url,
            main_source_url=main_source_url,
            analysis_source_url=analysis_source_url,
        )
        if len(set(provided_urls.values())) > 1:
            logger.warning(
                "single_source_stream_conflict camera_id=%s provided=%s using=%s",
                camera_id,
                {name: mask_source_url(url) for name, url in provided_urls.items()},
                mask_source_url(selected_url),
            )
        resolved_url = self._resolve_source_url(selected_url)
        existing = self.source_manager.get_runtime(camera_id)
        if existing is not None:
            if existing.config.source_url == resolved_url:
                return False, "stream already running"
            self.stop(camera_id)
        self._reset_camera_state(camera_id)
        runtime, created = self.source_manager.start_source(
            CameraSourceConfig(camera_id=camera_id, source_url=resolved_url)
        )
        if self.settings.pipeline_mode == "post_fall_v2":
            if self.post_fall_v2_runtime_service is not None:
                self.post_fall_v2_runtime_service.start_for_camera(runtime.config.camera_id)
            if existing is not None:
                return True, "stream restarted"
            if created:
                return True, "stream started"
            return False, "stream already running"

        self.detection_service.start_for_camera(runtime.config.camera_id)
        if self.fall_hint_worker_service is not None:
            self.fall_hint_worker_service.start_for_camera(runtime.config.camera_id)
        self.tracking_worker_service.start_for_camera(runtime.config.camera_id)
        self.identity_binding_worker_service.start_for_camera(runtime.config.camera_id)
        self.pose_worker_service.start_for_camera(runtime.config.camera_id)
        if self.temporal_worker_service is not None:
            self.temporal_worker_service.start_for_camera(runtime.config.camera_id)
        if self.fusion_worker_service is not None:
            self.fusion_worker_service.start_for_camera(runtime.config.camera_id)
        if self.post_fall_v2_shadow_service is not None:
            self.post_fall_v2_shadow_service.start_for_camera(runtime.config.camera_id)
        self.result_publisher_service.start_for_camera(runtime.config.camera_id)
        if existing is not None:
            return True, "stream restarted"
        if created:
            return True, "stream started"
        return False, "stream already running"

    def stop(self, camera_id: str) -> bool:
        self.result_publisher_service.stop_for_camera(camera_id)
        if self.post_fall_v2_runtime_service is not None:
            self.post_fall_v2_runtime_service.stop_for_camera(camera_id)
        if self.fusion_worker_service is not None:
            self.fusion_worker_service.stop_for_camera(camera_id)
        if self.post_fall_v2_shadow_service is not None:
            self.post_fall_v2_shadow_service.stop_for_camera(camera_id)
        if self.temporal_worker_service is not None:
            self.temporal_worker_service.stop_for_camera(camera_id)
        self.pose_worker_service.stop_for_camera(camera_id)
        self.identity_binding_worker_service.stop_for_camera(camera_id)
        self.tracking_worker_service.stop_for_camera(camera_id)
        if self.fall_hint_worker_service is not None:
            self.fall_hint_worker_service.stop_for_camera(camera_id)
        self.detection_service.stop_for_camera(camera_id)
        return self.source_manager.stop_source(camera_id)

    def _reset_camera_state(self, camera_id: str) -> None:
        self.tracking_service.reset(camera_id)
        self.identity_binding_service.reset_camera(camera_id)
        self.temporal_service.reset_camera(camera_id)
        if self.temporal_worker_service is not None:
            self.temporal_worker_service.clear_camera(camera_id)
        if self.fusion_worker_service is not None:
            self.fusion_worker_service.clear_camera(camera_id)
        if self.fall_fusion_service is not None:
            self.fall_fusion_service.reset_camera(camera_id)
        if self.fall_hint_worker_service is not None:
            self.fall_hint_worker_service.clear_camera(camera_id)
        self.realtime_store.clear_camera(camera_id)
        if self.post_fall_v2_runtime_service is not None:
            self.post_fall_v2_runtime_service.stop_for_camera(camera_id)

    def _resolve_source_url(self, source_url: str | None) -> str:
        if source_url:
            return source_url
        if self.settings.default_rtsp_url:
            return self.settings.default_rtsp_url
        if self.settings.mock_camera_enabled:
            return "mock://colorbars"
        raise ValueError("rtsp_url is required when mock camera is disabled")

    @staticmethod
    def _select_authoritative_source_url(
        *,
        source_url: str | None,
        main_source_url: str | None,
        analysis_source_url: str | None,
    ) -> tuple[str | None, dict[str, str]]:
        normalized = {
            "rtsp_url": StreamService._normalize_url(source_url),
            "main_rtsp_url": StreamService._normalize_url(main_source_url),
            "analysis_rtsp_url": StreamService._normalize_url(analysis_source_url),
        }
        provided = {name: value for name, value in normalized.items() if value}
        selected = (
            provided.get("rtsp_url")
            or provided.get("analysis_rtsp_url")
            or provided.get("main_rtsp_url")
        )
        return selected, provided

    @staticmethod
    def _normalize_url(source_url: str | None) -> str | None:
        if source_url is None:
            return None
        stripped = source_url.strip()
        return stripped or None
