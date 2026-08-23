from __future__ import annotations

from dataclasses import replace

from app.core.config import Settings
from app.detection.realtime_result_store import RealtimeResultStore
from app.services.detection_service import DetectionService
from app.services.fall_hint_worker_service import FallHintWorkerService
from app.services.temporal_service import TemporalService


class _SourceManager:
    pass


def test_post_fall_v2_construction_does_not_load_legacy_yolo_or_temporal_onnx(monkeypatch) -> None:
    settings = replace(
        Settings(),
        pipeline_mode="post_fall_v2",
        post_fall_v2_enabled=True,
        post_fall_v2_aux_person_detection_enabled=False,
        detection_enabled=True,
        fall_detector_enabled=True,
        enable_temporal=True,
        temporal_model_provider="onnx_lstm",
    )
    calls: list[str] = []

    def forbidden(name):
        def _raise(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"legacy model load attempted: {name}")
        return _raise

    monkeypatch.setattr("app.services.detection_service.YoloPersonDetector", forbidden("person_yolo"))
    monkeypatch.setattr("app.services.detection_service.YoloFallDetector", forbidden("fall_yolo"))
    monkeypatch.setattr("app.services.fall_hint_worker_service.YoloFallDetector", forbidden("fall_hint_yolo"))
    monkeypatch.setattr("app.services.temporal_service.ONNXSequenceModel", forbidden("temporal_onnx"))

    detection = DetectionService(settings, _SourceManager(), RealtimeResultStore())
    fall_hint = FallHintWorkerService(settings, _SourceManager(), RealtimeResultStore())
    temporal = TemporalService(settings)

    assert calls == []
    assert detection.detector.status().loaded is False
    assert detection.fall_detector is None
    assert fall_hint.detector is None
    assert temporal.model is temporal.fallback_model
