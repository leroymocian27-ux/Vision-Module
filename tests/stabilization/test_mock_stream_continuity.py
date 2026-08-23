import time

from app.camera.capture_worker import CaptureWorker
from app.camera.frame_buffer import FrameBuffer
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings


def test_mock_stream_produces_increasing_generation_and_frames():
    settings = Settings(mock_camera_width=64, mock_camera_height=48, mock_camera_fps=10)
    buffer = FrameBuffer("camera_01", source="mock", source_generation=7)
    worker = CaptureWorker(CameraSourceConfig("camera_01", "mock://colorbars"), buffer, settings)
    worker.start()
    try:
        time.sleep(0.25)
        first = buffer.latest()
        time.sleep(0.2)
        second = buffer.latest()
        assert first is not None
        assert second is not None
        assert second.seq > first.seq
        assert second.source == "mock"
        assert second.source_generation == 7
        assert worker.status().stream_state == "streaming"
    finally:
        worker.stop()
