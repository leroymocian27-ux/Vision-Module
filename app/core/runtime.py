from __future__ import annotations

from dataclasses import dataclass

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.events.pipeline import EventPipelineService
from app.events.delivery_worker import DeliveryWorker
from app.detection.realtime_result_store import RealtimeResultStore
from app.detection.result_store import ResultStore
from app.services.alert_simulator_service import AlertSimulatorService
from app.services.detection_service import DetectionService
from app.services.behavior_service import BehaviorService
from app.services.identity_binding_service import IdentityBindingService
from app.services.identity_binding_worker_service import IdentityBindingWorkerService
from app.services.identity_service import IdentityService
from app.services.fall_event_reporter_service import FallEventReporterService
from app.services.fall_hint_worker_service import FallHintWorkerService
from app.services.pose_service import PoseService
from app.services.pose_worker_service import PoseWorkerService
from app.services.result_publisher_service import ResultPublisherService
from app.services.status_service import StatusService
from app.services.stream_service import StreamService
from app.services.temporal_service import TemporalService
from app.services.temporal_worker_service import TemporalWorkerService
from app.services.tracking_service import TrackingService
from app.services.tracking_worker_service import TrackingWorkerService
from app.services.fusion_worker_service import FusionWorkerService
from app.services.device_connection_service import DeviceConnectionService
from app.fall.fusion import FallFusionService
from app.post_fall_v2.fall_binary_shadow_service import FallBinaryShadowService
from app.post_fall_v2.follow_target import FollowTargetReceiver
from app.post_fall_v2.post_fall_runtime_service import PostFallV2RuntimeService
from app.post_fall_v2.test_archive_service import PostFallTestArchiveService
from app.streaming.peer_manager import PeerManager
from app.streaming.result_channel_manager import ResultChannelManager


@dataclass
class Runtime:
    settings: Settings
    source_manager: CameraSourceManager
    realtime_store: RealtimeResultStore
    result_store: ResultStore
    result_channels: ResultChannelManager
    tracking_service: TrackingService
    identity_service: IdentityService
    identity_binding_service: IdentityBindingService
    identity_binding_worker_service: IdentityBindingWorkerService
    pose_service: PoseService
    behavior_service: BehaviorService
    temporal_service: TemporalService
    fall_event_reporter: FallEventReporterService
    alert_simulator_service: AlertSimulatorService
    detection_service: DetectionService
    tracking_worker_service: TrackingWorkerService
    pose_worker_service: PoseWorkerService
    result_publisher_service: ResultPublisherService
    stream_service: StreamService
    peer_manager: PeerManager
    status_service: StatusService
    device_connection_service: DeviceConnectionService | None = None
    event_pipeline: EventPipelineService | None = None
    event_delivery_worker: DeliveryWorker | None = None
    fall_fusion_service: FallFusionService | None = None
    fall_hint_worker_service: FallHintWorkerService | None = None
    temporal_worker_service: TemporalWorkerService | None = None
    fusion_worker_service: FusionWorkerService | None = None
    post_fall_v2_shadow_service: FallBinaryShadowService | None = None
    post_fall_v2_runtime_service: PostFallV2RuntimeService | None = None
    follow_target_receiver: FollowTargetReceiver | None = None
    post_fall_test_archive_service: PostFallTestArchiveService | None = None

    async def shutdown(self) -> None:
        if self.event_delivery_worker is not None:
            self.event_delivery_worker.stop()
        if self.event_pipeline is not None:
            self.event_pipeline.stop()
        if self.post_fall_v2_shadow_service is not None:
            self.post_fall_v2_shadow_service.stop_all()
        if self.post_fall_v2_runtime_service is not None:
            self.post_fall_v2_runtime_service.stop_all()
        if self.follow_target_receiver is not None:
            self.follow_target_receiver.stop()
        self.result_publisher_service.stop_all()
        if self.fusion_worker_service is not None:
            self.fusion_worker_service.stop_all()
        self.alert_simulator_service.stop()
        self.fall_event_reporter.stop()
        self.pose_worker_service.stop_all()
        if self.temporal_worker_service is not None:
            self.temporal_worker_service.stop_all()
        self.identity_binding_worker_service.stop_all()
        self.tracking_worker_service.stop_all()
        if self.fall_hint_worker_service is not None:
            self.fall_hint_worker_service.stop_all()
        self.detection_service.stop_all()
        self.source_manager.stop_all()
        await self.peer_manager.close_all()
