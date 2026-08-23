from __future__ import annotations

from collections import deque
from pathlib import Path
from threading import RLock
from typing import Any

import numpy as np
import torch

from scripts.showcase_legacy.fall_pose_tcn_model import FallPoseTCNModel


class FallPoseSequenceService:
    """Demo-only pose-sequence fall classifier copied for isolated showcase use."""

    def __init__(self, *, weights_path: Path, sequence_length: int = 32) -> None:
        self._weights_path = weights_path
        self._sequence_length = sequence_length
        self._lock = RLock()
        self._loaded = False
        self._load_error: str | None = None
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._model: FallPoseTCNModel | None = None
        self._session_windows: dict[str, deque[np.ndarray]] = {}

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self._loaded,
            "load_error": self._load_error,
            "weights_path": str(self._weights_path),
            "sequence_length": self._sequence_length,
            "device": str(self._device),
        }

    def predict_sequence(self, sequence: list[list[float]] | np.ndarray) -> dict[str, Any]:
        try:
            self._ensure_loaded()
            array = np.asarray(sequence, dtype=np.float32)
            if array.ndim != 2:
                return self._not_ready("INVALID_SEQUENCE")
            if array.shape[0] < self._sequence_length:
                return self._not_ready("SEQUENCE_TOO_SHORT")
            array = array[-self._sequence_length :]
            assert self._model is not None
            tensor = torch.from_numpy(array).unsqueeze(0).to(self._device)
            with torch.inference_mode():
                probability = float(self._model.predict_proba(tensor).item())
            return {
                "ok": True,
                "ready": True,
                "fall_probability": round(probability, 4),
                "status": "fall" if probability >= 0.65 else "suspected" if probability >= 0.45 else "normal",
                "model": self.status(),
            }
        except Exception as exc:
            self._load_error = f"{exc.__class__.__name__}: {exc}"
            return {
                "ok": False,
                "ready": False,
                "status": "model_unavailable",
                "fall_probability": 0.0,
                "error": self._load_error,
            }

    def push_frame(self, features: list[float] | np.ndarray, *, session_id: str = "default") -> dict[str, Any]:
        vector = np.asarray(features, dtype=np.float32).reshape(-1)
        with self._lock:
            window = self._session_windows.setdefault(session_id, deque(maxlen=self._sequence_length))
            window.append(vector)
            if len(window) < self._sequence_length:
                return self._not_ready("WARMING_UP", observed_frames=len(window))
            sequence = np.stack(list(window), axis=0)
        return self.predict_sequence(sequence)

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if not self._weights_path.exists():
                raise FileNotFoundError(self._weights_path)
            self._model = FallPoseTCNModel.load(self._weights_path, map_location=self._device)
            self._loaded = True
            self._load_error = None

    def _not_ready(self, reason: str, *, observed_frames: int = 0) -> dict[str, Any]:
        return {
            "ok": True,
            "ready": False,
            "status": "warming",
            "fall_probability": 0.0,
            "reason": reason,
            "observed_frames": observed_frames,
            "model": self.status(),
        }
