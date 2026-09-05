from __future__ import annotations

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.main import _enforce_cuda_runtime_guard, _should_enforce_cuda_runtime_guard


def _base_settings() -> Settings:
    return replace(
        Settings(),
        vision_service_require_cuda=True,
        vision_service_cuda_python_path="",
        detection_enabled=False,
        fall_detector_enabled=False,
        enable_pose=False,
        enable_temporal=False,
        post_fall_v2_enabled=False,
        post_fall_v2_qwen_enabled=False,
    )


def _patch_cuda_modules(monkeypatch: pytest.MonkeyPatch, *, torch_cuda: bool, ort_cuda: bool) -> None:
    fake_torch = SimpleNamespace(
        __version__="test",
        version=SimpleNamespace(cuda="12.8" if torch_cuda else None),
        cuda=SimpleNamespace(
            is_available=lambda: torch_cuda,
            device_count=lambda: 1 if torch_cuda else 0,
            get_device_name=lambda _index: "NVIDIA GeForce RTX 5060 Laptop GPU",
        ),
    )
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if ort_cuda else ["CPUExecutionProvider"]
    fake_ort = SimpleNamespace(__version__="test", get_available_providers=lambda: providers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)


def test_cuda_runtime_guard_is_enabled_by_default() -> None:
    assert _should_enforce_cuda_runtime_guard(Settings())


def test_cuda_runtime_guard_rejects_cpu_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cuda_modules(monkeypatch, torch_cuda=False, ort_cuda=True)

    with pytest.raises(RuntimeError, match=r"torch\.cuda\.is_available\(\) is false"):
        _enforce_cuda_runtime_guard(_base_settings())


def test_cuda_runtime_guard_rejects_missing_onnx_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cuda_modules(monkeypatch, torch_cuda=True, ort_cuda=False)

    with pytest.raises(RuntimeError, match="CUDAExecutionProvider"):
        _enforce_cuda_runtime_guard(_base_settings())


def test_cuda_runtime_guard_requires_cuda_first_binary_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cuda_modules(monkeypatch, torch_cuda=True, ort_cuda=True)
    settings = replace(
        _base_settings(),
        post_fall_v2_enabled=True,
        post_fall_v2_binary_onnx_providers="CPUExecutionProvider",
    )

    with pytest.raises(RuntimeError, match="POST_FALL_V2_BINARY_ONNX_PROVIDERS must start"):
        _enforce_cuda_runtime_guard(settings)


def test_cuda_runtime_guard_allows_cuda_ready_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cuda_modules(monkeypatch, torch_cuda=True, ort_cuda=True)
    settings = replace(
        _base_settings(),
        post_fall_v2_enabled=True,
        post_fall_v2_binary_onnx_providers="CUDAExecutionProvider,CPUExecutionProvider",
    )

    evidence = _enforce_cuda_runtime_guard(settings)

    assert evidence is not None
    assert evidence["torch"]["cuda_available"] is True
    assert "CUDAExecutionProvider" in evidence["onnxruntime"]["available_providers"]
