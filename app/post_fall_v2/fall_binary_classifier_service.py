from __future__ import annotations

import hashlib
import time
from pathlib import Path

import cv2
import numpy as np

from app.post_fall_v2.schemas import (
    BINARY_CANDIDATE_THRESHOLD_OOF,
    BinaryFallResult,
    InputInfo,
    ModelInfo,
    PerformanceInfo,
    SampledFrame,
    ThresholdInfo,
    utc_now_iso,
)


class FallBinaryClassifierError(RuntimeError):
    pass


class FallBinaryClassifierService:
    def __init__(
        self,
        *,
        model_path: str | Path,
        expected_sha256: str,
        threshold: float,
        input_policy: str,
        model_name: str = "efficientnet_b0_post_fall",
        providers: list[str] | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.expected_sha256 = expected_sha256.lower()
        self.threshold = float(threshold)
        self.input_policy = input_policy
        self.model_name = model_name
        self.providers = providers or ["CPUExecutionProvider"]
        self.model_sha256: str | None = None
        self.provider: str | None = None
        self.loaded = False
        self.last_error: str | None = None
        self._session = None
        self.load()

    def load(self) -> None:
        if not self.model_path.is_file():
            self.last_error = f"model not found: {self.model_path}"
            raise FileNotFoundError(self.last_error)
        digest = self._sha256(self.model_path)
        self.model_sha256 = digest
        if digest.lower() != self.expected_sha256:
            self.last_error = "model sha256 mismatch"
            raise FallBinaryClassifierError(
                f"model sha256 mismatch: expected {self.expected_sha256}, got {digest}"
            )
        try:
            import onnxruntime as ort
        except Exception as exc:  # pragma: no cover - depends on deployment env
            self.last_error = f"onnxruntime unavailable: {exc}"
            raise FallBinaryClassifierError(self.last_error) from exc

        available = set(ort.get_available_providers())
        selected = [provider for provider in self.providers if provider in available]
        if not selected:
            selected = ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(str(self.model_path), providers=selected)
        self.provider = self._session.get_providers()[0] if self._session.get_providers() else None
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or inputs[0].name != "input":
            raise FallBinaryClassifierError("unexpected ONNX input contract")
        if len(outputs) != 1 or outputs[0].name != "logits":
            raise FallBinaryClassifierError("unexpected ONNX output contract")
        self.loaded = True
        self.last_error = None

    def infer(self, sampled: SampledFrame) -> BinaryFallResult:
        started = time.monotonic()
        queue_delay_ms = round((started - sampled.sampled_monotonic) * 1000, 2)
        threshold = ThresholdInfo(value=self.threshold, type=BINARY_CANDIDATE_THRESHOLD_OOF, production_validated=False)
        model = ModelInfo(
            name=self.model_name,
            format="onnx",
            sha256=self.model_sha256 or "",
            provider=self.provider,
        )
        input_info = InputInfo(
            policy=self.input_policy,
            source_width=sampled.source_width,
            source_height=sampled.source_height,
            model_width=224,
            model_height=224,
        )
        try:
            preprocess_started = time.monotonic()
            input_tensor = self.preprocess_bgr(sampled.frame)
            preprocess_ms = round((time.monotonic() - preprocess_started) * 1000, 2)
            inference_started = time.monotonic()
            if self._session is None:
                raise FallBinaryClassifierError("model session is not loaded")
            logits = self._session.run(None, {"input": input_tensor})[0]
            inference_ms = round((time.monotonic() - inference_started) * 1000, 2)
            if logits.shape[-1] != 2:
                raise FallBinaryClassifierError(f"unexpected logits shape: {logits.shape}")
            probs = self._softmax(logits.astype(np.float32))[0]
            nofall_probability = float(probs[0])
            fall_probability = float(probs[1])
            class_index = int(np.argmax(probs))
            prediction = "Fall" if class_index == 1 else "noFall"
            return BinaryFallResult(
                frame_id=sampled.frame_id,
                camera_id=sampled.camera_id,
                captured_at=sampled.captured_at,
                sampled_at=sampled.sampled_at,
                inferred_at=utc_now_iso(),
                prediction=prediction,
                class_index=class_index,
                fall_probability=fall_probability,
                nofall_probability=nofall_probability,
                shadow_candidate_hint=fall_probability >= self.threshold,
                threshold=threshold,
                model=model,
                input=input_info,
                performance=PerformanceInfo(
                    queue_delay_ms=queue_delay_ms,
                    preprocess_ms=preprocess_ms,
                    inference_ms=inference_ms,
                    total_ms=round((time.monotonic() - started) * 1000, 2),
                ),
                valid=True,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return BinaryFallResult(
                frame_id=sampled.frame_id,
                camera_id=sampled.camera_id,
                captured_at=sampled.captured_at,
                sampled_at=sampled.sampled_at,
                inferred_at=utc_now_iso(),
                prediction=None,
                class_index=None,
                fall_probability=None,
                nofall_probability=None,
                shadow_candidate_hint=False,
                threshold=threshold,
                model=model,
                input=input_info,
                performance=PerformanceInfo(
                    queue_delay_ms=queue_delay_ms,
                    preprocess_ms=None,
                    inference_ms=None,
                    total_ms=round((time.monotonic() - started) * 1000, 2),
                ),
                valid=False,
                error_code="BINARY_INFERENCE_ERROR",
                error_message=str(exc),
            )

    @staticmethod
    def preprocess_bgr(frame: np.ndarray) -> np.ndarray:
        if not isinstance(frame, np.ndarray):
            raise ValueError("frame must be a numpy array")
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"frame must have shape HxWx3, got {frame.shape}")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("frame has invalid dimensions")
        scale = 224.0 / max(height, width)
        resized_width = max(1, int(round(width * scale)))
        resized_height = max(1, int(round(height * scale)))
        resized = cv2.resize(
            rgb,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )
        top = (224 - resized_height) // 2
        bottom = 224 - resized_height - top
        left = (224 - resized_width) // 2
        right = 224 - resized_width - left
        if top or bottom or left or right:
            resized = cv2.copyMakeBorder(
                resized,
                top,
                bottom,
                left,
                right,
                borderType=cv2.BORDER_REFLECT_101,
            )
        tensor = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        tensor = (tensor - mean) / std
        tensor = np.transpose(tensor, (2, 0, 1))[None].astype(np.float32)
        return tensor

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        return exp / exp.sum(axis=1, keepdims=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
