from __future__ import annotations

from typing import Protocol

from app.identity.schemas import FaceEmbedding, FaceRecognizerStatus


class FaceRecognizer(Protocol):
    def extract_embeddings(self, images: list[bytes]) -> list[FaceEmbedding]:
        raise NotImplementedError

    def status(self) -> FaceRecognizerStatus:
        raise NotImplementedError
