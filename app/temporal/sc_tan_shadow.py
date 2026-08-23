from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from app.schemas.vision_result import DetectedObject
from app.temporal.schemas import SequencePrediction, TargetFeature, TemporalV6Scores


SC_TAN_FEATURE_NAMES = [
    "person_confidence",
    "fall_hint_confidence",
    "hint_falling",
    "hint_fallen",
    "hint_lying",
    "hint_sitting",
    "hint_bending",
    "hint_kneeling",
    "hint_standing",
    "bbox_aspect_ratio",
    "delta_y_norm",
    "velocity_y_norm",
    "speed_norm",
    "pose_available",
    "pose_confidence",
    "torso_angle_norm",
    "head_height_ratio",
    "hip_height_ratio",
    "low_posture",
    "stillness",
    "track_quality",
    "lstm_fall_probability",
    "fall_evidence_score",
    "adl_suppression_score",
    "floor_risk_score",
    "support_surface_score",
]

_FALLING_LABELS = {"falling"}
_FALLEN_LABELS = {"fall", "fallen"}
_ADL_LABELS = {"sitting", "bending", "kneeling"}
_LYING_LABELS = {"lying"}


@dataclass(frozen=True)
class SCTANShadowConfig:
    min_window: int = 8
    top_k: int = 5


class SCTANShadowFusion:
    """Production-safe SC-TAN shadow scorer.

    This class mirrors the proposed Scene-Constrained Temporal Attention
    Network interface without requiring a trained neural checkpoint. It uses
    the same feature schema and attention-style temporal pooling as the demo,
    but keeps the output advisory/shadow-only so the existing state machine
    remains the authority until a trained checkpoint is promoted.
    """

    def __init__(self, config: SCTANShadowConfig | None = None) -> None:
        self.config = config or SCTANShadowConfig()
        self.last_error: str | None = None

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
            rows = [
                self._feature_row(
                    target=target,
                    feature=feature,
                    prediction=prediction,
                    v6_scores=v6_scores,
                )
                for feature in window
            ]
            attention_scores = [self._attention_logit(row) for row in rows]
            attention = _softmax(attention_scores)
            context = _weighted_mean(rows, attention)
            raw_fall_risk = self._raw_fall_risk(context)
            adl_risk = self._adl_risk(context)
            fall_risk = self._scene_constrained_fall_risk(raw_fall_risk, adl_risk, context)
            uncertainty = self._uncertainty(
                fall_risk=fall_risk,
                context=context,
                window_size=len(window),
                pose_missing_ratio=self._pose_missing_ratio(rows),
            )
            top_frames = self._top_attention_frames(rows, attention)
            self.last_error = None
            return {
                "schema_version": "sc_tan_shadow.v1",
                "source": "sc_tan_shadow_fusion",
                "model_available": True,
                "mode": "deterministic_attention_shadow",
                "window_size": len(window),
                "window_ready": len(window) >= self.config.min_window,
                "feature_names": SC_TAN_FEATURE_NAMES,
                "fall_risk": round(fall_risk, 4),
                "raw_fall_risk": round(raw_fall_risk, 4),
                "adl_risk": round(adl_risk, 4),
                "uncertainty": round(uncertainty, 4),
                "decision_hint": self._decision_hint(fall_risk, adl_risk, uncertainty, len(window)),
                "top_attention_frames": top_frames,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        except Exception as exc:
            self.last_error = str(exc)
            return self._unavailable(f"sc_tan_shadow_failed:{exc}", started)

    def _feature_row(
        self,
        *,
        target: DetectedObject,
        feature: TargetFeature,
        prediction: SequencePrediction,
        v6_scores: TemporalV6Scores | None,
    ) -> dict[str, float]:
        fall_hint = _fall_hint_payload(target)
        strongest_label = str(fall_hint.get("strongest_label") or fall_hint.get("label") or "").lower()
        hint_confidence = _clip01(_float(fall_hint.get("confidence"), 0.0))
        bbox_height = max(float(feature.bbox_height), 1.0)
        low_posture = _low_posture(feature)
        stillness = _clip01(1.0 - (float(feature.speed) / 45.0))
        floor_risk = 0.0
        support_surface = 0.0
        track_quality = 1.0
        fall_evidence = 0.0
        adl_suppression = 0.0
        if v6_scores is not None:
            floor_risk = _clip01(v6_scores.scene.floor_risk_score)
            support_surface = _clip01(v6_scores.scene.support_surface_score)
            track_quality = _clip01(v6_scores.motion.track_quality_score)
            fall_evidence = _clip01(v6_scores.fall.fall_evidence_score)
            adl_suppression = _clip01(v6_scores.adl.adl_suppression_score)

        return {
            "person_confidence": _clip01(feature.object_confidence),
            "fall_hint_confidence": hint_confidence,
            "hint_falling": 1.0 if strongest_label in _FALLING_LABELS else 0.0,
            "hint_fallen": 1.0 if strongest_label in _FALLEN_LABELS else 0.0,
            "hint_lying": 1.0 if strongest_label in _LYING_LABELS else 0.0,
            "hint_sitting": 1.0 if strongest_label == "sitting" else 0.0,
            "hint_bending": 1.0 if strongest_label == "bending" else 0.0,
            "hint_kneeling": 1.0 if strongest_label == "kneeling" else 0.0,
            "hint_standing": 1.0 if strongest_label == "standing" else 0.0,
            "bbox_aspect_ratio": _clip(float(feature.aspect_ratio) / 2.2, 0.0, 1.5),
            "delta_y_norm": _clip(float(feature.delta_y) / bbox_height, -1.0, 2.5),
            "velocity_y_norm": _clip(float(feature.velocity_y) / bbox_height, -2.0, 4.0),
            "speed_norm": _clip(float(feature.speed) / bbox_height, 0.0, 4.0),
            "pose_available": 1.0 if feature.pose_available else 0.0,
            "pose_confidence": _clip01(feature.pose_confidence),
            "torso_angle_norm": _clip((float(feature.torso_angle) if feature.torso_angle is not None else 0.0) / 90.0, -1.0, 1.0),
            "head_height_ratio": _clip(float(feature.head_height_ratio) if feature.head_height_ratio is not None else -1.0, -1.0, 2.0),
            "hip_height_ratio": _clip(float(feature.hip_height_ratio) if feature.hip_height_ratio is not None else -1.0, -1.0, 2.0),
            "low_posture": 1.0 if low_posture else 0.0,
            "stillness": stillness,
            "track_quality": track_quality,
            "lstm_fall_probability": _clip01(prediction.fall_probability),
            "fall_evidence_score": fall_evidence,
            "adl_suppression_score": adl_suppression,
            "floor_risk_score": floor_risk,
            "support_surface_score": support_surface,
        }

    @staticmethod
    def _attention_logit(row: dict[str, float]) -> float:
        fall_hint = max(row["hint_falling"], row["hint_fallen"]) * row["fall_hint_confidence"]
        rapid_motion = max(0.0, row["delta_y_norm"]) * 0.55 + max(0.0, row["velocity_y_norm"]) * 0.35
        posture = row["low_posture"] * 0.60 + row["bbox_aspect_ratio"] * 0.25
        return (
            1.15 * row["fall_evidence_score"]
            + 0.95 * row["lstm_fall_probability"]
            + 0.80 * fall_hint
            + 0.65 * rapid_motion
            + 0.45 * posture
            + 0.30 * row["floor_risk_score"]
            - 0.55 * row["adl_suppression_score"]
            - 0.35 * row["support_surface_score"]
        )

    @staticmethod
    def _raw_fall_risk(context: dict[str, float]) -> float:
        fall_hint = max(context["hint_falling"], context["hint_fallen"]) * context["fall_hint_confidence"]
        logit = (
            -3.20
            + 2.15 * context["fall_evidence_score"]
            + 1.45 * context["lstm_fall_probability"]
            + 1.25 * fall_hint
            + 0.90 * max(0.0, context["velocity_y_norm"])
            + 0.75 * context["low_posture"]
            + 0.55 * context["stillness"]
            - 1.15 * context["adl_suppression_score"]
            - 0.85 * context["support_surface_score"]
        )
        return _sigmoid(logit)

    @staticmethod
    def _adl_risk(context: dict[str, float]) -> float:
        adl_hint = max(context["hint_sitting"], context["hint_bending"], context["hint_kneeling"], context["hint_lying"] * 0.65)
        logit = (
            -2.10
            + 2.00 * context["adl_suppression_score"]
            + 1.35 * context["support_surface_score"]
            + 1.10 * adl_hint * context["fall_hint_confidence"]
            + 0.55 * context["stillness"]
            - 0.85 * max(0.0, context["velocity_y_norm"])
            - 0.65 * context["fall_evidence_score"]
        )
        return _sigmoid(logit)

    @staticmethod
    def _scene_constrained_fall_risk(raw_fall_risk: float, adl_risk: float, context: dict[str, float]) -> float:
        constrained = (
            _logit(_clip(raw_fall_risk, 1e-4, 1.0 - 1e-4))
            + 0.80 * context["floor_risk_score"]
            - 0.65 * context["support_surface_score"]
            - 0.35 * adl_risk
        )
        return _sigmoid(constrained)

    def _uncertainty(
        self,
        *,
        fall_risk: float,
        context: dict[str, float],
        window_size: int,
        pose_missing_ratio: float,
    ) -> float:
        boundary = 1.0 - min(abs(fall_risk - 0.5) * 2.0, 1.0)
        warmup = 1.0 - min(window_size / max(1, self.config.min_window), 1.0)
        track_penalty = 1.0 - context["track_quality"]
        return _clip01(0.08 + 0.24 * boundary + 0.22 * pose_missing_ratio + 0.24 * warmup + 0.22 * track_penalty)

    def _top_attention_frames(self, rows: list[dict[str, float]], attention: list[float]) -> list[dict[str, float | int]]:
        ranked = sorted(range(len(attention)), key=lambda idx: attention[idx], reverse=True)
        top: list[dict[str, float | int]] = []
        for idx in ranked[: max(1, self.config.top_k)]:
            row = rows[idx]
            top.append(
                {
                    "frame_index": idx,
                    "attention": round(attention[idx], 4),
                    "fall_evidence_score": round(row["fall_evidence_score"], 4),
                    "adl_suppression_score": round(row["adl_suppression_score"], 4),
                    "floor_risk_score": round(row["floor_risk_score"], 4),
                    "support_surface_score": round(row["support_surface_score"], 4),
                }
            )
        return top

    @staticmethod
    def _pose_missing_ratio(rows: list[dict[str, float]]) -> float:
        if not rows:
            return 1.0
        missing = sum(1 for row in rows if row["pose_available"] < 0.5)
        return missing / len(rows)

    def _decision_hint(self, fall_risk: float, adl_risk: float, uncertainty: float, window_size: int) -> str:
        if window_size < self.config.min_window:
            return "warming_up"
        if uncertainty >= 0.45:
            return "need_review"
        if fall_risk >= 0.72 and adl_risk < 0.45:
            return "fall_candidate"
        if adl_risk >= 0.60 and fall_risk < 0.55:
            return "adl_suppressed"
        if fall_risk >= 0.45:
            return "observe"
        return "normal"

    @staticmethod
    def _unavailable(reason: str, started: float) -> dict[str, Any]:
        return {
            "schema_version": "sc_tan_shadow.v1",
            "source": "sc_tan_shadow_fusion",
            "model_available": False,
            "mode": "deterministic_attention_shadow",
            "window_ready": False,
            "reason": reason,
            "fall_risk": 0.0,
            "raw_fall_risk": 0.0,
            "adl_risk": 0.0,
            "uncertainty": 1.0,
            "decision_hint": "unavailable",
            "top_attention_frames": [],
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }


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


def _weighted_mean(rows: list[dict[str, float]], weights: list[float]) -> dict[str, float]:
    result: dict[str, float] = {}
    for name in SC_TAN_FEATURE_NAMES:
        result[name] = sum(row[name] * weight for row, weight in zip(rows, weights))
    return result


def _softmax(values: list[float]) -> list[float]:
    if not values:
        return []
    max_value = max(values)
    exps = [math.exp(value - max_value) for value in values]
    denom = sum(exps) or 1.0
    return [value / denom for value in exps]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _logit(value: float) -> float:
    value = _clip(value, 1e-6, 1.0 - 1e-6)
    return math.log(value / (1.0 - value))


def _float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip01(value: float) -> float:
    return _clip(value, 0.0, 1.0)


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))
