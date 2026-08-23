from __future__ import annotations

from dataclasses import dataclass

import requests

from app.core.config import Settings
from app.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IdentityHealth:
    available: bool
    recognizer_loaded: bool = False
    registered_count: int = 0
    last_error: str | None = None


@dataclass
class IdentityMatch:
    available: bool
    matched: bool = False
    person_id: str | None = None
    person_name: str | None = None
    score: float | None = None
    threshold: float | None = None
    last_error: str | None = None


class IdentityClient:
    """Small, fail-closed client for the standalone identity_service.

    This client is intentionally not wired into realtime tracking yet. Phase 2.3 can use it
    from a low-frequency identity binding workflow without risking the video path.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.identity_service_url.rstrip("/")
        self.timeout = max(settings.identity_request_timeout_ms, 1) / 1000

    def healthz(self) -> IdentityHealth:
        try:
            response = requests.get(f"{self.base_url}/healthz", timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            return IdentityHealth(
                available=True,
                recognizer_loaded=bool(payload.get("recognizer_loaded")),
                registered_count=int(payload.get("registered_count") or 0),
                last_error=payload.get("last_error"),
            )
        except Exception as exc:
            logger.warning("identity_service_unavailable error=%s", exc)
            return IdentityHealth(available=False, last_error=str(exc))

    def match(self, image_bytes: bytes, threshold: float | None = None) -> IdentityMatch:
        try:
            data = {}
            if threshold is not None:
                data["threshold"] = str(threshold)
            files = {"file": ("candidate.jpg", image_bytes, "image/jpeg")}
            response = requests.post(
                f"{self.base_url}/identity/match",
                data=data,
                files=files,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return IdentityMatch(
                available=True,
                matched=bool(payload.get("matched")),
                person_id=payload.get("person_id"),
                person_name=payload.get("person_name"),
                score=payload.get("score"),
                threshold=payload.get("threshold"),
            )
        except Exception as exc:
            logger.warning("identity_match_unavailable error=%s", exc)
            return IdentityMatch(available=False, last_error=str(exc))
