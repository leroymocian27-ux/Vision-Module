from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject


@dataclass(frozen=True)
class UnifiedFallScore:
    decision: dict[str, object]
    confidence_breakdown: dict[str, float]
    evidence_summary: dict[str, object]
    decision_trace: list[str]

    def model_payload(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "confidence_breakdown": self.confidence_breakdown,
            "evidence_summary": self.evidence_summary,
            "decision_trace": self.decision_trace,
        }


class UnifiedFallDecisionEngine:
    """Unified fall scorer with shadow output and an optional primary write-back."""

    SOURCE = "unified_fall_score_v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        if not self.settings.unified_decision_enabled:
            return objects
        return [self._enrich_one(camera_id, item) if item.label == "person" else item for item in objects]

    def evaluate(self, camera_id: str, item: DetectedObject) -> UnifiedFallScore:
        del camera_id
        features = item.features if isinstance(item.features, dict) else {}
        motion = features.get("motion") if isinstance(features.get("motion"), dict) else {}
        pose = features.get("pose") if isinstance(features.get("pose"), dict) else {}
        fall_hint = features.get("fall_hint") if isinstance(features.get("fall_hint"), dict) else {}
        temporal = item.temporal if isinstance(item.temporal, dict) else {}
        fusion_debug = item.fusion_debug if isinstance(item.fusion_debug, dict) else {}
        v6_scores = temporal.get("v6_scores") if isinstance(temporal.get("v6_scores"), dict) else {}
        v6_fall = v6_scores.get("fall") if isinstance(v6_scores.get("fall"), dict) else {}
        v6_adl = v6_scores.get("adl") if isinstance(v6_scores.get("adl"), dict) else {}

        visual = self._visual_fall_hint_score(fall_hint)
        temporal_lstm = self._temporal_score(item, temporal)
        motion_drop = self._motion_drop_score(motion, temporal, v6_fall)
        low_posture = self._low_posture_score(motion, pose, temporal, v6_fall)
        horizontal = self._horizontal_posture_score(motion, temporal, v6_fall)
        stillness = self._post_fall_stillness_score(motion, temporal, v6_fall)
        floor_contact = self._floor_contact_score(motion, v6_fall)
        track_stability = self._track_stability_score(item, motion)
        adl_suppression = self._adl_suppression_score(item, v6_adl)
        quality_penalty = self._quality_penalty(item, pose, fusion_debug, track_stability)

        raw = (
            0.18 * visual
            + 0.16 * temporal_lstm
            + 0.08 * motion_drop
            + 0.18 * low_posture
            + 0.14 * horizontal
            + 0.14 * stillness
            + 0.08 * floor_contact
            + 0.04 * track_stability
            - 0.18 * adl_suppression
            - 0.10 * quality_penalty
        )
        final_score = self._clamp(raw)

        confirm_frames, confirmed_duration_ms = self._confirmation_progress(item, fusion_debug)
        evidence_count = sum(
            [
                visual >= 0.55,
                temporal_lstm >= 0.55 or motion_drop >= 0.55,
                low_posture >= 0.60 or horizontal >= 0.60,
                stillness >= 0.55 or floor_contact >= 0.55,
            ]
        )
        required_evidence_passed = evidence_count >= 2
        track_stability_passed = track_stability >= 0.60
        adl_suppression_passed = adl_suppression < 0.55
        degraded = self._degraded(fusion_debug)
        status = self._status(
            final_score=final_score,
            visual=visual,
            motion_drop=motion_drop,
            low_posture=low_posture,
            required_evidence_passed=required_evidence_passed,
            track_stability_passed=track_stability_passed,
            adl_suppression=adl_suppression,
            confirm_frames=confirm_frames,
            confirmed_duration_ms=confirmed_duration_ms,
        )

        breakdown = {
            "visual_fall_hint_score": round(visual, 4),
            "temporal_lstm_score": round(temporal_lstm, 4),
            "motion_drop_score": round(motion_drop, 4),
            "low_posture_score": round(low_posture, 4),
            "horizontal_posture_score": round(horizontal, 4),
            "post_fall_stillness_score": round(stillness, 4),
            "floor_contact_score": round(floor_contact, 4),
            "track_stability_score": round(track_stability, 4),
            "adl_suppression_score": round(adl_suppression, 4),
            "quality_penalty": round(quality_penalty, 4),
            "raw_fall_score": round(raw, 4),
            "final_fall_score": round(final_score, 4),
        }
        summary = self._evidence_summary(
            item=item,
            motion=motion,
            pose=pose,
            fall_hint=fall_hint,
            temporal=temporal,
            track_stability=track_stability,
            adl_suppression=adl_suppression,
            degraded=degraded,
        )
        decision = {
            "decision_source": self.SOURCE,
            "shadow": bool(self.settings.unified_decision_shadow and not self.settings.unified_decision_primary_enabled),
            "primary_enabled": bool(self.settings.unified_decision_primary_enabled),
            "status": status,
            "risk_level": self._risk_level(final_score, status),
            "final_fall_score": round(final_score, 4),
            "required_evidence_passed": required_evidence_passed,
            "evidence_group_count": evidence_count,
            "track_stability_passed": track_stability_passed,
            "adl_suppression_passed": adl_suppression_passed,
            "degraded": degraded,
            "confirm_frames": confirm_frames,
            "confirmed_duration_ms": confirmed_duration_ms,
        }
        return UnifiedFallScore(
            decision=decision,
            confidence_breakdown=breakdown,
            evidence_summary=summary,
            decision_trace=self._decision_trace(
                status=status,
                final_score=final_score,
                evidence_count=evidence_count,
                track_stability_passed=track_stability_passed,
                adl_suppression=adl_suppression,
                degraded=degraded,
            ),
        )

    def _enrich_one(self, camera_id: str, item: DetectedObject) -> DetectedObject:
        score = self.evaluate(camera_id, item)
        payload = score.model_payload()
        debug = dict(item.fusion_debug or {})
        if self.settings.unified_decision_shadow:
            debug["unified_shadow_decision"] = payload
        debug["unified_decision_primary_enabled"] = bool(self.settings.unified_decision_primary_enabled)
        updated = item.model_copy(update={"fusion_debug": debug})
        if not self.settings.unified_decision_primary_enabled:
            return updated
        return self._apply_primary_decision(updated, score)

    def _apply_primary_decision(self, item: DetectedObject, score: UnifiedFallScore) -> DetectedObject:
        payload = score.model_payload()
        decision = dict(score.decision)
        status = str(decision.get("status") or "normal")
        blocked_by = (item.fusion_debug or {}).get("confirm_blocked_by") if isinstance(item.fusion_debug, dict) else None
        blocked_by = list(blocked_by or [])
        confirmed = status == "fallen_confirmed"
        rejected_reason = None
        suppressed_reason = None
        if confirmed and blocked_by:
            confirmed = False
            status = "fallen_candidate"
            rejected_reason = "core_evidence_stale"
            suppressed_reason = "core_evidence_stale"

        fall_state = self._primary_fall_state(status)
        risk_level = str(decision.get("risk_level") or "low")
        probability = float(score.confidence_breakdown.get("final_fall_score") or 0.0)
        previous_decision = dict(item.fall_decision or {})
        previous_alarm = dict(item.alarm_preview or {})
        previous_source = previous_decision.get("source") or previous_alarm.get("source")

        if status == "suppressed":
            suppressed_reason = suppressed_reason or "unified_adl_or_quality_suppressed"
        elif status in {"normal", "suspicious", "fallen_candidate", "alarm_preview"}:
            rejected_reason = rejected_reason or self._primary_rejected_reason(status)

        next_decision = {
            **previous_decision,
            "fall_state": fall_state,
            "risk_level": risk_level,
            "fall_probability": round(probability, 4),
            "source": self.SOURCE,
            "confirm_source": self.SOURCE if confirmed else None,
            "suppressed_reason": suppressed_reason,
            "rejected_reason": rejected_reason,
            "previous_source": previous_source,
            "unified_decision": payload,
        }
        next_alarm = {
            **previous_alarm,
            "confirmed": confirmed,
            "risk_level": risk_level,
            "fall_probability": round(probability, 4),
            "source": self.SOURCE,
            "confirm_source": self.SOURCE if confirmed else None,
            "suppressed_reason": suppressed_reason,
            "rejected_reason": rejected_reason,
            "previous_source": previous_source,
            "unified_decision": payload,
        }
        debug = dict(item.fusion_debug or {})
        debug["unified_primary_decision"] = payload
        debug["unified_primary_applied"] = True
        debug["unified_primary_previous_source"] = previous_source
        return item.model_copy(
            update={
                "fall_decision": next_decision,
                "alarm_preview": next_alarm,
                "fusion_debug": debug,
            }
        )

    @staticmethod
    def _visual_fall_hint_score(fall_hint: dict) -> float:
        confidence = UnifiedFallDecisionEngine._float(fall_hint.get("confidence"))
        label = str(fall_hint.get("strongest_label") or "").lower()
        if bool(fall_hint.get("transition_hint")) or label == "falling":
            return confidence * 0.42
        if bool(fall_hint.get("strong_hint")):
            return confidence
        if bool(fall_hint.get("weak_hint")):
            return confidence * 0.55
        return 0.0

    @staticmethod
    def _temporal_score(item: DetectedObject, temporal: dict) -> float:
        candidates = [
            temporal.get("fall_probability"),
            (temporal.get("shadow") or {}).get("fall_probability") if isinstance(temporal.get("shadow"), dict) else None,
        ]
        decision = item.fall_decision if isinstance(item.fall_decision, dict) else {}
        alarm = item.alarm_preview if isinstance(item.alarm_preview, dict) else {}
        if str(decision.get("source") or "") == "temporal_state_machine":
            candidates.append(decision.get("fall_probability"))
        if str(alarm.get("source") or "") == "temporal_state_machine":
            candidates.append(alarm.get("fall_probability"))
        return max((UnifiedFallDecisionEngine._float(value) for value in candidates), default=0.0)

    @staticmethod
    def _motion_drop_score(motion: dict, temporal: dict, v6_fall: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_fall.get("vertical_drop_score"))
        if v6 is not None:
            return v6
        delta_y = max(UnifiedFallDecisionEngine._number(motion.get("delta_y")), UnifiedFallDecisionEngine._number(temporal.get("delta_y")))
        velocity_y = max(
            UnifiedFallDecisionEngine._number(motion.get("velocity_y")),
            UnifiedFallDecisionEngine._number(temporal.get("velocity_y")),
        )
        return max(UnifiedFallDecisionEngine._clamp(delta_y / 80.0), UnifiedFallDecisionEngine._clamp(velocity_y / 300.0))

    @staticmethod
    def _low_posture_score(motion: dict, pose: dict, temporal: dict, v6_fall: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_fall.get("low_posture_score"))
        if v6 is not None:
            return v6
        if bool(pose.get("low_posture")) or bool(temporal.get("low_posture")):
            return 1.0
        aspect = max(
            UnifiedFallDecisionEngine._number(motion.get("aspect_ratio")),
            UnifiedFallDecisionEngine._number(temporal.get("bbox_aspect_ratio")),
        )
        return UnifiedFallDecisionEngine._clamp((aspect - 0.65) / 0.70)

    @staticmethod
    def _horizontal_posture_score(motion: dict, temporal: dict, v6_fall: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_fall.get("aspect_ratio_change_score"))
        if v6 is not None:
            return v6
        aspect = max(
            UnifiedFallDecisionEngine._number(motion.get("aspect_ratio")),
            UnifiedFallDecisionEngine._number(temporal.get("bbox_aspect_ratio")),
        )
        return UnifiedFallDecisionEngine._clamp((aspect - 0.75) / 0.75)

    @staticmethod
    def _post_fall_stillness_score(motion: dict, temporal: dict, v6_fall: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_fall.get("post_fall_stillness_score"))
        if v6 is not None:
            return v6
        if temporal.get("stillness") is not None:
            return 1.0 if bool(temporal.get("stillness")) else 0.0
        speed = max(UnifiedFallDecisionEngine._number(motion.get("speed")), UnifiedFallDecisionEngine._number(temporal.get("speed")))
        return UnifiedFallDecisionEngine._clamp(1.0 - speed / 45.0)

    @staticmethod
    def _floor_contact_score(motion: dict, v6_fall: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_fall.get("floor_contact_score"))
        if v6 is not None:
            return v6
        center_y_norm = UnifiedFallDecisionEngine._float(motion.get("bbox_center_y_norm"))
        return UnifiedFallDecisionEngine._clamp((center_y_norm - 0.45) / 0.35)

    @staticmethod
    def _track_stability_score(item: DetectedObject, motion: dict) -> float:
        if item.track_id is not None and motion.get("tracking_stable") is not False:
            return 1.0
        if item.track_id is not None:
            return 0.7
        return 0.35

    @staticmethod
    def _adl_suppression_score(item: DetectedObject, v6_adl: dict) -> float:
        v6 = UnifiedFallDecisionEngine._maybe_float(v6_adl.get("adl_suppression_score"))
        if v6 is not None:
            return v6
        decision = item.fall_decision if isinstance(item.fall_decision, dict) else {}
        temporal = item.temporal if isinstance(item.temporal, dict) else {}
        for payload in (decision, temporal):
            value = UnifiedFallDecisionEngine._maybe_float(payload.get("adl_suppression_score"))
            if value is not None:
                return value
        behavior = item.behavior if isinstance(item.behavior, dict) else {}
        state = str(behavior.get("behavior_state") or "").lower()
        fall_hint = ((item.features or {}).get("fall_hint") or {}) if isinstance(item.features, dict) else {}
        hint_label = str(fall_hint.get("strongest_label") or "").lower()
        if state in {"sitting", "bending", "kneeling"} or hint_label in {"sitting", "bending", "kneeling"}:
            return 1.0
        return 0.0

    @staticmethod
    def _quality_penalty(item: DetectedObject, pose: dict, fusion_debug: dict, track_stability: float) -> float:
        penalty = 0.0
        if item.confidence < 0.4:
            penalty += 0.25
        if track_stability < 0.60:
            penalty += 0.30
        if not bool(pose.get("pose_available")):
            penalty += 0.15
        freshness = fusion_debug.get("evidence_freshness") if isinstance(fusion_debug.get("evidence_freshness"), dict) else {}
        for name in ("detection", "tracking"):
            if freshness.get(name) not in {None, "fresh", "disabled"}:
                penalty += 0.25
        for name in ("fall_hint", "pose"):
            if freshness.get(name) in {"stale", "frame_misaligned"}:
                penalty += 0.10
        return UnifiedFallDecisionEngine._clamp(penalty)

    @staticmethod
    def _confirmation_progress(item: DetectedObject, fusion_debug: dict) -> tuple[int, float]:
        decision = item.fall_decision if isinstance(item.fall_decision, dict) else {}
        candidates = [fusion_debug, decision]
        frames = 0
        duration = 0.0
        for payload in candidates:
            frames = max(frames, int(UnifiedFallDecisionEngine._number(payload.get("candidate_frames") or payload.get("confirm_frames"))))
            duration = max(
                duration,
                UnifiedFallDecisionEngine._number(payload.get("candidate_duration_ms") or payload.get("confirm_duration_ms")),
            )
        return frames, round(duration, 1)

    @staticmethod
    def _status(
        *,
        final_score: float,
        visual: float,
        motion_drop: float,
        low_posture: float,
        required_evidence_passed: bool,
        track_stability_passed: bool,
        adl_suppression: float,
        confirm_frames: int,
        confirmed_duration_ms: float,
    ) -> str:
        if adl_suppression >= 0.65 and final_score < 0.88:
            return "suppressed"
        if (
            final_score >= 0.75
            and required_evidence_passed
            and track_stability_passed
            and adl_suppression < 0.55
            and (confirm_frames >= 3 or confirmed_duration_ms >= 1000)
        ):
            return "fallen_confirmed"
        if final_score >= 0.70 and (confirm_frames >= 2 or confirmed_duration_ms >= 400):
            return "alarm_preview"
        if final_score >= 0.60 and required_evidence_passed:
            return "fallen_candidate"
        if final_score >= 0.45 or visual >= 0.55 or motion_drop >= 0.60 or low_posture >= 0.65:
            return "suspicious"
        return "normal"

    @staticmethod
    def _risk_level(final_score: float, status: str) -> str:
        if status == "fallen_confirmed":
            return "critical"
        if status in {"alarm_preview", "fallen_candidate"}:
            return "high"
        if status in {"suspicious", "suppressed"} or final_score >= 0.45:
            return "medium"
        return "low"

    @staticmethod
    def _primary_fall_state(status: str) -> str:
        if status == "fallen_confirmed":
            return "fallen_confirmed"
        if status in {"alarm_preview", "fallen_candidate"}:
            return "fallen_candidate"
        if status == "suppressed":
            return "suppressed"
        if status == "suspicious":
            return "suspicious"
        return "normal"

    @staticmethod
    def _primary_rejected_reason(status: str) -> str | None:
        if status == "normal":
            return "unified_score_below_candidate_threshold"
        if status == "suspicious":
            return "unified_suspicious_requires_more_evidence"
        if status in {"fallen_candidate", "alarm_preview"}:
            return "awaiting_unified_confirmation"
        return None

    @staticmethod
    def _evidence_summary(
        *,
        item: DetectedObject,
        motion: dict,
        pose: dict,
        fall_hint: dict,
        temporal: dict,
        track_stability: float,
        adl_suppression: float,
        degraded: bool,
    ) -> dict[str, object]:
        return {
            "track_id": item.track_id,
            "track_stable": track_stability >= 0.60,
            "window_seconds": temporal.get("window_seconds"),
            "frames_observed": temporal.get("window_size"),
            "abnormal_frames": temporal.get("abnormal_frames"),
            "fall_yolo_hits": 1 if bool(fall_hint.get("strong_hint") or fall_hint.get("weak_hint")) else 0,
            "fall_yolo_labels": [fall_hint.get("strongest_label")] if fall_hint.get("strongest_label") else [],
            "center_drop_pixels": round(UnifiedFallDecisionEngine._number(motion.get("delta_y")), 2),
            "max_downward_velocity": round(UnifiedFallDecisionEngine._number(motion.get("velocity_y")), 2),
            "bbox_aspect_ratio_latest": round(UnifiedFallDecisionEngine._number(motion.get("aspect_ratio")), 4),
            "pose_available": bool(pose.get("pose_available")),
            "pose_missing_reason": None if bool(pose.get("pose_available")) else pose.get("rejected_reason") or "missing",
            "body_tilt_degrees": pose.get("torso_angle") or temporal.get("body_angle"),
            "low_posture": bool(pose.get("low_posture") or temporal.get("low_posture")),
            "stillness": temporal.get("stillness"),
            "adl_suppressed": adl_suppression >= 0.55,
            "degraded": degraded,
        }

    @staticmethod
    def _decision_trace(
        *,
        status: str,
        final_score: float,
        evidence_count: int,
        track_stability_passed: bool,
        adl_suppression: float,
        degraded: bool,
    ) -> list[str]:
        trace = [
            f"final_score={final_score:.4f}",
            f"evidence_groups={evidence_count}",
            f"status={status}",
        ]
        if not track_stability_passed:
            trace.append("track_stability_below_confirm_threshold")
        if adl_suppression >= 0.55:
            trace.append("adl_suppression_active")
        if degraded:
            trace.append("freshness_degraded")
        return trace

    @staticmethod
    def _degraded(fusion_debug: dict) -> bool:
        freshness = fusion_debug.get("evidence_freshness") if isinstance(fusion_debug.get("evidence_freshness"), dict) else {}
        return any(state not in {None, "fresh", "disabled"} for state in freshness.values())

    @staticmethod
    def _float(value: object) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return UnifiedFallDecisionEngine._clamp(float(value))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _number(value: object) -> float:
        try:
            if value is None or value == "":
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _maybe_float(value: object) -> float | None:
        try:
            if value is None or value == "":
                return None
            return UnifiedFallDecisionEngine._clamp(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))
