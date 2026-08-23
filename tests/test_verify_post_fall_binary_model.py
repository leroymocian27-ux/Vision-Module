from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from tools.verify_post_fall_binary_model import (
    BinaryFallResult,
    class_mapping,
    collect_sources,
    operating_points,
    threshold_sweep,
    write_json,
)


def test_collect_sources_requires_single_source(tmp_path: Path) -> None:
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"not a real image")

    with pytest.raises(ValueError, match="Provide --image or --directory"):
        collect_sources(image=None, directory=None)
    with pytest.raises(ValueError, match="only one"):
        collect_sources(image=image, directory=tmp_path)


def test_collect_sources_rejects_missing_or_unsupported_image(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        collect_sources(image=tmp_path / "missing.jpg", directory=None)

    text_file = tmp_path / "sample.txt"
    text_file.write_text("not an image", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported image extension"):
        collect_sources(image=text_file, directory=None)


def test_collect_sources_directory_filters_images(tmp_path: Path) -> None:
    safe_dir = tmp_path / "safe"
    risk_dir = tmp_path / "risk"
    safe_dir.mkdir()
    risk_dir.mkdir()
    (safe_dir / "a.jpg").write_bytes(b"a")
    (risk_dir / "b.png").write_bytes(b"b")
    (risk_dir / "notes.txt").write_text("ignored", encoding="utf-8")

    sources = collect_sources(image=None, directory=tmp_path)

    assert sorted(path.name for path in sources) == ["a.jpg", "b.png"]


def test_class_mapping_for_risk_safe_names() -> None:
    mapping = class_mapping({0: "risk", 1: "safe"})

    assert mapping["fall_class_index"] == 0
    assert mapping["non_fall_class_index"] == 1
    assert mapping["mapping_status"] == "confirmed_from_model_names"


def test_threshold_sweep_metrics_and_operating_points() -> None:
    records = [
        {"label": "risk", "fall_probability": 0.9},
        {"label": "risk", "fall_probability": 0.7},
        {"label": "safe", "fall_probability": 0.6},
        {"label": "safe", "fall_probability": 0.1},
    ]

    sweep = threshold_sweep(records, [0.5, 0.8])

    assert sweep[0] == {
        "threshold": 0.5,
        "tp": 2,
        "fp": 1,
        "tn": 1,
        "fn": 0,
        "precision": 0.666667,
        "recall": 1.0,
        "f1": 0.8,
        "specificity": 0.5,
        "false_positive_rate": 0.5,
    }
    points = operating_points(sweep)
    assert points["best_f1"] == sweep[0]
    assert points["high_recall"] == sweep[0]


def test_binary_fall_result_json_serializes(tmp_path: Path) -> None:
    result = BinaryFallResult(
        frame_id="frame_0001",
        camera_id=None,
        timestamp=None,
        prediction="risk",
        fall_probability=0.75,
        class_index=0,
        model_name="model.pt",
        model_version=None,
        model_hash="abc",
        inference_ms=12.3,
        input_width=320,
        input_height=240,
        valid=True,
        error_code=None,
        source="sample.jpg",
        model="model.pt",
        input_shape=[240, 320],
        preprocessing_summary={"imgsz": 384},
        raw_output_summary={"probabilities": [0.75, 0.25]},
    )
    path = tmp_path / "result.json"

    write_json(path, {"record": asdict(result)})

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["record"]["fall_probability"] == 0.75
    assert payload["record"]["raw_output_summary"]["probabilities"] == [0.75, 0.25]
