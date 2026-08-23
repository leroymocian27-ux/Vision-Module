from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.result_publisher_service import ResultPublisherService
from app.streaming.result_channel_manager import ResultChannelManager


def _person(**updates) -> DetectedObject:
    payload = {
        "label": "person",
        "confidence": 0.9,
        "bbox": [10.0, 20.0, 120.0, 220.0],
        "track_id": 1,
        "is_target": True,
    }
    payload.update(updates)
    return DetectedObject(**payload)


def test_store_marks_wrong_frame_evidence_as_misaligned():
    store = RealtimeResultStore()
    now = time.monotonic()
    store.update_detection(
        DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=50,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-20T00:00:00Z",
            monotonic_at=now,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[_person()],
        )
    )

    result = store.latest_with_freshness(
        "camera_01",
        "detection",
        ttl_ms=1000,
        base_frame_seq=40,
        max_frame_delta=2,
    )

    assert result.state == "frame_misaligned"
    assert result.frame_seq == 50
    assert result.frame_delta == 10
    assert result.stale_reason == "frame_misaligned"


def test_result_builder_marks_and_blocks_core_misaligned_evidence():
    settings = replace(
        Settings(),
        enable_pose=False,
        enable_behavior=False,
        enable_temporal=False,
        temporal_worker_enabled=False,
        fall_detector_enabled=False,
        fusion_max_frame_delta_detection=1,
        fusion_max_frame_delta_tracking=1,
    )
    store = RealtimeResultStore()
    publisher = ResultPublisherService(settings, store, ResultChannelManager())
    now = time.monotonic()
    base = ObjectSnapshot(
        camera_id="camera_01",
        frame_seq=10,
        frame_width=640,
        frame_height=360,
        timestamp="2026-07-20T00:00:00Z",
        monotonic_at=now,
        objects=[_person()],
    )
    store.update_tracking(base)
    store.update_detection(
        DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=20,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-20T00:00:00Z",
            monotonic_at=now,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[_person()],
        )
    )

    evidence = publisher._evidence_debug("camera_01", base)  # type: ignore[attr-defined]
    guarded = publisher._apply_core_freshness_guard(  # type: ignore[attr-defined]
        [
            _person(
                fall_decision={"fall_state": "fallen_confirmed"},
                alarm_preview={"confirmed": True},
            )
        ],
        evidence,
    )

    assert evidence["evidence_freshness"]["detection"] == "frame_misaligned"
    assert evidence["evidence_frame_delta"]["detection"] == 10
    assert evidence["confirm_blocked_by"] == ["detection_frame_misaligned"]
    assert guarded[0].alarm_preview["confirmed"] is False
    assert guarded[0].fall_decision["fall_state"] == "fallen_candidate"
    assert guarded[0].fall_decision["confirm_blocked_by"] == ["detection_frame_misaligned"]
