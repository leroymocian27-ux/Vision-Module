from __future__ import annotations

from pydantic import BaseModel, Field


class FaceEmbedding(BaseModel):
    embedding: list[float]
    face_index: int
    image_index: int
    bbox: list[float] | None = Field(default=None, description="[x1, y1, x2, y2]")


class FaceRecognizerStatus(BaseModel):
    enabled: bool
    loaded: bool = False
    recognizer_name: str = "insightface"
    model_name: str | None = None
    last_error: str | None = None


class IdentityProfile(BaseModel):
    person_id: str
    person_name: str
    embedding_count: int
    model_name: str | None = None
    created_at: str
    updated_at: str


class IdentityStoreEntry(BaseModel):
    person_id: str
    person_name: str
    embedding_count: int
    model_name: str | None = None
    created_at: str
    updated_at: str


class EnrollResult(BaseModel):
    person_id: str
    person_name: str
    faces_registered: int
    status: str = "success"
