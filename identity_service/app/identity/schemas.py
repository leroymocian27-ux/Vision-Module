from __future__ import annotations

from pydantic import BaseModel, Field


class FaceEmbedding(BaseModel):
    embedding: list[float]
    image_index: int
    face_index: int = 1
    bbox: list[float] | None = Field(default=None, description="[x1, y1, x2, y2]")


class FaceRecognizerStatus(BaseModel):
    recognizer_loaded: bool = False
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


class EnrollResult(BaseModel):
    person_id: str
    person_name: str
    faces_registered: int
    embedding_count: int
    model_name: str | None = None
    status: str = "success"


class MatchResult(BaseModel):
    matched: bool
    person_id: str | None = None
    person_name: str | None = None
    score: float | None = None
    threshold: float
    model_name: str | None = None


class HealthStatus(BaseModel):
    status: str = "ok"
    recognizer_loaded: bool = False
    recognizer_name: str = "insightface"
    model_name: str | None = None
    registered_count: int = 0
    last_error: str | None = None
