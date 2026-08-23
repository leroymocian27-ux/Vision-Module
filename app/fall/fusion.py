from __future__ import annotations

import time

from app.core.config import Settings
from app.schemas.vision_result import DetectedObject


class FallFusionService:
    """False-positive-first fusion guard for final fall decisions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._candidate_states: dict[str, dict[str, float | int]] = {}
        self._counts = {
            "confirmed": 0,
            "candidate": 0,
            "suppressed": 0,
        }
        self._latest_guard_reason: str | None = None

    def enrich(self, camera_id: str, objects: list[DetectedObject]) -> list[DetectedObject]:
        enriched: list[DetectedObject] = []
        for item in objects:
            if item.label != "person":
                enriched.append(item)
                continue
            fused = self._enrich_one(camera_id, item)
            enriched.append(fused)
        return enriched

    def status(self) -> dict[str, object]:
        return {
            "confirmed_count": self._counts["confirmed"],
            "candidate_count": self._counts["candidate"],
            "suppressed_count": self._counts["suppressed"],
            "latest_guard_reason": self._latest_guard_reason,
            "active_candidate_tracks": len(self._candidate_states),
        }

    def reset_camera(self, camera_id: str) -> None:
        prefix = f"{camera_id}:"
        for key in list(self._candidate_states.keys()):
            if key.startswith(prefix):
                self._candidate_states.pop(key, None)

    def _enrich_one(self, camera_id: str, item: DetectedObject) -> DetectedObject:
        features = item.features or {}
        motion = features.get("motion") if isinstance(features.get("motion"), dict) else {}
        pose = features.get("pose") if isinstance(features.get("pose"), dict) else {}
        fall_hint = features.get("fall_hint") if isinstance(features.get("fall_hint"), dict) else {}
        temporal = item.temporal if isinstance(item.temporal, dict) else {}
        existing_decision = item.fall_decision if isinstance(item.fall_decision, dict) else {}
        existing_alarm = item.alarm_preview if isinstance(item.alarm_preview, dict) else {}

        evidence_sources = self._evidence_sources(motion, pose, fall_hint, temporal)
        temporal_probability = self._probability(item, temporal)
        low_posture = bool(pose.get("low_posture") or temporal.get("low_posture"))
        stillness = self._stillness(motion, temporal)
        rapid_descent = self._rapid_descent(motion, temporal)
        strong_hint = bool(fall_hint.get("strong_hint"))
        transition_hint = bool(fall_hint.get("transition_hint"))
        weak_hint = bool(fall_hint.get("weak_hint"))
        track_stable = bool(motion.get("tracking_stable") is True and item.track_id is not None)
        adl_like = self._adl_like(item)
        existing_confirmed = self._existing_confirmed(existing_decision, existing_alarm)
        v6_guard_reason = self._v6_guard_reason(existing_decision, temporal)
        existing_temporal_confirmed = self._existing_temporal_confirmed(existing_decision)
        if existing_confirmed and (existing_temporal_confirmed or v6_guard_reason is None):
            self._counts["confirmed"] += 1
            return self._with_fusion_payloads(
                item,
                fall_state="fallen_confirmed",
                risk_level="critical",
                probability=max(0.72, temporal_probability, float(fall_hint.get("confidence") or 0.0)),
                confirmed=True,
                evidence_sources=evidence_sources,
                guard_reason=None,
                confirm_debug={
                    "candidate_frames": existing_decision.get("confirm_frames", 0),
                    "candidate_duration_ms": existing_decision.get("candidate_duration_ms", 0),
                    "rejected_reason": None,
                    "temporal_confirmed_passthrough": True,
                },
                source="temporal_state_machine",
            )

        candidate_evidence = (
            temporal_probability >= self.settings.falling_prob_threshold
            or strong_hint
            or (transition_hint and (low_posture or stillness or temporal_probability >= self.settings.falling_prob_threshold))
            or (weak_hint and not transition_hint and (rapid_descent or low_posture))
            or str(existing_decision.get("fall_state") or "") in {"falling", "fallen_candidate", "fallen_confirmed"}
        )

        guard_reason = self._guard_reason(
            existing_confirmed=existing_confirmed,
            track_stable=track_stable,
            adl_like=adl_like,
            strong_hint=strong_hint,
            transition_hint=transition_hint,
            weak_hint=weak_hint,
            low_posture=low_posture,
            stillness=stillness,
            rapid_descent=rapid_descent,
            temporal_probability=temporal_probability,
            v6_guard_reason=v6_guard_reason,
        )
        confirmed_ready, confirm_debug = self._confirmed_ready(
            camera_id=camera_id,
            item=item,
            candidate_evidence=candidate_evidence,
            guard_reason=guard_reason,
            low_posture=low_posture,
            stillness=stillness,
            rapid_descent=rapid_descent,
            temporal_probability=temporal_probability,
            strong_hint=strong_hint,
            transition_hint=transition_hint,
            track_stable=track_stable,
            evidence_sources=evidence_sources,
        )

        if confirmed_ready:
            self._counts["confirmed"] += 1
            return self._with_fusion_payloads(
                item,
                fall_state="fallen_confirmed",
                risk_level="critical",
                probability=max(0.72, temporal_probability, float(fall_hint.get("confidence") or 0.0)),
                confirmed=True,
                evidence_sources=evidence_sources,
                guard_reason=None,
                confirm_debug=confirm_debug,
                source="fusion_state_machine",
            )

        if candidate_evidence:
            if guard_reason is not None:
                self._counts["suppressed"] += 1
                self._latest_guard_reason = guard_reason
                return self._with_fusion_payloads(
                    item,
                    fall_state="suppressed",
                    risk_level="medium",
                    probability=max(temporal_probability, float(fall_hint.get("confidence") or 0.0)),
                    confirmed=False,
                    evidence_sources=evidence_sources,
                    guard_reason=guard_reason,
                    confirm_debug=confirm_debug,
                    source="fusion_state_machine",
                )
            self._counts["candidate"] += 1
            self._latest_guard_reason = confirm_debug.get("rejected_reason")
            candidate_risk = "high" if (low_posture and (strong_hint or temporal_probability >= self.settings.falling_prob_threshold)) else "medium"
            return self._with_fusion_payloads(
                item,
                fall_state="fallen_candidate",
                risk_level=candidate_risk,
                probability=max(0.35, temporal_probability, float(fall_hint.get("confidence") or 0.0)),
                confirmed=False,
                evidence_sources=evidence_sources,
                guard_reason=str(confirm_debug.get("rejected_reason") or "awaiting_multi_evidence_confirmation"),
                confirm_debug=confirm_debug,
                source="fusion_state_machine",
            )

        self._decay_candidate(camera_id, item)
        return item.model_copy(
            update={
                "fusion_debug": {
                    **(item.fusion_debug or {}),
                    "evidence_sources": evidence_sources,
                    "candidate_evidence": False,
                    "track_stable": track_stable,
                    "adl_like": adl_like,
                }
            }
        )

    def _confirmed_ready(
        self,
        *,
        camera_id: str,
        item: DetectedObject,
        candidate_evidence: bool,
        guard_reason: str | None,
        low_posture: bool,
        stillness: bool,
        rapid_descent: bool,
        temporal_probability: float,
        strong_hint: bool,
        transition_hint: bool,
        track_stable: bool,
        evidence_sources: list[str],
    ) -> tuple[bool, dict[str, object]]:
        key = self._candidate_key(camera_id, item)
        now = time.monotonic()
        state = self._candidate_states.get(key)
        if state is None or now - float(state.get("last_seen", 0.0)) > 2.5:
            state = {"frames": 0, "started_at": now, "last_seen": now}
        if candidate_evidence and guard_reason is None:
            state["frames"] = int(state.get("frames", 0)) + 1
        else:
            state["frames"] = max(0, int(state.get("frames", 0)) - 1)
        state["last_seen"] = now
        self._candidate_states[key] = state

        frames = int(state.get("frames", 0))
        duration_ms = (now - float(state.get("started_at", now))) * 1000
        frames_ready = frames >= max(1, self.settings.fall_confirm_frames)
        duration_ready = duration_ms >= max(0, self.settings.fall_still_ms)
        combo_temporal = temporal_probability >= self.settings.falling_prob_threshold and low_posture and stillness
        combo_hint = rapid_descent and low_posture and strong_hint
        combo_transition = transition_hint and low_posture and stillness and temporal_probability >= self.settings.falling_prob_threshold
        combo_pose_motion = "pose" in evidence_sources and rapid_descent and low_posture and stillness
        multi_evidence = sum([combo_temporal, combo_hint, combo_transition, combo_pose_motion]) >= 1
        rejected_reason = None
        if guard_reason is not None:
            rejected_reason = guard_reason
        elif not track_stable:
            rejected_reason = "track_unstable"
        elif not multi_evidence:
            rejected_reason = "insufficient_multi_evidence"
        elif not frames_ready and not duration_ready:
            rejected_reason = "awaiting_confirm_frames_and_duration"
        elif not frames_ready:
            rejected_reason = "awaiting_confirm_frames"
        elif not duration_ready:
            rejected_reason = "awaiting_confirm_duration"
        return (
            bool(track_stable and multi_evidence and frames_ready and duration_ready and guard_reason is None),
            {
                "candidate_frames": frames,
                "candidate_duration_ms": round(duration_ms, 1),
                "confirm_frames_required": self.settings.fall_confirm_frames,
                "confirm_duration_required_ms": self.settings.fall_still_ms,
                "combo_temporal": combo_temporal,
                "combo_hint": combo_hint,
                "combo_transition": combo_transition,
                "combo_pose_motion": combo_pose_motion,
                "low_posture": low_posture,
                "stillness": stillness,
                "rapid_descent": rapid_descent,
                "track_stable": track_stable,
                "rejected_reason": rejected_reason,
            },
        )

    def _guard_reason(
        self,
        *,
        existing_confirmed: bool,
        track_stable: bool,
        adl_like: bool,
        strong_hint: bool,
        transition_hint: bool,
        weak_hint: bool,
        low_posture: bool,
        stillness: bool,
        rapid_descent: bool,
        temporal_probability: float,
        v6_guard_reason: str | None,
    ) -> str | None:
        if v6_guard_reason is not None:
            return v6_guard_reason
        if not track_stable:
            return "track_unstable"
        if transition_hint and not low_posture and temporal_probability < self.settings.falling_prob_threshold:
            return "falling_transition_without_fallen_evidence"
        if weak_hint and not strong_hint and not rapid_descent:
            return "weak_lying_hint_without_descent"
        if adl_like and not (
            low_posture
            and stillness
            and strong_hint
        ):
            return "adl_like_posture_suppressed"
        if existing_confirmed and not (low_posture and stillness):
            return "confirmed_input_failed_low_posture_stillness_guard"
        return None

    @staticmethod
    def _existing_confirmed(decision: dict, alarm: dict) -> bool:
        return (
            str(decision.get("fall_state") or "") == "fallen_confirmed"
            or bool(decision.get("fall_latched") is True)
            or bool(alarm.get("confirmed") is True)
        )

    @staticmethod
    def _existing_temporal_confirmed(decision: dict) -> bool:
        return (
            str(decision.get("source") or "") == "temporal_state_machine"
            and str(decision.get("fall_state") or "") == "fallen_confirmed"
        ) or bool(decision.get("fall_latched") is True)

    def _v6_guard_reason(self, decision: dict, temporal: dict) -> str | None:
        if not self.settings.fall_v6_decision_enabled:
            return None
        if bool(decision.get("fall_latched") is True):
            return None
        if bool(decision.get("suppressed_by_adl") is True):
            return "v6_adl_suppressed"
        if bool(decision.get("uncertain_review") is True):
            return "v6_uncertain_review"

        v6_scores = temporal.get("v6_scores") if isinstance(temporal.get("v6_scores"), dict) else {}
        v6_fall = v6_scores.get("fall") if isinstance(v6_scores.get("fall"), dict) else {}
        fall_evidence = self._float_or_none(decision.get("fall_evidence_score"))
        if fall_evidence is None:
            fall_evidence = self._float_or_none(temporal.get("fall_evidence_score"))
        floor_contact = self._float_or_none(v6_fall.get("floor_contact_score"))
        post_fall_stillness = self._float_or_none(v6_fall.get("post_fall_stillness_score"))
        motion_path = str(decision.get("motion_path") or temporal.get("motion_path") or "")
        if (
            fall_evidence is not None
            and floor_contact is not None
            and post_fall_stillness is not None
            and fall_evidence < 0.55
            and floor_contact < 0.30
            and post_fall_stillness >= 0.55
            and motion_path in {"normal", "motion_observe", "legacy_shadow"}
        ):
            return "v6_low_fall_evidence_low_floor_contact"
        return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _evidence_sources(motion: dict, pose: dict, fall_hint: dict, temporal: dict) -> list[str]:
        sources = []
        if motion:
            sources.append("motion")
        if pose.get("pose_available"):
            sources.append("pose")
        if fall_hint.get("strong_hint") or fall_hint.get("weak_hint"):
            sources.append("fall_hint")
        if temporal.get("window_ready") or temporal.get("fall_probability") is not None:
            sources.append("temporal")
        return sources

    @staticmethod
    def _probability(item: DetectedObject, temporal: dict) -> float:
        candidates = [
            temporal.get("fall_probability"),
            (temporal.get("shadow") or {}).get("fall_probability") if isinstance(temporal.get("shadow"), dict) else None,
            (item.fall_decision or {}).get("fall_probability") if isinstance(item.fall_decision, dict) else None,
            (item.alarm_preview or {}).get("fall_probability") if isinstance(item.alarm_preview, dict) else None,
        ]
        values = []
        for candidate in candidates:
            try:
                if candidate is not None:
                    values.append(max(0.0, min(1.0, float(candidate))))
            except (TypeError, ValueError):
                continue
        return max(values) if values else 0.0

    @staticmethod
    def _stillness(motion: dict, temporal: dict) -> bool:
        if temporal.get("stillness") is not None:
            return bool(temporal.get("stillness"))
        return float(motion.get("speed") or 0.0) <= 38.0

    @staticmethod
    def _rapid_descent(motion: dict, temporal: dict) -> bool:
        velocity_y = float(motion.get("velocity_y") or temporal.get("velocity_y") or 0.0)
        delta_y = float(motion.get("delta_y") or 0.0)
        return delta_y > 40.0 or velocity_y > 180.0

    @staticmethod
    def _adl_like(item: DetectedObject) -> bool:
        behavior = item.behavior if isinstance(item.behavior, dict) else {}
        behavior_state = str(behavior.get("behavior_state") or "").lower()
        fall_hint = ((item.features or {}).get("fall_hint") or {}) if isinstance(item.features, dict) else {}
        label = str(fall_hint.get("strongest_label") or "").lower()
        return behavior_state in {"sitting", "bending", "kneeling"} or label in {"sitting", "bending", "kneeling"}

    def _with_fusion_payloads(
        self,
        item: DetectedObject,
        *,
        fall_state: str,
        risk_level: str,
        probability: float,
        confirmed: bool,
        evidence_sources: list[str],
        guard_reason: str | None,
        confirm_debug: dict[str, object],
        source: str,
    ) -> DetectedObject:
        previous_decision = dict(item.fall_decision or {})
        previous_alarm = dict(item.alarm_preview or {})
        fusion_debug = {
            **(item.fusion_debug or {}),
            **confirm_debug,
            "evidence_sources": evidence_sources,
            "suppressed_reason": guard_reason if fall_state == "suppressed" else None,
            "rejected_reason": guard_reason or confirm_debug.get("rejected_reason"),
            "source": source,
        }
        decision = {
            **previous_decision,
            "fall_state": fall_state,
            "risk_level": risk_level,
            "fall_probability": round(float(probability), 4),
            "source": source,
            "suppressed_reason": guard_reason if fall_state != "fallen_confirmed" else None,
            "rejected_reason": guard_reason or confirm_debug.get("rejected_reason"),
            "confirm_source": source if confirmed else None,
            "evidence_sources": evidence_sources,
        }
        alarm = {
            **previous_alarm,
            "confirmed": confirmed,
            "risk_level": risk_level,
            "fall_probability": round(float(probability), 4),
            "source": source,
            "suppressed_reason": guard_reason if not confirmed else None,
        }
        return item.model_copy(
            update={
                "fall_decision": decision,
                "alarm_preview": alarm,
                "fusion_debug": fusion_debug,
            }
        )

    def _decay_candidate(self, camera_id: str, item: DetectedObject) -> None:
        key = self._candidate_key(camera_id, item)
        state = self._candidate_states.get(key)
        if state is None:
            return
        frames = max(0, int(state.get("frames", 0)) - 1)
        if frames <= 0:
            self._candidate_states.pop(key, None)
            return
        state["frames"] = frames
        state["last_seen"] = time.monotonic()

    @staticmethod
    def _candidate_key(camera_id: str, item: DetectedObject) -> str:
        if item.track_id is not None:
            return f"{camera_id}:track:{int(item.track_id)}"
        x1, y1, x2, y2 = [float(value) for value in item.bbox]
        return f"{camera_id}:spatial:{int(((x1 + x2) / 2) // 160)}:{int(((y1 + y2) / 2) // 120)}"
