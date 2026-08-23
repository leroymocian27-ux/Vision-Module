from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from app.temporal.feature_vectorizer import FeatureVectorizer
from app.temporal.schemas import SequencePrediction, TargetFeature


class ONNXSequenceModel:
    def __init__(
        self,
        *,
        model_path: str,
        schema_path: str,
        providers: str,
        vectorizer: FeatureVectorizer,
        window_size: int,
        input_dim: int,
        frame_width: int,
        frame_height: int,
    ) -> None:
        self.model_name = "onnx_lstm"
        self.model_path = model_path
        self.schema_path = schema_path
        self.vectorizer = vectorizer
        self.window_size = window_size
        self.input_dim = input_dim
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.available = False
        self.last_error: str | None = None
        self.session: Any | None = None
        self.input_name: str | None = None
        self.output_name: str | None = None
        self.selected_providers: list[str] = []
        self._load(providers)

    def predict(self, window: list[TargetFeature]) -> SequencePrediction:
        if not self.available or self.session is None or self.input_name is None:
            return SequencePrediction(
                source=self._fallback_source(),
                fall_probability=0.0,
                model_name=self.model_name,
                model_available=False,
                window_ready=False,
                window_size=len(window),
                feature_dim=self.input_dim,
            )
        if len(window) < self.window_size:
            return SequencePrediction(
                source="warming_up",
                fall_probability=0.0,
                model_name=self.model_name,
                model_available=True,
                window_ready=False,
                window_size=len(window),
                feature_dim=self.input_dim,
            )

        start = time.perf_counter()
        recent = window[-self.window_size :]
        vectors = self.vectorizer.vectors_from_window(
            recent,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )
        x = np.asarray([vectors], dtype=np.float32)
        outputs = self.session.run([self.output_name] if self.output_name else None, {self.input_name: x})
        probability = self._decode_probability(outputs)
        latency_ms = round((time.perf_counter() - start) * 1000, 3)
        return SequencePrediction(
            source="onnx_lstm",
            fall_probability=round(probability, 4),
            model_name=self.model_name,
            model_available=True,
            window_ready=True,
            window_size=len(recent),
            feature_dim=self.input_dim,
            confidence=round(max(probability, 1.0 - probability), 4),
            latency_ms=latency_ms,
        )

    def _load(self, providers: str) -> None:
        model = Path(self.model_path)
        if not model.exists():
            self.last_error = f"model missing: {self.model_path}"
            return

        schema_error = self._validate_schema()
        if schema_error is not None:
            self.last_error = schema_error
            return

        try:
            import onnxruntime as ort  # type: ignore
        except Exception as exc:
            self.last_error = f"onnxruntime unavailable: {exc}"
            return

        try:
            available = set(ort.get_available_providers())
            requested = [item.strip() for item in providers.split(",") if item.strip()]
            selected = [item for item in requested if item in available]
            if not selected and "CPUExecutionProvider" in available:
                selected = ["CPUExecutionProvider"]
            if not selected:
                self.last_error = f"no usable onnx providers: requested={requested} available={sorted(available)}"
                return
            self.session = ort.InferenceSession(str(model), providers=selected)
            self.selected_providers = selected
            model_inputs = self.session.get_inputs()
            model_outputs = self.session.get_outputs()
            if not model_inputs:
                self.last_error = "onnx model has no inputs"
                self.session = None
                return
            self.input_name = model_inputs[0].name
            self.output_name = model_outputs[0].name if model_outputs else None
            shape = list(model_inputs[0].shape)
            if len(shape) == 3:
                seq_dim = shape[1]
                feat_dim = shape[2]
                if isinstance(seq_dim, int) and seq_dim != self.window_size:
                    self.last_error = f"sequence length mismatch: model={seq_dim} settings={self.window_size}"
                    self.session = None
                    return
                if isinstance(feat_dim, int) and feat_dim != self.input_dim:
                    self.last_error = f"input dim mismatch: model={feat_dim} settings={self.input_dim}"
                    self.session = None
                    return
            self.available = True
            self.last_error = None
        except Exception as exc:
            self.last_error = f"onnx load failed: {exc}"
            self.session = None

    def _validate_schema(self) -> str | None:
        schema_file = Path(self.schema_path)
        runtime_schema = self.vectorizer.schema()
        if not schema_file.exists():
            return f"schema missing: {self.schema_path}"
        try:
            payload = json.loads(schema_file.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"schema unreadable: {exc}"
        expected = runtime_schema.model_dump()
        checks = {
            "schema_version": expected["schema_version"],
            "input_dim": self.input_dim,
            "window_size": self.window_size,
            "schema_hash": expected["schema_hash"],
            "feature_names": expected["feature_names"],
        }
        for key, expected_value in checks.items():
            if payload.get(key) != expected_value:
                return f"schema mismatch {key}: model={payload.get(key)!r} runtime={expected_value!r}"
        return None

    def _fallback_source(self) -> str:
        if self.last_error is None:
            return "fallback_mock_inference_error"
        if self.last_error.startswith("model missing"):
            return "fallback_mock_model_missing"
        if self.last_error.startswith("onnxruntime unavailable"):
            return "fallback_mock_onnxruntime_missing"
        if "schema" in self.last_error or "dim mismatch" in self.last_error or "sequence length" in self.last_error:
            return "fallback_mock_schema_mismatch"
        return "fallback_mock_inference_error"

    @staticmethod
    def _decode_probability(outputs: list[Any]) -> float:
        if not outputs:
            raise ValueError("onnx model returned no outputs")
        first = np.asarray(outputs[0], dtype=np.float32)
        if first.size == 1:
            value = float(first.reshape(-1)[0])
            if 0.0 <= value <= 1.0:
                return value
            return 1.0 / (1.0 + float(np.exp(-value)))
        flat = first.reshape(-1)
        if flat.size >= 2:
            shifted = flat - np.max(flat)
            probs = np.exp(shifted) / np.sum(np.exp(shifted))
            return float(probs[1])
        raise ValueError(f"unsupported onnx output shape: {first.shape}")
