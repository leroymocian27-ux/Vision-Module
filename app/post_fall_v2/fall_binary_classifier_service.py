from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import cv2
import numpy as np

from app.core.logger import get_logger
from app.post_fall_v2.model_log_bus import model_log_bus
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


logger = get_logger(__name__)


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
        warmup_runs: int = 3,
    ) -> None:
        self.model_path = Path(model_path)
        self.expected_sha256 = expected_sha256.lower()
        self.threshold = float(threshold)
        self.input_policy = input_policy
        self.model_name = model_name
        self.providers = providers or ["CPUExecutionProvider"]
        self.warmup_runs = max(0, int(warmup_runs))
        self.model_sha256: str | None = None
        self.provider: str | None = None
        self.requested_providers: list[str] = list(self.providers)
        self.available_providers: list[str] = []
        self.active_providers: list[str] = []
        self.provider_degraded = False
        self.provider_warning: str | None = None
        self.load_timings_ms: dict[str, float] = {}
        self.loaded = False
        self.last_error: str | None = None
        self._dll_directories: list[object] = []
        self._session = None
        self.load()

    def load(self) -> None:
        load_started = time.monotonic()
        timings: dict[str, float] = {}
        if not self.model_path.is_file():
            self.last_error = f"model not found: {self.model_path}"
            raise FileNotFoundError(self.last_error)
        digest_started = time.monotonic()
        digest = self._sha256(self.model_path)
        timings["model_sha256"] = round((time.monotonic() - digest_started) * 1000, 2)
        self.model_sha256 = digest
        if digest.lower() != self.expected_sha256:
            self.last_error = "model sha256 mismatch"
            raise FallBinaryClassifierError(
                f"model sha256 mismatch: expected {self.expected_sha256}, got {digest}"
            )
        wants_cuda = "CUDAExecutionProvider" in self.providers
        if wants_cuda:
            preload_started = time.monotonic()
            try:
                import torch

                torch_lib = Path(torch.__file__).resolve().parent / "lib"
                if torch_lib.is_dir() and hasattr(os, "add_dll_directory"):
                    self._dll_directories.append(os.add_dll_directory(str(torch_lib)))
            except Exception as exc:  # pragma: no cover - depends on deployment env
                logger.warning("post_fall_v2_binary_torch_cuda_dll_preload_skipped error=%s", exc)
            timings["torch_cuda_preload"] = round((time.monotonic() - preload_started) * 1000, 2)
        ort_import_started = time.monotonic()
        try:
            import onnxruntime as ort
        except Exception as exc:  # pragma: no cover - depends on deployment env
            self.last_error = f"onnxruntime unavailable: {exc}"
            raise FallBinaryClassifierError(self.last_error) from exc
        timings["onnxruntime_import"] = round((time.monotonic() - ort_import_started) * 1000, 2)

        self.available_providers = list(ort.get_available_providers())
        available = set(self.available_providers)
        if wants_cuda and "CUDAExecutionProvider" not in available:
            self.provider_degraded = True
            self.provider_warning = "CUDAExecutionProvider requested but unavailable"
            self.last_error = (
                "CUDAExecutionProvider was requested for Post-Fall V2 binary inference, "
                f"but available providers are {self.available_providers}"
            )
            raise FallBinaryClassifierError(self.last_error)
        selected = [provider for provider in self.providers if provider in available]
        if not selected:
            selected = ["CPUExecutionProvider"]
            self.provider_degraded = True
            self.provider_warning = "requested providers unavailable; using CPUExecutionProvider"
        try:
            session_started = time.monotonic()
            self._session = ort.InferenceSession(str(self.model_path), providers=selected)
            timings["inference_session"] = round((time.monotonic() - session_started) * 1000, 2)
        except Exception as exc:
            if wants_cuda:
                self.provider_degraded = True
                self.provider_warning = f"CUDAExecutionProvider session failed: {exc}"
                self.last_error = (
                    "CUDAExecutionProvider was requested for Post-Fall V2 binary inference, "
                    f"but session creation failed: {exc}"
                )
                raise FallBinaryClassifierError(self.last_error) from exc
            if selected != ["CPUExecutionProvider"] and "CPUExecutionProvider" in available:
                self.provider_degraded = True
                self.provider_warning = f"requested provider session failed; using CPUExecutionProvider: {exc}"
                logger.warning(
                    "post_fall_v2_binary_provider_degraded requested=%s available=%s error=%s",
                    self.providers,
                    self.available_providers,
                    exc,
                )
                selected = ["CPUExecutionProvider"]
                session_started = time.monotonic()
                self._session = ort.InferenceSession(str(self.model_path), providers=selected)
                timings["inference_session"] = round((time.monotonic() - session_started) * 1000, 2)
            else:
                raise
        self.active_providers = self._session.get_providers()
        self.provider = self.active_providers[0] if self.active_providers else None
        if wants_cuda and self.provider != "CUDAExecutionProvider":
            self.provider_degraded = True
            self.provider_warning = self.provider_warning or "CUDA requested but active provider is not CUDAExecutionProvider"
            logger.warning(
                "post_fall_v2_binary_cuda_not_active requested=%s available=%s active=%s",
                self.providers,
                self.available_providers,
                self.active_providers,
            )
            self.last_error = (
                "CUDAExecutionProvider was requested for Post-Fall V2 binary inference, "
                f"but active providers are {self.active_providers}"
            )
            raise FallBinaryClassifierError(self.last_error)
        logger.info(
            "post_fall_v2_binary_provider_selected requested=%s available=%s active=%s degraded=%s",
            self.providers,
            self.available_providers,
            self.active_providers,
            self.provider_degraded,
        )
        model_log_bus.publish(
            "binary",
            "binary_provider_selected",
            provider=self.provider,
            active_providers=self.active_providers,
            available_providers=self.available_providers,
            degraded=self.provider_degraded,
            warning=self.provider_warning,
        )
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or inputs[0].name != "input":
            raise FallBinaryClassifierError("unexpected ONNX input contract")
        if len(outputs) != 1 or outputs[0].name != "logits":
            raise FallBinaryClassifierError("unexpected ONNX output contract")
        try:
            warmup_started = time.monotonic()
            self._warmup(inputs[0])
            timings["warmup"] = round((time.monotonic() - warmup_started) * 1000, 2)
        except Exception as exc:
            if wants_cuda:
                self.provider_degraded = True
                self.provider_warning = f"CUDAExecutionProvider warm-up failed: {exc}"
                self.last_error = (
                    "CUDAExecutionProvider was requested for Post-Fall V2 binary inference, "
                    f"but warm-up failed: {exc}"
                )
                logger.warning(
                    "post_fall_v2_binary_cuda_warmup_failed requested=%s available=%s error=%s",
                    self.providers,
                    self.available_providers,
                    exc,
                )
                raise FallBinaryClassifierError(self.last_error) from exc
            raise
        timings["total"] = round((time.monotonic() - load_started) * 1000, 2)
        self.load_timings_ms = timings
        self.loaded = True
        self.last_error = None
        model_log_bus.publish(
            "binary",
            "binary_model_loaded",
            model_path=str(self.model_path),
            provider=self.provider,
            sha256=self.model_sha256,
            warmup_runs=self.warmup_runs,
            timings_ms=self.load_timings_ms,
        )

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

    def _warmup(self, input_meta) -> None:
        if self._session is None or self.warmup_runs <= 0:
            return
        shape = []
        for index, dim in enumerate(input_meta.shape):
            if isinstance(dim, int) and dim > 0:
                shape.append(dim)
            elif index == 0:
                shape.append(1)
            elif index == 1:
                shape.append(3)
            else:
                shape.append(224)
        dummy = np.zeros(shape, dtype=np.float32)
        for _ in range(self.warmup_runs):
            self._session.run(None, {input_meta.name: dummy})

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
