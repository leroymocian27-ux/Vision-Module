from __future__ import annotations

from dataclasses import replace

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject
from app.services.temporal_service import TemporalService


def _target(track_id: int = 1) -> DetectedObject:
    return DetectedObject(
        label="person",
        confidence=0.92,
        bbox=[20.0, 30.0, 140.0, 230.0],
        track_id=track_id,
        is_target=True,
    )


def test_temporal_window_reports_warming_up_before_required_window():
    settings = replace(
        Settings(),
        enable_temporal=True,
        temporal_model_provider="mock",
        temporal_model_window_size=3,
        temporal_warmup_min_size=3,
        feature_window_size=5,
    )
    service = TemporalService(settings)

    first = service.enrich("camera_01", [_target()])[0]
    second = service.enrich("camera_01", [_target()])[0]
    third = service.enrich("camera_01", [_target()])[0]

    assert first.temporal["window_size"] == 1
    assert first.temporal["window_ready"] is False
    assert second.temporal["window_size"] == 2
    assert second.temporal["window_ready"] is False
    assert third.temporal["window_size"] == 3
    assert third.temporal["window_ready"] is True
    assert service.status("camera_01").active_tracks == 1


def test_temporal_reset_clears_camera_tracks_on_source_or_track_change():
    settings = replace(
        Settings(),
        enable_temporal=True,
        temporal_model_provider="mock",
        temporal_model_window_size=3,
        feature_window_size=5,
    )
    service = TemporalService(settings)

    service.enrich("camera_01", [_target(track_id=7)])
    service.reset_camera("camera_01", reason="source_switch")

    status = service.status("camera_01")
    assert status.active_tracks == 0
    assert status.no_object_reset_count == 1
    assert status.last_reset_reason == "source_switch"
    assert status.fall_state == "normal"
