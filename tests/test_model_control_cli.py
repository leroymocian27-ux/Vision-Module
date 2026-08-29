from __future__ import annotations

from app.cli import _build_parser
from app.cli import _default_camera_id
from app.post_fall_v2.model_log_bus import ModelLogBus


def test_model_log_bus_keeps_bounded_history_and_since_cursor() -> None:
    bus = ModelLogBus(max_events_per_kind=10)
    first = bus.publish("binary", "first", camera_id="camera_01")
    second = bus.publish("binary", "second", provider="CUDAExecutionProvider")
    bus.publish("qwen", "qwen-only")

    assert [item["message"] for item in bus.snapshot("binary")] == ["first", "second"]
    assert [item["message"] for item in bus.since("binary", first.seq)] == ["second"]
    assert bus.since("binary", second.seq) == []


def test_cli_parser_supports_model_lifecycle_commands() -> None:
    parser = _build_parser()

    start = parser.parse_args(["model", "binary", "start", "--no-follow"])
    assert start.model_kind == "binary"
    assert start.action == "start"
    assert start.no_follow is True

    logs = parser.parse_args(["model", "qwen", "logs", "--follow", "--tail", "50"])
    assert logs.model_kind == "qwen"
    assert logs.action == "logs"
    assert logs.follow is True
    assert logs.tail == 50


def test_cli_default_camera_id_uses_project_env(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEFAULT_CAMERA_ID=go2_front_camera\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VISION_SERVICE_CAMERA_ID", raising=False)
    monkeypatch.delenv("VISION_SERVICE_ENV_FILE", raising=False)

    assert _default_camera_id() == "go2_front_camera"


def test_cli_default_camera_id_allows_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("VISION_SERVICE_CAMERA_ID", "manual_camera")

    assert _default_camera_id() == "manual_camera"
