from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.logger import get_logger
from app.identity.identity_store import IdentityStore
from app.identity.insightface_recognizer import InsightFaceRecognizer
from app.identity.schemas import EnrollResult, FaceRecognizerStatus, IdentityStoreEntry

logger = get_logger(__name__)


@dataclass
class IdentityServiceStatus:
    identity_enabled: bool
    recognizer_loaded: bool
    recognizer_name: str | None
    model_name: str | None
    registered_count: int
    last_error: str | None = None


class IdentityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = IdentityStore(settings.identity_store_dir)
        self.recognizer = InsightFaceRecognizer(settings)
        self._last_error: str | None = self.recognizer.status().last_error

    def enroll(
        self,
        person_id: str,
        person_name: str,
        images: list[bytes],
        replace_existing: bool = False,
    ) -> EnrollResult:
        if not self.settings.enable_identity:
            raise RuntimeError("identity subsystem is disabled")
        if not 1 <= len(images) <= self.settings.identity_max_images:
            raise ValueError(f"upload 1-{self.settings.identity_max_images} face images")

        status = self.recognizer.status()
        embeddings = self.recognizer.extract_embeddings(images)
        if not embeddings:
            self._last_error = "no face detected in uploaded images"
            raise ValueError(self._last_error)

        profile = self.store.save(
            person_id=person_id,
            person_name=person_name,
            images=images,
            embeddings=embeddings,
            model_name=status.model_name,
            replace_existing=replace_existing,
        )
        self._last_error = None
        logger.info(
            "identity_enrolled person_id=%s faces_registered=%s replace_existing=%s",
            profile.person_id,
            profile.embedding_count,
            replace_existing,
        )
        return EnrollResult(
            person_id=profile.person_id,
            person_name=profile.person_name,
            faces_registered=profile.embedding_count,
        )

    def list_identities(self) -> list[IdentityStoreEntry]:
        return self.store.list()

    def delete(self, person_id: str) -> bool:
        deleted = self.store.delete(person_id)
        if deleted:
            logger.info("identity_deleted person_id=%s", person_id)
        return deleted

    def status(self) -> IdentityServiceStatus:
        recognizer_status: FaceRecognizerStatus = self.recognizer.status()
        return IdentityServiceStatus(
            identity_enabled=self.settings.enable_identity,
            recognizer_loaded=recognizer_status.loaded,
            recognizer_name=recognizer_status.recognizer_name,
            model_name=recognizer_status.model_name,
            registered_count=self.store.count(),
            last_error=self._last_error or recognizer_status.last_error,
        )
