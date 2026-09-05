from __future__ import annotations

from pathlib import Path

import pytest

from scripts.start_visual_gpu_auto import choose_available_port


def test_choose_available_port_prefers_8000() -> None:
    assert choose_available_port(
        "127.0.0.1",
        check=lambda _host, _port: True,
    ) == 8000


def test_choose_available_port_falls_back_in_order() -> None:
    occupied = {8000, 8001}

    assert choose_available_port(
        "127.0.0.1",
        check=lambda _host, port: port not in occupied,
    ) == 8002


def test_choose_available_port_fails_when_all_candidates_are_occupied() -> None:
    with pytest.raises(RuntimeError, match="8000, 8001, 8002"):
        choose_available_port(
            "127.0.0.1",
            check=lambda _host, _port: False,
        )


def test_gpu_launcher_keeps_required_cuda_guards() -> None:
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "scripts" / "start_visual_gpu.ps1").read_text(encoding="utf-8")

    assert "camera-service-gpu\\python.exe" in source
    assert 'POST_FALL_V2_BINARY_ONNX_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"' in source
    assert 'YOLO_DEVICE = "cuda:0"' in source
    assert 'if requires_cuda and "CUDAExecutionProvider" not in providers:' in source
