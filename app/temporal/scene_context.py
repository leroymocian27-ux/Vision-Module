from __future__ import annotations

from pydantic import BaseModel


SUPPORT_SURFACE_TYPES = {
    "bed",
    "sofa",
    "chair",
    "nursing_bed",
    "rest_mat",
    "support_surface",
    "support_surface_zone",
}

SUPPORT_SCENE_TYPES = {
    "support_surface_zone",
    "chair_or_support_zone",
    "bed_zone",
    "sofa_zone",
}

FLOOR_RISK_SCENE_TYPES = {
    "floor_risk_zone",
    "floor_risk_area",
    "adl_floor_or_mixed_zone",
}


class SceneContext(BaseModel):
    scene_type: str | None = None
    support_surface: str | None = None
    support_surface_score: float = 0.0
    floor_risk_score: float = 0.0
    reasons: list[str] = []


class SceneContextResolver:
    @classmethod
    def from_payload(cls, payload: dict | None) -> SceneContext:
        if not isinstance(payload, dict):
            return SceneContext()
        raw = payload.get("scene_context") if isinstance(payload.get("scene_context"), dict) else payload
        if not isinstance(raw, dict):
            return SceneContext()
        scene_type = cls._norm(raw.get("scene_type"))
        support_surface = cls._norm(raw.get("support_surface"))
        support_score = cls._support_surface_score(scene_type, support_surface)
        floor_score = cls._floor_risk_score(scene_type)
        reasons: list[str] = []
        if support_score >= 0.60:
            reasons.append("support_surface_context")
        if floor_score >= 0.60:
            reasons.append("floor_risk_zone_context")
        return SceneContext(
            scene_type=scene_type,
            support_surface=support_surface,
            support_surface_score=support_score,
            floor_risk_score=floor_score,
            reasons=reasons,
        )

    @staticmethod
    def _support_surface_score(scene_type: str | None, support_surface: str | None) -> float:
        if support_surface in SUPPORT_SURFACE_TYPES:
            return 0.90
        if scene_type == "support_surface_zone":
            return 0.85
        if scene_type == "chair_or_support_zone":
            return 0.70
        if scene_type in SUPPORT_SCENE_TYPES:
            return 0.75
        return 0.0

    @staticmethod
    def _floor_risk_score(scene_type: str | None) -> float:
        if scene_type in FLOOR_RISK_SCENE_TYPES:
            return 1.0
        return 0.0

    @staticmethod
    def _norm(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower()
        return text or None
