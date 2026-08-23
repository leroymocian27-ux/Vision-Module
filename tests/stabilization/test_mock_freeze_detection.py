import time

from app.camera.capture_worker import CaptureWorker
from app.camera.frame_buffer import FrameBuffer
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings


def test_mock_freeze_keeps_frame_seq_and_becomes_stale():
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
        first = buffer.latest()
        assert first is not None
        worker.set_mock_fault("freeze")
        time.sleep(0.35)
        frozen = buffer.latest()
        assert frozen is not None
        assert frozen.seq == first.seq
        assert worker.status().frame_status == "stale"
    finally:
        worker.stop()
