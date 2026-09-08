from __future__ import annotations

import time

import numpy as np

from app.post_fall_v2.keyframe_collection_session import KeyframeCollectionSession
from app.post_fall_v2.schemas import BufferedFrame


def test_future_offsets_remain_collecting_until_real_future_frames_arrive() -> None:
    session = KeyframeCollectionSession(
        incident_id="incident-1",
        camera_id="camera_01",
        confirmed_monotonic=100.0,
        required_offsets_ms=(-3000, -1000, 0, 1000, 3000, 5000),
        tolerance_ms=100,
        collection_window_seconds=10,
    )
    for seq, offset_ms in enumerate((-3000, -1000, 0), start=1):
        session.observe_buffered_frame(_frame(seq, 100.0 + offset_ms / 1000.0))

    package = session.build_package(now_monotonic=100.0)

    assert package.status == "collecting"
    assert package.resolved_offsets_ms == [-3000, -1000, 0]
    assert package.missing_offsets_ms == [1000, 3000, 5000]
    assert [item.frame_seq for item in package.frames if item.frame_seq] == [1, 2, 3]


def test_short_post_frame_is_not_filled_before_target_time_even_with_wide_tolerance() -> None:
    session = KeyframeCollectionSession(
        incident_id="incident-short-post",
        camera_id="camera_01",
        confirmed_monotonic=10.0,
        required_offsets_ms=(-800, 0, 400),
        tolerance_ms=750,
        collection_window_seconds=2,
    )
    for seq, offset_ms in enumerate((-800, -300, 0), start=1):
        session.observe_buffered_frame(_frame(seq, 10.0 + offset_ms / 1000.0))

    package = session.build_package(now_monotonic=10.2)

    assert package.status == "collecting"
    assert package.resolved_offsets_ms == [-800, 0]
    assert package.missing_offsets_ms == [400]


def test_session_becomes_ready_when_all_future_offsets_have_distinct_frames() -> None:
    session = KeyframeCollectionSession(
        incident_id="incident-2",
        camera_id="camera_01",
        confirmed_monotonic=50.0,
        required_offsets_ms=(-3000, -1000, 0, 1000, 3000, 5000),
        tolerance_ms=100,
        collection_window_seconds=10,
    )
    for seq, offset_ms in enumerate((-3000, -1000, 0, 1000, 3000, 5000), start=1):
        session.observe_buffered_frame(_frame(seq, 50.0 + offset_ms / 1000.0))

    package = session.build_package(now_monotonic=55.0)
    images, missing = session.export_qwen_images(max_images=6, max_image_bytes=1024 * 1024, now_monotonic=55.0)

    assert package.status == "ready"
    assert package.missing_offsets_ms == []
    assert [item.actual_offset_ms for item in package.frames] == [-3000, -1000, 0, 1000, 3000, 5000]
    assert len({item.frame_seq for item in package.frames}) == 6
    assert len(images) == 6
    assert missing == []


def test_deadline_degrades_when_future_frame_is_missing() -> None:
    session = KeyframeCollectionSession(
        incident_id="incident-3",
        camera_id="camera_01",
        confirmed_monotonic=20.0,
        required_offsets_ms=(0, 1000, 3000),
        tolerance_ms=100,
        collection_window_seconds=0.1,
    )
    session.observe_buffered_frame(_frame(1, 20.0))
    session.observe_buffered_frame(_frame(2, 21.0))
    time.sleep(0.12)

    package = session.build_package()

    assert package.status == "degraded"
    assert package.resolved_offsets_ms == [0, 1000]
    assert package.missing_offsets_ms == [3000]


def test_duplicate_frame_is_not_used_for_multiple_offsets() -> None:
    session = KeyframeCollectionSession(
        incident_id="incident-4",
        camera_id="camera_01",
        confirmed_monotonic=10.0,
        required_offsets_ms=(0, 100),
        tolerance_ms=200,
        collection_window_seconds=0.1,
    )
    session.observe_buffered_frame(_frame(1, 10.0))
    time.sleep(0.12)

    package = session.build_package()

    assert package.status == "degraded"
    assert package.resolved_offsets_ms == [0]
    assert package.missing_offsets_ms == [100]


def _frame(seq: int, monotonic_at: float) -> BufferedFrame:
    return BufferedFrame(
        camera_id="camera_01",
        frame_id=f"camera_01_1_{seq:08d}",
        frame_seq=seq,
        timestamp="2026-08-13T00:00:00.000+00:00",
        monotonic_at=monotonic_at,
        source_width=32,
        source_height=24,
        frame=np.full((24, 32, 3), seq, dtype=np.uint8),
    )
