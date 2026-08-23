from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewResult
from app.events.vlm_adapter import QwenOllamaReviewAdapter


class IntelligentAnalysisEngineOllamaAdvisoryOnlyTest(unittest.TestCase):
    def test_confirmed_fall_ollama_disagree_is_not_downgraded(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=self._adapter(self._ollama_payload(support=False))).analyze(
            self._confirmed_semantics(),
            self._evidence(),
        )

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fallen_confirmed")
        self.assertEqual(result.final_risk_level, "critical")
        self.assertIn("vlm_disagree", result.uncertainty)
        self.assertEqual(result.vlm_provider, "qwen_ollama")

    def test_candidate_ollama_support_only_enriches_advisory_fields(self) -> None:
        result = IntelligentAnalysisEngine(vlm_analyzer=self._adapter(self._ollama_payload(support=True))).analyze(
            self._candidate_semantics(),
            self._evidence(),
        )

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertEqual(result.final_risk_level, "high")
        self.assertIn("VLM advisory", result.explanation)
        self.assertEqual(result.recommended_action, "Check live stream and confirm onsite.")
        self.assertEqual(result.observed_process, "structured event shows sustained low posture")

    def test_ollama_forbidden_decision_fields_do_not_override_rules(self) -> None:
        payload = self._ollama_payload(support=True)
        payload.update({"risk_level": "low", "fall_state": "fallen_confirmed", "delivery_status": "sent"})

        result = IntelligentAnalysisEngine(vlm_analyzer=self._adapter(payload)).analyze(self._candidate_semantics(), self._evidence())

        self.assertTrue(result.support_fall_alarm)
        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertEqual(result.final_risk_level, "high")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_medical_diagnosis_text_is_not_adopted(self) -> None:
        payload = self._ollama_payload(support=True)
        payload["recommended_action"] = "medical diagnosis: fracture"
        payload["risk_interpretation"] = "medical diagnosis should not be used"

        result = IntelligentAnalysisEngine(vlm_analyzer=self._adapter(payload)).analyze(self._candidate_semantics(), self._evidence())

        self.assertNotIn("medical diagnosis", result.explanation.lower())
        self.assertNotIn("medical diagnosis", result.recommended_action.lower())

    @staticmethod
    def _adapter(content: dict) -> QwenOllamaReviewAdapter:
        return QwenOllamaReviewAdapter(
            endpoint_url="http://127.0.0.1:11434/api/chat",
            model="qwen-vision-cn:latest",
            timeout_seconds=1,
            transport=lambda payload, timeout: {"message": {"content": __import__("json").dumps(content)}},
        )

    @staticmethod
    def _ollama_payload(*, support: bool | None) -> dict:
        return {
            "schema_version": "vlm_review_result_v1",
            "support_fall_alarm": support,
            "semantic_event_type": "fall_candidate",
            "observed_process": "structured event shows sustained low posture",
            "adl_likelihood": "low",
            "uncertainty": ["text_only_no_images"],
            "risk_interpretation": "Structured evidence supports advisory fall review.",
            "alarm_title": "Local advisory review",
            "alarm_body": "Review the live stream and onsite status.",
            "recommended_action": "Check live stream and confirm onsite.",
        }

    @staticmethod
    def _candidate_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="ollama-advisory",
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

    @staticmethod
    def _confirmed_semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="ollama-advisory",
            risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.94, "decision": "urgent_attention"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="ollama-advisory",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            fall_probability=0.82,
            fall_evidence_score=0.86,
            adl_suppression_score=0.1,
        )


if __name__ == "__main__":
    unittest.main()
