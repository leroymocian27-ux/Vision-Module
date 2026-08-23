from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject
from app.services.temporal_service import TemporalService


def main() -> int:
    results = {
        "mock_provider": test_mock_provider(),
        "shadow_provider": test_shadow_provider(),
        "model_missing_fallback": test_model_missing_fallback(),
        "schema_mismatch_fallback": test_schema_mismatch_fallback(),
        "track_modes_and_reset": test_track_modes_and_reset(),
    }
    failed = {name: result for name, result in results.items() if not result["passed"]}
    out = ROOT / "evaluations" / "phase6f_runtime_smoke_001.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 1 if failed else 0


SETTING_KEYS = {
    "ENABLE_TEMPORAL": ("enable_temporal", lambda value: str(value).lower() in {"1", "true", "yes", "on"}),
    "TEMPORAL_MODEL_PROVIDER": ("temporal_model_provider", str),
    "TEMPORAL_ONNX_MODEL_PATH": ("temporal_onnx_model_path", str),
    "TEMPORAL_FEATURE_SCHEMA_PATH": ("temporal_feature_schema_path", str),
    "TEMPORAL_MODEL_INPUT_DIM": ("temporal_model_input_dim", int),
    "TEMPORAL_TRACK_MODE": ("temporal_track_mode", str),
}


def settings(**env: str) -> Settings:
    updates = {}
    for key, value in env.items():
        attr, convert = SETTING_KEYS[key]
        updates[attr] = convert(value)
    return replace(Settings(), **updates)


def person(track_id: int, *, is_target: bool = False, x: float = 20.0) -> DetectedObject:
    return DetectedObject(
        label="person",
        confidence=0.9,
        bbox=[x, 20.0, x + 80.0, 180.0],
        track_id=track_id,
        is_target=is_target,
    )


def feed(service: TemporalService, *, camera_id: str = "smoke", frames: int = 35, objects: list[DetectedObject] | None = None):
    latest = None
    for index in range(frames):
        frame_objects = objects or [person(1)]
        latest = service.enrich(camera_id, frame_objects)
    return latest or []


def test_mock_provider() -> dict:
    service = TemporalService(settings(ENABLE_TEMPORAL="true", TEMPORAL_MODEL_PROVIDER="mock"))
    objects = feed(service)
    temporal = objects[0].temporal or {}
    return {
        "passed": temporal.get("source") == "mock" and bool(objects[0].fall_decision),
        "source": temporal.get("source"),
        "fall_state": (objects[0].fall_decision or {}).get("fall_state"),
    }


def test_shadow_provider() -> dict:
    service = TemporalService(
        settings(
            ENABLE_TEMPORAL="true",
            TEMPORAL_MODEL_PROVIDER="shadow",
            TEMPORAL_ONNX_MODEL_PATH="models/fall_lstm_v3.onnx",
            TEMPORAL_FEATURE_SCHEMA_PATH="models/fall_lstm_v3_features.json",
        )
    )
    objects = feed(service)
    temporal = objects[0].temporal or {}
    shadow = temporal.get("shadow") or {}
    return {
        "passed": temporal.get("source") == "mock" and shadow.get("source") in {"shadow_onnx_lstm", "warming_up"},
        "source": temporal.get("source"),
        "shadow_source": shadow.get("source"),
    }


def test_model_missing_fallback() -> dict:
    service = TemporalService(
        settings(
            ENABLE_TEMPORAL="true",
            TEMPORAL_MODEL_PROVIDER="onnx_lstm",
            TEMPORAL_ONNX_MODEL_PATH="models/missing_phase6_model.onnx",
            TEMPORAL_FEATURE_SCHEMA_PATH="models/fall_lstm_v3_features.json",
        )
    )
    objects = feed(service)
    source = (objects[0].temporal or {}).get("source")
    return {"passed": source == "fallback_mock_model_missing", "source": source, "status": service.status().model_last_error}


def test_schema_mismatch_fallback() -> dict:
    service = TemporalService(
        settings(
            ENABLE_TEMPORAL="true",
            TEMPORAL_MODEL_PROVIDER="onnx_lstm",
            TEMPORAL_ONNX_MODEL_PATH="models/fall_lstm_v3.onnx",
            TEMPORAL_FEATURE_SCHEMA_PATH="models/fall_lstm_features.json",
            TEMPORAL_MODEL_INPUT_DIM="14",
        )
    )
    objects = feed(service)
    source = (objects[0].temporal or {}).get("source")
    return {"passed": source == "fallback_mock_schema_mismatch", "source": source, "status": service.status().model_last_error}


def test_track_modes_and_reset() -> dict:
    all_tracks = TemporalService(settings(ENABLE_TEMPORAL="true", TEMPORAL_MODEL_PROVIDER="mock", TEMPORAL_TRACK_MODE="all_tracks"))
    objects = feed(all_tracks, objects=[person(1, x=20.0), person(2, x=160.0)])
    all_temporal = sum(1 for item in objects if item.temporal)
    before_reset = all_tracks.status().active_tracks
    all_tracks.reset_camera("smoke")
    after_reset = all_tracks.status().active_tracks

    target_only = TemporalService(settings(ENABLE_TEMPORAL="true", TEMPORAL_MODEL_PROVIDER="mock", TEMPORAL_TRACK_MODE="target_only"))
    objects = feed(target_only, objects=[person(1, is_target=True, x=20.0), person(2, is_target=False, x=160.0)])
    target_temporal = sum(1 for item in objects if item.temporal)
    return {
        "passed": all_temporal == 2 and before_reset >= 2 and after_reset == 0 and target_temporal == 1,
        "all_tracks_temporal_objects": all_temporal,
        "before_reset": before_reset,
        "after_reset": after_reset,
        "target_only_temporal_objects": target_temporal,
    }


if __name__ == "__main__":
    raise SystemExit(main())
