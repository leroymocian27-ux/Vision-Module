from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics
from app.events.vlm import VLMReviewInput, VLMReviewResult
from app.events.vlm_adapter import EventVLMAdapter, InvalidVLMOutput
from app.events.vlm_prompt import VLM_FALL_REVIEW_PROMPT, VLM_FALL_REVIEW_PROMPT_VERSION


class VLMPromptSchemaGuardTest(unittest.TestCase):
    def test_prompt_states_safety_constraints(self) -> None:
        prompt = VLM_FALL_REVIEW_PROMPT

        self.assertEqual(VLM_FALL_REVIEW_PROMPT_VERSION, "fall_event_review_v1")
        self.assertIn("valid JSON only", prompt)
        self.assertIn("Do not invent facts", prompt)
        self.assertIn("Do not provide medical diagnosis", prompt)
        self.assertIn("not the realtime fall detector", prompt)
        self.assertIn("single frame", prompt)
        self.assertIn("adl_likelihood", prompt)
        self.assertIn("vlm_review_result_v1", prompt)

    def test_markdown_wrapped_output_is_invalid(self) -> None:
        adapter = EventVLMAdapter(provider="http_mock", transport=lambda request, timeout: "```json\n{}\n```")

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_non_json_output_is_invalid(self) -> None:
        adapter = EventVLMAdapter(provider="http_mock", transport=lambda request, timeout: "not json")

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_wrong_field_type_is_invalid_schema(self) -> None:
        adapter = EventVLMAdapter(
            provider="http_mock",
            transport=lambda request, timeout: {
                "schema_version": "vlm_review_result_v1",
                "support_fall_alarm": True,
                "semantic_event_type": "fall_candidate",
                "observed_process": "fall-like motion",
                "adl_likelihood": "low",
                "uncertainty": "not-a-list",
                "risk_interpretation": "bad schema",
                "alarm_title": "title",
                "alarm_body": "body",
                "recommended_action": "action",
            },
        )

        with self.assertRaises(InvalidVLMOutput):
            adapter.analyze(self._semantics(), self._evidence())

    def test_long_advisory_text_is_truncated(self) -> None:
        long_body = "body " * 100
        long_action = "action " * 100

        result = EventVLMAdapter(
            provider="http_mock",
            transport=lambda request, timeout: {
                "schema_version": "vlm_review_result_v1",
                "support_fall_alarm": True,
                "semantic_event_type": "fall_candidate",
                "observed_process": "standing to floor",
                "adl_likelihood": "low",
                "uncertainty": [],
                "risk_interpretation": "risk",
                "alarm_title": "title",
                "alarm_body": long_body,
                "recommended_action": long_action,
            },
        ).analyze(self._semantics(), self._evidence())

        self.assertLessEqual(len(result.alarm_body), 300)
        self.assertLessEqual(len(result.recommended_action), 220)

    def test_missing_recommended_action_keeps_rule_default(self) -> None:
        class MissingActionVLM:
            def analyze(self, semantics: EventSemantics, evidence: EvidencePackage):
                del semantics, evidence
                return VLMReviewResult(
                    support_fall_alarm=True,
                    semantic_event_type="fall_candidate",
                    observed_process="standing to low posture",
                    adl_likelihood="low",
                    risk_interpretation="visual advisory",
                )

        baseline = IntelligentAnalysisEngine().analyze(self._semantics(), self._evidence())
        result = IntelligentAnalysisEngine(vlm_analyzer=MissingActionVLM()).analyze(self._semantics(), self._evidence())

        self.assertEqual(result.recommended_action, baseline.recommended_action)
        self.assertIn("VLM advisory", result.explanation)

    @staticmethod
    def _semantics() -> EventSemantics:
        return EventSemantics(
            incident_id="prompt-guard",
            evidence={"adl_suppression_score": 0.1},
            risk={"event_type": "fall_candidate", "risk_level": "high", "confidence": 0.82, "decision": "need_attention"},
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="prompt-guard",
            camera_id="camera_01",
            trigger_timestamp="2026-07-18T09:30:00+00:00",
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, image_path="keyframes/t0.jpg")],
        )


if __name__ == "__main__":
    unittest.main()
