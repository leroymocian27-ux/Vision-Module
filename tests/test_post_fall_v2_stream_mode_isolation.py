from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.core.config import Settings
from app.services.stream_service import StreamService


class _SourceManager:
    def __init__(self) -> None:
        self.runtime = None
        self.started = False
        self.stopped = False

    def get_runtime(self, camera_id):
        return self.runtime

    def start_source(self, config):
        self.started = True
        self.runtime = SimpleNamespace(config=config)
        return self.runtime, True

    def stop_source(self, camera_id):
        self.stopped = True
        self.runtime = None
        return True


class _Service:
    def __init__(self) -> None:
        self.started = []
        self.stopped = []

    def start_for_camera(self, camera_id):
        self.started.append(camera_id)

    def stop_for_camera(self, camera_id):
        self.stopped.append(camera_id)


class _RealtimeStore:
    def clear_camera(self, camera_id):
        pass


def test_post_fall_v2_stream_starts_binary_runtime_not_legacy_detection() -> None:
    settings = replace(Settings(), pipeline_mode="post_fall_v2", post_fall_v2_enabled=True)
    source_manager = _SourceManager()
    detection = _Service()
    post_fall = _Service()
    publisher = _Service()

    service = StreamService(
        settings=settings,
        source_manager=source_manager,
        detection_service=detection,
        realtime_store=_RealtimeStore(),
        tracking_service=SimpleNamespace(reset=lambda camera_id: None),
        identity_binding_service=SimpleNamespace(reset_camera=lambda camera_id: None),
        temporal_service=SimpleNamespace(reset_camera=lambda camera_id: None),
        tracking_worker_service=_Service(),
        identity_binding_worker_service=_Service(),
        pose_worker_service=_Service(),
        result_publisher_service=publisher,
        post_fall_v2_runtime_service=post_fall,
    )

    started, message = service.start("camera_01", "mock://colorbars")

    assert started is True
    assert message == "stream started"
    assert post_fall.started == ["camera_01"]
    assert detection.started == []
    assert publisher.started == []
