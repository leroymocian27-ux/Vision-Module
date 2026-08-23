from __future__ import annotations

import numpy as np

from app.identity.identity_store import IdentityStore
from app.identity.schemas import MatchResult


class IdentityMatcher:
    def __init__(self, store: IdentityStore) -> None:
        self.store = store

    def match(
        self,
        embedding: list[float],
        threshold: float,
        model_name: str | None,
    ) -> MatchResult:
        query = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm <= 0:
            raise ValueError("invalid zero face embedding")
        query = query / norm

        best_profile = None
        best_score: float | None = None
        for profile, matrix in self.store.load_all_embeddings():
            if matrix.size == 0:
                continue
            scores = matrix @ query
            score = float(np.max(scores))
            if best_score is None or score > best_score:
                best_score = score
                best_profile = profile

        if best_profile is None or best_score is None:
            raise LookupError("identity store is empty")

        matched = best_score >= threshold
        return MatchResult(
            matched=matched,
            person_id=best_profile.person_id if matched else None,
            person_name=best_profile.person_name if matched else None,
            score=round(best_score, 4),
            threshold=threshold,
            model_name=model_name,
        )
