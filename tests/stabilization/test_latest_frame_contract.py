import numpy as np
import pytest
from fastapi import HTTPException

from app.api.rest_api import latest_stream_frame
from app.camera.frame_buffer import FrameBuffer


class _Settings:
    frame_delayed_threshold_ms = 1000
    stream_stale_threshold_ms = 3000


class _SourceManager:
    def __init__(self, buffer):
        self._buffer = buffer

    def get_buffer(self, camera_id):
        return self._buffer

    def worker_status(self, camera_id):
        return None


class _Runtime:
    def __init__(self, buffer):
        self.source_manager = _SourceManager(buffer)
        self.settings = _Settings()


def test_latest_frame_headers_include_s3_metadata():
    buffer = FrameBuffer("camera_01", source="mock", source_generation=3)
    buffer.update(np.zeros((16, 16, 3), dtype=np.uint8))

    response = latest_stream_frame(camera_id="camera_01", runtime=_Runtime(buffer))

    assert response.headers["X-Camera-Id"] == "camera_01"
    assert response.headers["X-Frame-Id"] == "1"
    assert response.headers["X-Frame-Status"] == "fresh"
    assert response.headers["X-Source-Generation"] == "3"


def test_latest_frame_no_frame_is_structured_404():
    with pytest.raises(HTTPException) as exc:
        latest_stream_frame(camera_id="camera_01", runtime=_Runtime(FrameBuffer("camera_01")))

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "LATEST_FRAME_NOT_AVAILABLE"
    assert exc.value.detail["safe_to_interpret_as_no_fall"] is False
