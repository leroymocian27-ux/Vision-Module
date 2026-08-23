from __future__ import annotations

import cv2
import numpy as np

from app.core.config import Settings
from app.core.logger import get_logger
from app.identity.schemas import FaceEmbedding, FaceRecognizerStatus

logger = get_logger(__name__)


class InsightFaceRecognizer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app = None
        self._status = FaceRecognizerStatus(
            enabled=settings.enable_identity,
            loaded=False,
            recognizer_name="insightface",
            model_name=settings.insightface_model_name,
        )
        if settings.enable_identity:
            self._load()

    def _load(self) -> None:
        try:
            from insightface.app import FaceAnalysis

            providers = self._providers()
            app = FaceAnalysis(name=self.settings.insightface_model_name, providers=providers)
            app.prepare(
                ctx_id=self.settings.insightface_ctx_id,
                det_size=(self.settings.insightface_det_size, self.settings.insightface_det_size),
            )
            self._app = app
            self._status.loaded = True
            self._status.last_error = None
            logger.info("insightface_loaded model=%s providers=%s", self.settings.insightface_model_name, providers)
        except Exception as exc:
            self._app = None
            self._status.loaded = False
            self._status.last_error = str(exc)
            logger.error("insightface_load_failed error=%s", exc)

    def extract_embeddings(self, images: list[bytes]) -> list[FaceEmbedding]:
        if not self.settings.enable_identity:
            raise RuntimeError("identity subsystem is disabled")
        if self._app is None:
            self._load()
        if self._app is None:
            raise RuntimeError(f"face recognizer unavailable: {self._status.last_error}")

        embeddings: list[FaceEmbedding] = []
        for image_index, image_bytes in enumerate(images, start=1):
            image = self._decode_image(image_bytes)
            faces = self._app.get(image)
            if not faces:
                continue

            face = max(faces, key=self._face_area)
            embedding = np.asarray(face.normed_embedding, dtype=np.float32)
            embedding = self._l2_normalize(embedding)
            bbox = [round(float(v), 2) for v in getattr(face, "bbox", [])]
            embeddings.append(
                FaceEmbedding(
                    embedding=embedding.tolist(),
                    face_index=1,
                    image_index=image_index,
                    bbox=bbox or None,
                )
            )
        return embeddings

    def status(self) -> FaceRecognizerStatus:
        return FaceRecognizerStatus(**self._status.model_dump())

    def _providers(self) -> list[str]:
        if self.settings.insightface_providers:
            return [item.strip() for item in self.settings.insightface_providers.split(",") if item.strip()]
        if self.settings.insightface_ctx_id >= 0:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    @staticmethod
    def _decode_image(image_bytes: bytes) -> np.ndarray:
        array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("invalid image file")
        return image

    @staticmethod
    def _l2_normalize(embedding: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(embedding))
        if norm <= 0:
            raise ValueError("invalid zero face embedding")
        return embedding / norm

    @staticmethod
    def _face_area(face) -> float:
        bbox = getattr(face, "bbox", None)
        if bbox is None or len(bbox) < 4:
            return 0.0
        x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
