import time

from app.camera.capture_worker import CaptureWorker
from app.camera.frame_buffer import FrameBuffer
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings


def test_mock_pause_transitions_to_stale():
    settings = Settings(
        mock_camera_width=64,
        mock_camera_height=48,
        mock_camera_fps=20,
        frame_delayed_threshold_ms=100,
        stream_stale_threshold_ms=250,
    )
    buffer = FrameBuffer("camera_01", source="mock", source_generation=1)
    worker = CaptureWorker(CameraSourceConfig("camera_01", "mock://colorbars"), buffer, settings)
    worker.start()
    try:
        time.sleep(0.2)
        assert buffer.latest() is not None
        worker.set_mock_fault("pause")
        time.sleep(0.35)
        status = worker.status()
        assert status.frame_status == "stale"
        assert status.stream_state == "stale"
        assert status.safe_to_interpret_as_no_fall is False
    finally:
        worker.stop()
