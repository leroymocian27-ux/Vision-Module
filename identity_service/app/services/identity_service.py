from __future__ import annotations

from app.core.config import Settings
from app.core.logger import get_logger
from app.identity.identity_store import IdentityStore
from app.identity.insightface_recognizer import InsightFaceRecognizer
from app.identity.matcher import IdentityMatcher
from app.identity.schemas import EnrollResult, HealthStatus, IdentityProfile, MatchResult

logger = get_logger(__name__)


class IdentityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = IdentityStore(settings.identity_store_dir)
        self.recognizer = InsightFaceRecognizer(settings)
        self.matcher = IdentityMatcher(self.store)
        self._last_error: str | None = self.recognizer.status().last_error

    def health(self) -> HealthStatus:
        recognizer_status = self.recognizer.status()
        return HealthStatus(
            status="ok",
            recognizer_loaded=recognizer_status.recognizer_loaded,
            recognizer_name=recognizer_status.recognizer_name,
            model_name=recognizer_status.model_name,
            registered_count=self.store.count(),
            last_error=self._last_error or recognizer_status.last_error,
        )

    def enroll(
        self,
        person_id: str,
        person_name: str,
        images: list[bytes],
        replace_existing: bool = False,
    ) -> EnrollResult:
        self._validate_image_count(images)
        embeddings = self.recognizer.extract_embeddings(images)
        if not embeddings:
            self._last_error = "no face detected in uploaded images"
            raise ValueError(self._last_error)

        profile = self.store.save(
            person_id=person_id,
            person_name=person_name,
            images=images,
            embeddings=embeddings,
            model_name=self.recognizer.status().model_name,
            replace_existing=replace_existing,
        )
        self._last_error = None
        logger.info("identity_enrolled person_id=%s embeddings=%s", profile.person_id, profile.embedding_count)
        return EnrollResult(
            person_id=profile.person_id,
            person_name=profile.person_name,
            faces_registered=profile.embedding_count,
            embedding_count=profile.embedding_count,
            model_name=profile.model_name,
        )

    def match(self, image: bytes, threshold: float | None = None) -> MatchResult:
        embeddings = self.recognizer.extract_embeddings([image])
        if not embeddings:
            self._last_error = "no face detected in uploaded image"
            raise ValueError(self._last_error)
        threshold = self.settings.match_threshold if threshold is None else threshold
        result = self.matcher.match(
            embedding=embeddings[0].embedding,
            threshold=threshold,
            model_name=self.recognizer.status().model_name,
        )
        self._last_error = None
        return result

    def list_identities(self) -> list[IdentityProfile]:
        return self.store.list()

    def delete(self, person_id: str) -> bool:
        deleted = self.store.delete(person_id)
        if deleted:
            logger.info("identity_deleted person_id=%s", person_id)
        return deleted

    def _validate_image_count(self, images: list[bytes]) -> None:
        if not 1 <= len(images) <= self.settings.identity_max_images:
            raise ValueError(f"upload 1-{self.settings.identity_max_images} face images")
