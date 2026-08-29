from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np

from app.api.rest_api import latest_stream_frame
from app.camera.frame_buffer import FrameBuffer
from app.camera.mjpeg_parser import extract_jpeg_frames, jpeg_dimensions
from app.camera.mjpeg_stream_worker import MJPEGStreamWorker
from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import CameraSourceConfig, is_mjpeg_source
from app.core.config import Settings


def _jpeg(width: int = 32, height: int = 16) -> bytes:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    assert ok
    return encoded.tobytes()


def test_mjpeg_parser_extracts_split_and_multiple_frames() -> None:
    first = _jpeg(32, 16)
    second = _jpeg(24, 12)
    frames, remaining = extract_jpeg_frames(b"junk" + first[:11])
    assert frames == []
    frames, remaining = extract_jpeg_frames(remaining + first[11:] + second)
    assert frames == [first, second]
    assert remaining == b""
    assert jpeg_dimensions(first) == (32, 16)


def test_frame_buffer_keeps_raw_jpeg_for_latest_frame_response() -> None:
    jpeg = _jpeg(40, 20)
    buffer = FrameBuffer("camera_01", source="mjpeg", source_generation=2)
    packet = buffer.update_jpeg(jpeg, width=40, height=20)

    response = latest_stream_frame(
        camera_id="camera_01",
        runtime=SimpleNamespace(
            source_manager=SimpleNamespace(
                get_buffer=lambda camera_id: buffer,
                worker_status=lambda camera_id: None,
            ),
            settings=SimpleNamespace(frame_delayed_threshold_ms=1000, stream_stale_threshold_ms=3000),
        ),
    )

    assert packet.width == 40
    assert packet.height == 20
    assert response.body == jpeg
    assert response.headers["X-Raw-Jpeg-Reused"] == "true"
    assert response.headers["X-Source-Protocol"] == "mjpeg"


def test_source_manager_uses_native_mjpeg_worker_even_with_subprocess_backend() -> None:
    settings = replace(
        Settings(),
        capture_backend="subprocess_pyav",
        mock_camera_enabled=False,
    )
    manager = CameraSourceManager(settings)
    buffer = FrameBuffer("go2_front_camera", source="mjpeg")
    worker = manager._create_worker(  # type: ignore[attr-defined]
        CameraSourceConfig("go2_front_camera", "http://192.168.8.254:8093/stream.mjpg"),
        buffer,
    )

    assert is_mjpeg_source("http://192.168.8.254:8093/stream.mjpg")
    assert isinstance(worker, MJPEGStreamWorker)
