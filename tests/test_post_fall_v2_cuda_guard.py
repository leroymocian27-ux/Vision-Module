from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from app.post_fall_v2.fall_binary_classifier_service import (
    FallBinaryClassifierError,
    FallBinaryClassifierService,
)
from app.post_fall_v2.schemas import FULL_FRAME_TRAIN_MATCHED


MODEL_SHA256 = "a" * 64


def _model_path(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"test-model")
    return path


def _make_service(tmp_path, providers):
    return FallBinaryClassifierService(
        model_path=_model_path(tmp_path),
        expected_sha256=MODEL_SHA256,
        threshold=0.3979087471961975,
        input_policy=FULL_FRAME_TRAIN_MATCHED,
        providers=providers,
        warmup_runs=1,
    )


def _patch_hash(monkeypatch):
    monkeypatch.setattr(
        FallBinaryClassifierService,
        "_sha256",
        staticmethod(lambda _path: MODEL_SHA256),
    )


def test_cuda_request_rejects_missing_provider(tmp_path, monkeypatch) -> None:
    _patch_hash(monkeypatch)
    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=lambda *_args, **_kwargs: pytest.fail("session should not be created"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    with pytest.raises(FallBinaryClassifierError, match="CUDAExecutionProvider was requested"):
        _make_service(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])


def test_cuda_request_rejects_cuda_session_failure(tmp_path, monkeypatch) -> None:
    _patch_hash(monkeypatch)

    def _raise_session(*_args, **_kwargs):
        raise RuntimeError("cuda session failed")

    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        InferenceSession=_raise_session,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    with pytest.raises(FallBinaryClassifierError, match="session creation failed"):
        _make_service(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])


def test_cuda_request_rejects_cpu_active_provider(tmp_path, monkeypatch) -> None:
    _patch_hash(monkeypatch)

    class _CpuSession:
        def get_providers(self):
            return ["CPUExecutionProvider"]

    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        InferenceSession=lambda *_args, **_kwargs: _CpuSession(),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    with pytest.raises(FallBinaryClassifierError, match="active providers"):
        _make_service(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])


def test_cuda_request_rejects_warmup_failure(tmp_path, monkeypatch) -> None:
    _patch_hash(monkeypatch)

    class _CudaSession:
        def get_providers(self):
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]

        def get_inputs(self):
            return [SimpleNamespace(name="input", shape=[1, 3, 224, 224])]

        def get_outputs(self):
            return [SimpleNamespace(name="logits")]

        def run(self, *_args, **_kwargs):
            raise RuntimeError("cuda warmup failed")

    fake_ort = SimpleNamespace(
        get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
        InferenceSession=lambda *_args, **_kwargs: _CudaSession(),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    with pytest.raises(FallBinaryClassifierError, match="warm-up failed"):
        _make_service(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])
