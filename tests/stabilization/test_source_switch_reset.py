from app.services.stream_service import StreamService


class _Resettable:
    def __init__(self):
        self.calls = []

    def reset(self, camera_id):
        self.calls.append(("reset", camera_id))

    def reset_camera(self, camera_id):
        self.calls.append(("reset_camera", camera_id))

    def clear_camera(self, camera_id):
        self.calls.append(("clear_camera", camera_id))


def test_source_switch_reset_clears_state_slots():
    tracking = _Resettable()
    identity = _Resettable()
    temporal = _Resettable()
    temporal_worker = _Resettable()
    fusion_worker = _Resettable()
    fall_fusion = _Resettable()
    fall_hint = _Resettable()
    realtime_store = _Resettable()

    service = StreamService(
        settings=object(),
        source_manager=object(),
        detection_service=object(),
        realtime_store=realtime_store,
        tracking_service=tracking,
        identity_binding_service=identity,
        temporal_service=temporal,
        tracking_worker_service=object(),
        identity_binding_worker_service=object(),
        pose_worker_service=object(),
        result_publisher_service=object(),
        fall_fusion_service=fall_fusion,
        fall_hint_worker_service=fall_hint,
        temporal_worker_service=temporal_worker,
        fusion_worker_service=fusion_worker,
    )

    service._reset_camera_state("camera_01")

    assert ("reset", "camera_01") in tracking.calls
    assert ("reset_camera", "camera_01") in identity.calls
    assert ("reset_camera", "camera_01") in temporal.calls
    assert ("clear_camera", "camera_01") in temporal_worker.calls
    assert ("clear_camera", "camera_01") in fusion_worker.calls
    assert ("reset_camera", "camera_01") in fall_fusion.calls
    assert ("clear_camera", "camera_01") in fall_hint.calls
    assert ("clear_camera", "camera_01") in realtime_store.calls
