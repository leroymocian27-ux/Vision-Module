from __future__ import annotations

import time
from dataclasses import replace

from app.core.config import Settings
from app.detection.realtime_result_store import ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.temporal_worker_service import TemporalWorkerService


class _TemporalStub:
    def __init__(self) -> None:
        self.calls = 0

    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        del camera_id
        self.calls += 1
        return [item.model_copy(update={"temporal": {"source": "stub"}}) for item in objects]


def _snapshot(seq: int, monotonic_at: float) -> ObjectSnapshot:
    return ObjectSnapshot(
        camera_id="camera_01",
        frame_seq=seq,
        frame_width=640,
        frame_height=360,
        timestamp="2026-07-20T00:00:00Z",
        monotonic_at=monotonic_at,
        objects=[
            DetectedObject(
                label="person",
                confidence=0.9,
                bbox=[10.0, 20.0, 120.0, 220.0],
                track_id=1,
                is_target=True,
            )
        ],
    )


def test_temporal_worker_drops_duplicate_frames_as_backpressure():
    settings = replace(Settings(), enable_temporal=True, temporal_worker_enabled=True)
    store = RealtimeResultStore()
    temporal = _TemporalStub()
    worker = TemporalWorkerService(settings, store, temporal)  # type: ignore[arg-type]
    store.update_tracking(_snapshot(11, time.monotonic()))

    worker._tick("camera_01")  # type: ignore[attr-defined]
    worker._tick("camera_01")  # type: ignore[attr-defined]

    status = worker.status("camera_01")
    assert temporal.calls == 1
    assert status.last_frame_seq == 11
    assert status.skipped_duplicate_frame_count == 1


def test_temporal_worker_drops_stale_input_before_inference():
    settings = replace(
        Settings(),
        enable_temporal=True,
        temporal_worker_enabled=True,
        stream_stale_threshold_ms=20,
    )
    store = RealtimeResultStore()
    temporal = _TemporalStub()
    worker = TemporalWorkerService(settings, store, temporal)  # type: ignore[arg-type]
    store.update_tracking(_snapshot(12, time.monotonic() - 1.0))

    worker._tick("camera_01")  # type: ignore[attr-defined]

    status = worker.status("camera_01")
    assert temporal.calls == 0
    assert status.skipped_stale_input_count == 1
    assert store.latest_temporal("camera_01") is None
