from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.identity.schemas import FaceEmbedding, IdentityProfile


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class IdentityStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        person_id: str,
        person_name: str,
        images: list[bytes],
        embeddings: list[FaceEmbedding],
        model_name: str | None,
        replace_existing: bool = False,
    ) -> IdentityProfile:
        safe_person_id = self._validate_person_id(person_id)
        person_dir = self.root_dir / safe_person_id
        if person_dir.exists() and not replace_existing:
            raise FileExistsError(f"identity already exists: {safe_person_id}")

        old_profile = self.get(safe_person_id) if person_dir.exists() else None
        if person_dir.exists():
            shutil.rmtree(person_dir)

        faces_dir = person_dir / "faces"
        faces_dir.mkdir(parents=True, exist_ok=True)
        for index, image_bytes in enumerate(images, start=1):
            (faces_dir / f"{index:03d}.jpg").write_bytes(image_bytes)

        matrix = np.asarray([item.embedding for item in embeddings], dtype=np.float32)
        matrix = self._l2_normalize_rows(matrix)
        np.save(person_dir / "embeddings.npy", matrix)

        now = utc_now_iso()
        profile = IdentityProfile(
            person_id=safe_person_id,
            person_name=person_name,
            embedding_count=int(matrix.shape[0]),
            model_name=model_name,
            created_at=old_profile.created_at if old_profile else now,
            updated_at=now,
        )
        (person_dir / "profile.json").write_text(
            json.dumps(profile.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return profile

    def list(self) -> list[IdentityProfile]:
        entries: list[IdentityProfile] = []
        for profile_path in sorted(self.root_dir.glob("*/profile.json")):
            try:
                entries.append(IdentityProfile(**json.loads(profile_path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return entries

    def get(self, person_id: str) -> IdentityProfile | None:
        safe_person_id = self._validate_person_id(person_id)
        profile_path = self.root_dir / safe_person_id / "profile.json"
        if not profile_path.exists():
            return None
        return IdentityProfile(**json.loads(profile_path.read_text(encoding="utf-8")))

    def load_all_embeddings(self) -> list[tuple[IdentityProfile, np.ndarray]]:
        rows: list[tuple[IdentityProfile, np.ndarray]] = []
        for profile in self.list():
            path = self.root_dir / profile.person_id / "embeddings.npy"
            if path.exists():
                rows.append((profile, np.load(path).astype(np.float32)))
        return rows

    def delete(self, person_id: str) -> bool:
        safe_person_id = self._validate_person_id(person_id)
        person_dir = self.root_dir / safe_person_id
        if not person_dir.exists():
            return False
        shutil.rmtree(person_dir)
        return True

    def count(self) -> int:
        return len(self.list())

    @staticmethod
    def _validate_person_id(person_id: str) -> str:
        value = person_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("person_id must match [A-Za-z0-9_-]{1,64}")
        return value

    @staticmethod
    def _l2_normalize_rows(matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            raise ValueError("embedding matrix is empty")
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ValueError("embedding matrix contains zero vector")
        return matrix / norms
