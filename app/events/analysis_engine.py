from __future__ import annotations

from typing import Any, Protocol

from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult
from app.events.vlm import VLMReviewResult
from app.events.vlm_adapter import InvalidVLMOutput, VLMAdapterSkipped, VLMAdapterTimeout


class OptionalVLMAnalyzer(Protocol):
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewResult | dict[str, Any] | None: ...


class DummyVLMAnalyzer:
    """Deterministic test implementation; never used unless explicitly injected."""

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> dict[str, Any] | None:
        del semantics, evidence
        return None


class RuleAnalyzer:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> TrustedEventResult:
        risk = semantics.risk
        event_type = str(risk.get("event_type") or "fall_candidate")
        risk_level = str(risk.get("risk_level") or "medium")
        confidence = float(risk.get("confidence") or 0.0)
        decision = str(risk.get("decision") or "need_review")
        adl_score = float((semantics.evidence or {}).get("adl_suppression_score") or 0.0)
        degradation = list(semantics.degradation_used)
        if event_type == "fallen_confirmed":
            support = True
            final_level = "critical"
            title = "跌倒确认告警"
            body = "检测到老人跌倒确认事件，请立即查看现场并确认老人状态。"
            action = "立即查看实时画面，必要时联系现场人员或家属。"
        elif adl_score >= 0.65 or decision == "need_review":
            support = False
            final_level = "medium" if risk_level in {"high", "critical"} else risk_level
            title = "疑似异常姿态待复核"
            body = "检测到低位或异常姿态，但存在日常活动误报可能，建议人工复核。"
            action = "查看关键帧和实时画面，确认是否为坐下、弯腰或正常躺卧。"
        else:
            support = True
            final_level = risk_level if risk_level in {"low", "medium", "high", "critical"} else "high"
            title = "疑似跌倒告警"
            body = "检测到疑似跌倒及持续低位证据，请及时查看现场。"
            action = str(risk.get("advice") or "立即查看实时画面并确认老人状态。")
        explanation = _explanation(semantics, evidence)
        return TrustedEventResult(
            incident_id=semantics.incident_id,
            support_fall_alarm=support,
            final_event_type=event_type,
            final_risk_level=final_level,  # type: ignore[arg-type]
            confidence=max(0.0, min(1.0, confidence)),
            explanation=explanation,
            uncertainty=list(semantics.uncertainty),
            alarm_title=title,
            alarm_body=body,
            recommended_action=action,
            review_result="rule_only",
            degradation_used=degradation,
        )


class IntelligentAnalysisEngine:
    """Rule-first event analysis; optional VLM can enrich but never decide."""

    def __init__(self, *, rule_analyzer: RuleAnalyzer | None = None, vlm_analyzer: OptionalVLMAnalyzer | None = None) -> None:
        self.rule_analyzer = rule_analyzer or RuleAnalyzer()
        self.vlm_analyzer = vlm_analyzer

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> TrustedEventResult:
        result = self.rule_analyzer.analyze(semantics, evidence)
        if self.vlm_analyzer is None:
            return result
        try:
            enrichment = self.vlm_analyzer.analyze(semantics, evidence)
        except VLMAdapterSkipped as exc:
            return _with_degradation(result, str(exc) or "vlm_skipped")
        except VLMAdapterTimeout:
            return _with_degradation(result, "vlm_timeout")
        except InvalidVLMOutput:
            return _with_degradation(result, "vlm_invalid_json")
        except Exception:
            return _with_degradation(result, "vlm_failed")
        if not enrichment:
            return result
        if isinstance(enrichment, dict):
            try:
                enrichment = VLMReviewResult.model_validate(enrichment)
            except Exception:
                return _with_degradation(result, "vlm_invalid_json")
        updates: dict[str, Any] = {}
        advisory_uncertainty = list(enrichment.uncertainty)
        advisory_degradation: list[str] = []
        if enrichment.support_fall_alarm is False and result.support_fall_alarm:
            advisory_uncertainty.append("vlm_disagree")
            advisory_degradation.append("vlm_disagree")
        if enrichment.adl_likelihood == "high":
            advisory_uncertainty.append("vlm_high_adl_likelihood")
        elif enrichment.adl_likelihood == "medium":
            advisory_uncertainty.append("vlm_medium_adl_likelihood")
        if enrichment.risk_interpretation:
            updates["explanation"] = f"{result.explanation} VLM advisory: {enrichment.risk_interpretation}"
        updates["vlm_provider"] = enrichment.provider
        updates["vlm_latency_ms"] = enrichment.latency_ms
        if enrichment.provider in {"ollama", "qwen_ollama", "ollama_qwen"}:
            if enrichment.risk_interpretation:
                updates["explanation"] = f"{result.explanation} VLM advisory: {enrichment.risk_interpretation}"
            if enrichment.recommended_action:
                updates["recommended_action"] = enrichment.recommended_action
            if advisory_uncertainty:
                updates["uncertainty"] = list(dict.fromkeys([*result.uncertainty, *advisory_uncertainty]))
            updates.update({
                "observed_process": enrichment.observed_process or None,
                "risk_interpretation": enrichment.risk_interpretation or None,
                "adl_likelihood": enrichment.adl_likelihood,
                "scene_summary": enrichment.scene_summary or None,
                "possible_false_positive_reason": enrichment.possible_false_positive_reason or None,
                "care_advice": enrichment.care_advice or None,
                "confidence_explanation": enrichment.confidence_explanation or None,
                "advisory_confidence": enrichment.advisory_confidence,
            })
            review = "rule_confirmed_vlm_advisory" if result.final_event_type == "fallen_confirmed" else "rule_with_vlm_advisory"
            return result.model_copy(update={**updates, "review_result": review})
        updates["observed_process"] = enrichment.observed_process or None
        updates["risk_interpretation"] = enrichment.risk_interpretation or None
        updates["adl_likelihood"] = enrichment.adl_likelihood
        if advisory_uncertainty:
            updates["uncertainty"] = list(dict.fromkeys([*result.uncertainty, *advisory_uncertainty]))
        if advisory_degradation:
            updates["degradation_used"] = list(dict.fromkeys([*result.degradation_used, *advisory_degradation]))
        if enrichment.alarm_title:
            updates["alarm_title"] = enrichment.alarm_title
        if enrichment.alarm_body:
            updates["alarm_body"] = enrichment.alarm_body
        if enrichment.recommended_action:
            updates["recommended_action"] = enrichment.recommended_action
        if result.final_event_type == "fallen_confirmed":
            return result.model_copy(update={**updates, "review_result": "rule_confirmed_vlm_advisory"})
        return result.model_copy(update={**updates, "review_result": "rule_with_vlm_advisory"})


def _with_degradation(result: TrustedEventResult, reason: str) -> TrustedEventResult:
    degradation = list(dict.fromkeys([*result.degradation_used, reason]))
    return result.model_copy(update={"degradation_used": degradation})


def _explanation(semantics: EventSemantics, evidence: EvidencePackage) -> str:
    motion = semantics.motion.get("main_transition", "unknown")
    state = semantics.risk.get("event_type", "fall_candidate")
    keyframe_count = len([item for item in evidence.keyframes if item.missing_reason is None])
    return f"事件状态为 {state}，运动变化为 {motion}，已收集 {keyframe_count} 张可用关键帧。"
