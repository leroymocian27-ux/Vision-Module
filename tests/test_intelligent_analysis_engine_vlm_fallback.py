from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewResult
from app.events.vlm_adapter import InvalidVLMOutput, VLMAdapterTimeout


class _TimeoutVLM:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        raise VLMAdapterTimeout("timeout")


class _InvalidVLM:
    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        raise InvalidVLMOutput("bad json")


class _AdvisoryVLM:
    def __init__(self, *, support: bool | None = True, adl_likelihood: str = "low") -> None:
        self.support = support
        self.adl_likelihood = adl_likelihood

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
        del semantics, evidence
        return VLMReviewResult(
            support_fall_alarm=self.support,
            semantic_event_type="fall_candidate",
            observed_process="person moves from standing to low posture",
            adl_likelihood=self.adl_likelihood,
            uncertainty=["vlm_keyframe_limited"],
            risk_interpretation="visual review is consistent with fall-like motion",
            alarm_title="VLM advisory fall review",
            alarm_body="Review keyframes and live stream.",
            recommended_action="Check live stream and confirm onsite.",
            provider="dummy",
        )


class IntelligentAnalysisEngineVLMFallbackTest(unittest.TestCase):
    def test_timeout_falls_back_to_rule_result(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_TimeoutVLM()).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_only")
        self.assertIn("vlm_timeout", result.degradation_used)

    def test_invalid_json_falls_back_to_rule_result(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_InvalidVLM()).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_only")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_candidate_vlm_success_enriches_explanation_and_action(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_AdvisoryVLM()).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.review_result, "rule_with_vlm_advisory")
        self.assertIn("VLM advisory", result.explanation)
        self.assertIn("vlm_keyframe_limited", result.uncertainty)
        self.assertEqual(result.recommended_action, "Check live stream and confirm onsite.")

    def test_confirmed_fall_is_not_cancelled_by_vlm_non_support(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_AdvisoryVLM(support=False)).analyze(
            self._confirmed_semantics(),
            self._evidence(),
        )

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertEqual(result.final_risk_level, "critical")
        self.assertEqual(result.review_result, "rule_confirmed_vlm_advisory")
        self.assertIn("vlm_disagree", result.uncertainty)

    def test_candidate_high_vlm_adl_likelihood_adds_uncertainty_without_cancelling_rule(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=_AdvisoryVLM(adl_likelihood="high")).analyze(
            self._candidate_semantics(),
            self._evidence(),
        )

        self.assertTrue(result.support_fall_alarm)
        self.assertIn("vlm_high_adl_likelihood", result.uncertainty)

    @staticmethod
    def _candidate_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="incident-vlm",
            motion={"main_transition": "standing_to_low_posture"},
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

    @staticmethod
    def _confirmed_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="incident-vlm",
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.92, "decision": "urgent_attention"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="incident-vlm",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
        )


if __name__ == "__main__":
    unittest.main()
