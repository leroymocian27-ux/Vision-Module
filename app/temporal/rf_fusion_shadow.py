from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.schemas.vision_result import DetectedObject
from app.temporal.schemas import SequencePrediction, TargetFeature, TemporalV6Scores


RF_FUSION_FEATURE_NAMES = [
    "lstm_fall_probability",
    "fall_evidence_score",
    "adl_suppression_score",
    "vertical_drop_score",
    "impact_proxy_score",
    "low_posture_score",
    "post_fall_stillness_score",
    "floor_contact_score",
    "floor_risk_score",
    "support_surface_score",
    "track_quality_score",
    "downward_velocity_score",
    "low_posture_duration_score",
    "recovery_score",
    "pose_available_ratio",
    "fall_hint_strength",
    "adl_hint_strength",
    "stillness_score",
    "aspect_ratio_score",
]

_FALL_HINT_LABELS = {"fall", "falling", "fallen"}
_ADL_HINT_LABELS = {"sitting", "bending", "kneeling", "lying"}


@dataclass(frozen=True)
class RFFusionShadowConfig:
    min_window: int = 8


@dataclass(frozen=True)
class _DecisionTree:
    name: str
    rules: tuple[tuple[str, str, float], ...]
    positive_vote: float
    negative_vote: float

    def predict(self, features: dict[str, float]) -> tuple[float, list[str]]:
        matched: list[str] = []
        for feature_name, op, threshold in self.rules:
            value = features.get(feature_name, 0.0)
            passed = value >= threshold if op == ">=" else value < threshold
            if not passed:
                return self.negative_vote, matched
            matched.append(feature_name)
        return self.positive_vote, matched


class RandomForestFusionShadow:
    """Production-safe random-forest style multi-evidence fusion scorer.

    The scorer is deliberately shadow-only: it runs inside the real temporal
    chain and produces an independent random-forest risk view, but the existing
    state machine remains the alarm authority until a trained/calibrated model
    is promoted.
    """

    def __init__(self, config: RFFusionShadowConfig | None = None) -> None:
        self.config = config or RFFusionShadowConfig()
        self.last_error: str | None = None
        self.fall_forest = self._build_fall_forest()
        self.adl_forest = self._build_adl_forest()

    def predict(
        self,
        *,
        target: DetectedObject,
        window: list[TargetFeature],
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if not window:
                return self._unavailable("empty_window", started)
            features = self._features(
                target=target,
                window=window,
                prediction=prediction,
                v6_scores=v6_scores,
            )
            fall_risk, fall_votes = self._predict_forest(self.fall_forest, features)
            adl_risk, adl_votes = self._predict_forest(self.adl_forest, features)
            fall_risk = _clip01(fall_risk - 0.18 * adl_risk - 0.12 * features["support_surface_score"])
            uncertainty = self._uncertainty(
                fall_risk=fall_risk,
                adl_risk=adl_risk,
                features=features,
                window_size=len(window),
            )
            self.last_error = None
            return {
                "schema_version": "rf_fusion_shadow.v1",
                "source": "random_forest_multi_evidence_fusion",
                "model_available": True,
                "mode": "deterministic_expert_forest_shadow",
                "tree_count": len(self.fall_forest),
                "window_size": len(window),
                "window_ready": len(window) >= self.config.min_window,
                "feature_names": RF_FUSION_FEATURE_NAMES,
                "fall_risk": round(fall_risk, 4),
                "adl_risk": round(adl_risk, 4),
                "uncertainty": round(uncertainty, 4),
                "decision_hint": self._decision_hint(fall_risk, adl_risk, uncertainty, len(window)),
                "top_feature_votes": self._top_feature_votes([*fall_votes, *adl_votes]),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except Exception as exc:
            self.last_error = str(exc)
            return self._unavailable(f"rf_fusion_shadow_failed:{exc}", started)

    def _features(
        self,
        *,
        target: DetectedObject,
        window: list[TargetFeature],
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None,
    ) -> dict[str, float]:
        latest = window[-1]
        fall_hint = _fall_hint_payload(target)
        label = str(fall_hint.get("strongest_label") or fall_hint.get("label") or "").lower()
        hint_confidence = _clip01(_float(fall_hint.get("confidence"), 0.0))
        pose_available_ratio = sum(1 for item in window if item.pose_available) / max(1, len(window))
        aspect_ratio_score = _clip01((float(latest.aspect_ratio) - 0.65) / 0.90)
        stillness_score = _clip01(1.0 - float(latest.speed) / 45.0)
        features = {
            "lstm_fall_probability": _clip01(prediction.fall_probability),
            "fall_evidence_score": 0.0,
            "adl_suppression_score": 0.0,
            "vertical_drop_score": 0.0,
            "impact_proxy_score": 0.0,
            "low_posture_score": 1.0 if _low_posture(latest) else aspect_ratio_score,
            "post_fall_stillness_score": stillness_score,
            "floor_contact_score": 0.0,
            "floor_risk_score": 0.0,
            "support_surface_score": 0.0,
            "track_quality_score": 1.0,
            "downward_velocity_score": _clip01(max((item.velocity_y for item in window), default=0.0) / 600.0),
            "low_posture_duration_score": 0.0,
            "recovery_score": 0.0,
            "pose_available_ratio": pose_available_ratio,
            "fall_hint_strength": hint_confidence if label in _FALL_HINT_LABELS else 0.0,
            "adl_hint_strength": hint_confidence if label in _ADL_HINT_LABELS else 0.0,
            "stillness_score": stillness_score,
            "aspect_ratio_score": aspect_ratio_score,
        }
        if v6_scores is not None:
            features.update(
                {
                    "fall_evidence_score": _clip01(v6_scores.fall.fall_evidence_score),
                    "adl_suppression_score": _clip01(v6_scores.adl.adl_suppression_score),
                    "vertical_drop_score": _clip01(v6_scores.fall.vertical_drop_score),
                    "impact_proxy_score": _clip01(v6_scores.fall.impact_proxy_score),
                    "low_posture_score": _clip01(v6_scores.fall.low_posture_score),
                    "post_fall_stillness_score": _clip01(v6_scores.fall.post_fall_stillness_score),
                    "floor_contact_score": _clip01(v6_scores.fall.floor_contact_score),
                    "floor_risk_score": _clip01(v6_scores.scene.floor_risk_score),
                    "support_surface_score": _clip01(v6_scores.scene.support_surface_score),
                    "track_quality_score": _clip01(v6_scores.motion.track_quality_score),
                    "downward_velocity_score": _clip01(v6_scores.motion.max_downward_velocity_16f / 600.0),
                    "low_posture_duration_score": _clip01(v6_scores.motion.low_posture_duration_ms / 1500.0),
                    "recovery_score": _clip01(v6_scores.adl.recovery_score),
                }
            )
        return features

    @staticmethod
    def _predict_forest(forest: tuple[_DecisionTree, ...], features: dict[str, float]) -> tuple[float, list[str]]:
        if not forest:
            return 0.0, []
        votes: list[float] = []
        matched_features: list[str] = []
        for tree in forest:
            vote, matched = tree.predict(features)
            votes.append(vote)
            matched_features.extend(matched)
        return sum(votes) / len(votes), matched_features

    @staticmethod
    def _uncertainty(
        *,
        fall_risk: float,
        adl_risk: float,
        features: dict[str, float],
        window_size: int,
    ) -> float:
        boundary = 1.0 - min(abs(fall_risk - 0.5) * 2.0, 1.0)
        fall_adl_conflict = min(fall_risk, adl_risk)
        warmup = 1.0 - min(window_size / 8.0, 1.0)
        track_penalty = 1.0 - features["track_quality_score"]
        pose_penalty = 1.0 - features["pose_available_ratio"]
        return _clip01(0.08 + 0.25 * boundary + 0.20 * fall_adl_conflict + 0.20 * warmup + 0.18 * track_penalty + 0.09 * pose_penalty)

    def _decision_hint(self, fall_risk: float, adl_risk: float, uncertainty: float, window_size: int) -> str:
        if window_size < self.config.min_window:
            return "warming_up"
        if uncertainty >= 0.45:
            return "need_review"
        if fall_risk >= 0.70 and adl_risk < 0.45:
            return "fall_candidate"
        if adl_risk >= 0.60 and fall_risk < 0.55:
            return "adl_suppressed"
        if fall_risk >= 0.45:
            return "observe"
        return "normal"

    @staticmethod
    def _top_feature_votes(features: list[str]) -> list[dict[str, int | str]]:
        counts: dict[str, int] = {}
        for feature in features:
            counts[feature] = counts.get(feature, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [{"feature": feature, "votes": votes} for feature, votes in ranked[:5]]

    @staticmethod
    def _unavailable(reason: str, started: float) -> dict[str, Any]:
        return {
            "schema_version": "rf_fusion_shadow.v1",
            "source": "random_forest_multi_evidence_fusion",
            "model_available": False,
            "mode": "deterministic_expert_forest_shadow",
            "window_ready": False,
            "reason": reason,
            "fall_risk": 0.0,
            "adl_risk": 0.0,
            "uncertainty": 1.0,
            "decision_hint": "unavailable",
            "top_feature_votes": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }

    @staticmethod
    def _build_fall_forest() -> tuple[_DecisionTree, ...]:
        return (
            _DecisionTree("lstm_evidence_grounded", (("lstm_fall_probability", ">=", 0.55), ("fall_evidence_score", ">=", 0.55), ("adl_suppression_score", "<", 0.55)), 0.86, 0.18),
            _DecisionTree("rapid_impact_floor", (("vertical_drop_score", ">=", 0.60), ("impact_proxy_score", ">=", 0.50), ("floor_risk_score", ">=", 0.50)), 0.90, 0.16),
            _DecisionTree("fall_hint_low_posture", (("fall_hint_strength", ">=", 0.35), ("low_posture_score", ">=", 0.55), ("track_quality_score", ">=", 0.55)), 0.80, 0.20),
            _DecisionTree("ground_contact_hold", (("floor_contact_score", ">=", 0.45), ("post_fall_stillness_score", ">=", 0.55), ("support_surface_score", "<", 0.45)), 0.82, 0.22),
            _DecisionTree("motion_only_guarded", (("downward_velocity_score", ">=", 0.35), ("low_posture_duration_score", ">=", 0.35), ("adl_suppression_score", "<", 0.45)), 0.74, 0.20),
            _DecisionTree("scene_floor_not_adl", (("floor_risk_score", ">=", 0.80), ("fall_evidence_score", ">=", 0.50), ("adl_hint_strength", "<", 0.25)), 0.72, 0.24),
            _DecisionTree("pose_low_still", (("pose_available_ratio", ">=", 0.25), ("low_posture_score", ">=", 0.70), ("stillness_score", ">=", 0.55)), 0.70, 0.26),
            _DecisionTree("recovery_blocks_fall", (("recovery_score", "<", 0.40), ("fall_evidence_score", ">=", 0.65)), 0.78, 0.18),
            _DecisionTree("support_surface_guard", (("support_surface_score", "<", 0.50), ("impact_proxy_score", ">=", 0.45), ("adl_suppression_score", "<", 0.50)), 0.76, 0.15),
        )

    @staticmethod
    def _build_adl_forest() -> tuple[_DecisionTree, ...]:
        return (
            _DecisionTree("explicit_adl_hint", (("adl_hint_strength", ">=", 0.35), ("support_surface_score", ">=", 0.45)), 0.88, 0.18),
            _DecisionTree("adl_suppression_support", (("adl_suppression_score", ">=", 0.60), ("support_surface_score", ">=", 0.45)), 0.86, 0.20),
            _DecisionTree("controlled_no_impact", (("adl_suppression_score", ">=", 0.50), ("impact_proxy_score", "<", 0.45), ("vertical_drop_score", "<", 0.55)), 0.78, 0.22),
            _DecisionTree("recovery_adl", (("recovery_score", ">=", 0.45), ("fall_evidence_score", "<", 0.75)), 0.76, 0.20),
            _DecisionTree("lying_surface", (("adl_hint_strength", ">=", 0.25), ("floor_risk_score", "<", 0.45), ("support_surface_score", ">=", 0.55)), 0.82, 0.18),
        )


def _fall_hint_payload(target: DetectedObject) -> dict[str, Any]:
    features = target.features if isinstance(target.features, dict) else {}
    payload = features.get("fall_hint") if isinstance(features.get("fall_hint"), dict) else {}
    return payload


def _low_posture(feature: TargetFeature) -> bool:
    return feature.aspect_ratio >= 0.95 or (
        feature.head_height_ratio is not None
        and feature.head_height_ratio > 0.45
        and feature.hip_height_ratio is not None
        and feature.hip_height_ratio > 0.65
    )


def _float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
