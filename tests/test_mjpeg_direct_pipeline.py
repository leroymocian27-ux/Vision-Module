from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import time

import cv2
import numpy as np
import pytest

from app.api.rest_api import latest_stream_frame
from app.camera.frame_buffer import FrameBuffer
from app.camera.mjpeg_parser import extract_jpeg_frames, jpeg_dimensions
from app.camera.mjpeg_stream_worker import MJPEGStreamWorker
from app.camera.source_manager import CameraSourceManager
from app.camera.source_models import CameraSourceConfig, is_mjpeg_source
from app.core.config import Settings
from app.streaming.display_frame_cache import get_display_frame_cache


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


def test_latest_frame_display_mode_resizes_without_reusing_raw_jpeg() -> None:
    get_display_frame_cache().reset("camera_01")
    jpeg = _jpeg(128, 72)
    buffer = FrameBuffer("camera_01", source="mjpeg", source_generation=2)
    buffer.update_jpeg(jpeg, width=128, height=72)

    response = latest_stream_frame(
        camera_id="camera_01",
        display=True,
        runtime=SimpleNamespace(
            source_manager=SimpleNamespace(
                get_buffer=lambda camera_id: buffer,
                worker_status=lambda camera_id: None,
            ),
            settings=SimpleNamespace(
                frame_delayed_threshold_ms=1000,
                stream_stale_threshold_ms=3000,
                display_frame_height=36,
                display_jpeg_quality=72,
            ),
        ),
    )

    assert response.body != jpeg
    assert response.headers["X-Display-Resized"] == "true"
    assert jpeg_dimensions(response.body) == (64, 36)
    assert response.headers["X-Display-Cache-Hit"] == "false"


def test_display_frame_cache_reuses_encoded_display_jpeg_for_same_frame() -> None:
    get_display_frame_cache().reset("camera_01")
    jpeg = _jpeg(128, 72)
    buffer = FrameBuffer("camera_01", source="mjpeg", source_generation=2)
    buffer.update_jpeg(jpeg, width=128, height=72)
    runtime = SimpleNamespace(
        source_manager=SimpleNamespace(
            get_buffer=lambda camera_id: buffer,
            worker_status=lambda camera_id: None,
        ),
        settings=SimpleNamespace(
            frame_delayed_threshold_ms=1000,
            stream_stale_threshold_ms=3000,
            display_frame_height=36,
            display_jpeg_quality=72,
        ),
    )

    first = latest_stream_frame(camera_id="camera_01", display=True, runtime=runtime)
    second = latest_stream_frame(camera_id="camera_01", display=True, runtime=runtime)
    status = get_display_frame_cache().status("camera_01")["cameras"]["camera_01"]

    assert first.body == second.body
    assert first.headers["X-Display-Cache-Hit"] == "false"
    assert second.headers["X-Display-Cache-Hit"] == "true"
    assert status["encoded_frames"] == 1
    assert status["cache_hits"] == 1


def test_display_frame_cache_separates_latest_frame_and_mjpeg_stream_serves() -> None:
    cache = get_display_frame_cache()
    cache.reset("camera_01")

    cache.mark_served("camera_01", consumer="latest_frame")
    cache.mark_served("camera_01", consumer="latest_frame")
    cache.mark_served("camera_01", consumer="display_mjpg")
    status = cache.status("camera_01")["cameras"]["camera_01"]

    assert status["served_frames"] == 3
    assert status["latest_frame_served_frames"] == 2
    assert status["display_mjpeg_served_frames"] == 1


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


def test_mjpeg_worker_keeps_latest_compressed_frame_only() -> None:
    settings = Settings()
    buffer = FrameBuffer("go2_front_camera", source="mjpeg")
    worker = MJPEGStreamWorker(
        CameraSourceConfig("go2_front_camera", "http://example.test/stream.mjpg"),
        buffer,
        settings,
    )
    first = _jpeg(32, 16)
    second = _jpeg(48, 24)

    worker._queue_jpeg(first)  # noqa: SLF001 - verifies latest-only queue behavior
    worker._queue_jpeg(second)  # noqa: SLF001
    queued = worker._pop_latest_jpeg()  # noqa: SLF001

    assert queued is not None
    assert queued[1] == second
    status = worker.status()
    assert status.mjpeg_received_frames == 2
    assert status.mjpeg_dropped_frames == 1
    assert status.capture_ipc_dropped_frames == 1


def test_mjpeg_worker_publishes_receive_timestamp_as_frame_age_origin() -> None:
    settings = Settings()
    buffer = FrameBuffer("go2_front_camera", source="mjpeg")
    worker = MJPEGStreamWorker(
        CameraSourceConfig("go2_front_camera", "http://example.test/stream.mjpg"),
        buffer,
        settings,
    )
    received_at = 123.456

    worker._publish_jpeg(_jpeg(40, 20), received_at=received_at)  # noqa: SLF001

    packet = buffer.latest()
    assert packet is not None
    assert packet.captured_at == received_at
    assert packet.received_at == received_at
    status = worker.status()
    assert status.mjpeg_published_frames == 1
    assert status.mjpeg_publish_latency_ms is not None


def test_mjpeg_worker_reconnects_when_no_complete_jpeg_arrives_after_stale_threshold() -> None:
    settings = replace(Settings(), mjpeg_stale_frame_ms=1, mjpeg_read_timeout_sec=0.001)
    buffer = FrameBuffer("go2_front_camera", source="mjpeg")
    worker = MJPEGStreamWorker(
        CameraSourceConfig("go2_front_camera", "http://example.test/stream.mjpg"),
        buffer,
        settings,
    )

    with pytest.raises(TimeoutError, match="complete frame stale"):
        worker._raise_if_complete_frame_stale(time.monotonic() - 1.0)  # noqa: SLF001

    assert worker._status.stale_count == 1  # noqa: SLF001
    assert worker._status.read_timeout_count == 1  # noqa: SLF001
    assert worker._status.reconnect_reason == "mjpeg_complete_frame_stale"  # noqa: SLF001


def test_mjpeg_worker_does_not_reconnect_before_read_timeout_window() -> None:
    settings = replace(Settings(), mjpeg_stale_frame_ms=1, mjpeg_read_timeout_sec=2.0)
    buffer = FrameBuffer("go2_front_camera", source="mjpeg")
    worker = MJPEGStreamWorker(
        CameraSourceConfig("go2_front_camera", "http://example.test/stream.mjpg"),
        buffer,
        settings,
    )

    worker._raise_if_complete_frame_stale(time.monotonic() - 1.0)  # noqa: SLF001

    assert worker._status.stale_count == 0  # noqa: SLF001
    assert worker._status.read_timeout_count == 0  # noqa: SLF001
