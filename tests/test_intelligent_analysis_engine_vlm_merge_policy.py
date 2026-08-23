from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewResult
from app.events.vlm_adapter import InvalidVLMOutput, VLMAdapterSkipped


class _ReviewVLM:
    def __init__(self, *, support: bool | None = True, adl_likelihood: str = "low") -> None:
        self.support = support
        self.adl_likelihood = adl_likelihood

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewResult:
        del semantics, evidence
        return VLMReviewResult(
            support_fall_alarm=self.support,
            semantic_event_type="fall_candidate",
            observed_process="multi-frame fall-like motion",
            adl_likelihood=self.adl_likelihood,
            uncertainty=["vlm_timeline_limited"],
            risk_interpretation="VLM advisory supports review of the event process.",
            alarm_title="VLM advisory review",
            alarm_body="Review timeline and live stream.",
            recommended_action="Check live stream and confirm onsite.",
            provider="dummy",
            latency_ms=12.5,
        )


class _InvalidVLM:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        raise InvalidVLMOutput("bad schema")


class _SkippedVLM:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        raise VLMAdapterSkipped("vlm_skipped_no_images")


class IntelligentAnalysisEngineVLMMergePolicyTest(unittest.TestCase):
    def test_confirmed_plus_vlm_unsupported_is_not_downgraded(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_ReviewVLM(support=False)).analyze(self._confirmed(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertEqual(result.final_risk_level, "critical")
        self.assertIn("vlm_disagree", result.uncertainty)
        self.assertIn("vlm_disagree", result.degradation_used)

    def test_confirmed_plus_vlm_invalid_still_generates_trusted_result(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_InvalidVLM()).analyze(self._confirmed(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_candidate_low_adl_vlm_support_enriches_explanation(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_ReviewVLM(support=True, adl_likelihood="low")).analyze(self._candidate_low_adl(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_with_vlm_advisory")
        self.assertIn("VLM advisory", result.explanation)
        self.assertEqual(result.recommended_action, "Check live stream and confirm onsite.")

    def test_candidate_high_adl_remains_review_or_unsupported_even_if_vlm_supports(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_ReviewVLM(support=True, adl_likelihood="high")).analyze(self._candidate_high_adl(), self._evidence())

        self.assertFalse(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertNotEqual(result.final_event_type, "fallen_confirmed")
        self.assertIn("vlm_high_adl_likelihood", result.uncertainty)

    def test_unsupported_rule_is_not_upgraded_to_confirmed_by_vlm_support(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_ReviewVLM(support=True, adl_likelihood="medium")).analyze(self._unsupported_like(), self._evidence())

        self.assertFalse(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertIn("vlm_medium_adl_likelihood", result.uncertainty)

    def test_vlm_skipped_no_images_is_recorded_as_degradation(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_SkippedVLM()).analyze(self._candidate_low_adl(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertIn("vlm_skipped_no_images", result.degradation_used)

    @staticmethod
    def _confirmed() -> EventSemantics:
        return EventSemantics(
            incident_id="merge-policy",
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.94, "decision": "urgent_attention"},
        )

    @staticmethod
    def _candidate_low_adl() -> EventSemantics:
        return EventSemantics(
            incident_id="merge-policy",
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.84, "decision": "need_attention"},
        )

    @staticmethod
    def _candidate_high_adl() -> EventSemantics:
        return EventSemantics(
            incident_id="merge-policy",
            evidence={"adl_suppression_score": 0.9},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.8, "decision": "need_review"},
        )

    @staticmethod
    def _unsupported_like() -> EventSemantics:
        return EventSemantics(
            incident_id="merge-policy",
            evidence={"adl_suppression_score": 0.8},
            risk={"event_type": "fall_candidate", "risk_level": "medium", "confidence": 0.45, "decision": "need_review"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="merge-policy",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
        )


if __name__ == "__main__":
    unittest.main()
