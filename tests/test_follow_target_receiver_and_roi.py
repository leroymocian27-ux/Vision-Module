from __future__ import annotations

import json
import socket
import time

import numpy as np

from app.post_fall_v2.follow_target import (
    FollowTargetReceiver,
    FollowTargetState,
    TargetRegionConfig,
    TargetRegionExtractor,
)


def test_target_roi_uses_bearing_full_height_and_width_ratio() -> None:
    extractor = TargetRegionExtractor(
        TargetRegionConfig(
            enabled=True,
            fresh_ms=300,
            grace_ms=700,
            camera_hfov_deg=90.0,
            camera_yaw_offset_deg=0.0,
            fresh_width_ratio=0.50,
            grace_width_ratio=0.70,
        )
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    state = FollowTargetState(
        sequence=1,
        target_valid=True,
        follow_active=True,
        bearing_deg=0.0,
        distance_m=2.0,
        received_monotonic=time.monotonic(),
    )

    result = extractor.extract(frame, state)

    assert result.tracking_state == "fresh"
    assert result.frame is not None
    assert result.frame.shape[:2] == (100, 100)
    assert result.target_binding["roi"] == [50, 0, 150, 100]
    assert result.target_binding["original_width"] == 200
    assert result.target_binding["original_height"] == 100


def test_target_roi_allows_fresh_valid_target_when_follow_inactive() -> None:
    extractor = TargetRegionExtractor(
        TargetRegionConfig(
            enabled=True,
            fresh_ms=300,
            grace_ms=700,
            camera_hfov_deg=90.0,
            camera_yaw_offset_deg=0.0,
            fresh_width_ratio=0.50,
            grace_width_ratio=0.70,
        )
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    state = FollowTargetState(
        sequence=10,
        target_valid=True,
        follow_active=False,
        bearing_deg=-15.0,
        distance_m=1.5,
        received_monotonic=time.monotonic(),
    )

    result = extractor.extract(frame, state)
    status = extractor.status_from_state(state)

    assert result.tracking_state == "fresh"
    assert result.frame is not None
    assert result.target_binding["follow_active"] is False
    assert result.target_binding["bearing_deg"] == -15.0
    assert result.target_binding["distance_m"] == 1.5
    assert status["tracking_state"] == "fresh"
    assert status["valid"] is True
    assert status["follow_active"] is False


def test_target_roi_uses_grace_width_and_stale_unavailable() -> None:
    extractor = TargetRegionExtractor(
        TargetRegionConfig(
            enabled=True,
            fresh_ms=300,
            grace_ms=700,
            camera_hfov_deg=90.0,
            camera_yaw_offset_deg=0.0,
            fresh_width_ratio=0.50,
            grace_width_ratio=0.70,
        )
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    grace_state = FollowTargetState(
        sequence=2,
        target_valid=True,
        follow_active=True,
        bearing_deg=0.0,
        distance_m=2.0,
        received_monotonic=time.monotonic() - 0.45,
    )
    stale_state = FollowTargetState(
        sequence=3,
        target_valid=True,
        follow_active=True,
        bearing_deg=0.0,
        distance_m=2.0,
        received_monotonic=time.monotonic() - 1.0,
    )

    grace = extractor.extract(frame, grace_state)
    stale = extractor.extract(frame, stale_state)

    assert grace.tracking_state == "grace"
    assert grace.frame is not None
    assert grace.frame.shape[:2] == (100, 140)
    assert stale.tracking_state == "unavailable"
    assert stale.frame is None
    assert stale.target_binding["roi"] is None
    assert stale.target_binding["reason"] == "target_stale"


def test_target_invalid_and_bad_bearing_are_unavailable() -> None:
    extractor = TargetRegionExtractor(
        TargetRegionConfig(
            enabled=True,
            fresh_ms=300,
            grace_ms=700,
            camera_hfov_deg=90.0,
            camera_yaw_offset_deg=0.0,
            fresh_width_ratio=0.50,
            grace_width_ratio=0.70,
        )
    )
    frame = np.zeros((100, 200, 3), dtype=np.uint8)
    invalid_target = FollowTargetState(
        sequence=4,
        target_valid=False,
        follow_active=True,
        bearing_deg=0.0,
        distance_m=2.0,
        received_monotonic=time.monotonic(),
    )
    bad_bearing = FollowTargetState(
        sequence=5,
        target_valid=True,
        follow_active=False,
        bearing_deg=float("nan"),
        distance_m=2.0,
        received_monotonic=time.monotonic(),
    )

    invalid = extractor.extract(frame, invalid_target)
    bad = extractor.extract(frame, bad_bearing)

    assert invalid.tracking_state == "unavailable"
    assert invalid.frame is None
    assert invalid.target_binding["reason"] == "target_invalid"
    assert bad.tracking_state == "unavailable"
    assert bad.frame is None
    assert bad.target_binding["reason"] == "bearing_invalid"


def test_follow_target_receiver_keeps_latest_and_drops_out_of_order() -> None:
    receiver = FollowTargetReceiver(host="127.0.0.1", port=8766, enabled=True)

    receiver._handle_packet(_packet(sequence=1, bearing=0.0), time.monotonic())  # noqa: SLF001
    receiver._handle_packet(_packet(sequence=3, bearing=15.0), time.monotonic())  # noqa: SLF001
    receiver._handle_packet(_packet(sequence=2, bearing=-15.0), time.monotonic())  # noqa: SLF001

    latest = receiver.latest()
    status = receiver.status()
    assert latest is not None
    assert latest.sequence == 3
    assert latest.bearing_deg == 15.0
    assert status["packet_count"] == 2
    assert status["out_of_order_count"] == 1


def test_follow_target_receiver_receives_udp_without_queueing() -> None:
    port = _free_udp_port()
    receiver = FollowTargetReceiver(host="127.0.0.1", port=port, enabled=True)
    receiver.start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for sequence in range(20):
            _send(sock, port, sequence=sequence, bearing=float(sequence))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            latest = receiver.latest()
            if latest is not None and latest.sequence == 19:
                break
            time.sleep(0.01)
    finally:
        sock.close()
        receiver.stop()

    latest = receiver.latest()
    assert latest is not None
    assert latest.sequence == 19


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _send(sock: socket.socket, port: int, *, sequence: int, bearing: float) -> None:
    sock.sendto(_packet(sequence=sequence, bearing=bearing), ("127.0.0.1", port))


def _packet(*, sequence: int, bearing: float) -> bytes:
    payload = {
        "schema_version": "go2_follow_target.v1",
        "sequence": sequence,
        "target_valid": True,
        "follow_active": True,
        "bearing_deg": bearing,
        "distance_m": 2.0,
        "sent_timestamp_ms": int(time.time() * 1000),
    }
    return json.dumps(payload).encode("utf-8")
