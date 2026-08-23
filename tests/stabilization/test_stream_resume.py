import time

from app.camera.capture_worker import CaptureWorker
from app.camera.frame_buffer import FrameBuffer
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings


def test_mock_resume_recovers_streaming_after_pause():
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
        worker.set_mock_fault("pause")
        time.sleep(0.35)
        assert worker.status().stream_state == "stale"
        worker.set_mock_fault("resume")
        time.sleep(0.2)
        status = worker.status()
        assert status.frame_status == "fresh"
        assert status.stream_state == "streaming"
    finally:
        worker.stop()
