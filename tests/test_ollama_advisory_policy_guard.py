from __future__ import annotations

import json
import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.vlm_adapter import QwenOllamaReviewAdapter
from scripts.evaluate_ollama_advisory_review import build_synthetic_case


class OllamaAdvisoryPolicyGuardTest(unittest.TestCase):
    def test_forbidden_risk_level_is_not_adopted(self) -> None:
        result = self._analyze_with_payload({"risk_level": "low"})

        self.assertEqual(result.final_risk_level, "high")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_forbidden_fall_state_is_not_adopted(self) -> None:
        result = self._analyze_with_payload({"fall_state": "fallen_confirmed"})

        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_forbidden_confirmed_is_not_adopted(self) -> None:
        result = self._analyze_with_payload({"confirmed": True})

        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertEqual(result.final_risk_level, "high")

    def test_forbidden_delivery_status_is_not_adopted(self) -> None:
        result = self._analyze_with_payload({"delivery_status": "sent"})

        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertIn("vlm_invalid_json", result.degradation_used)

    def test_medical_diagnosis_does_not_enter_final_advice(self) -> None:
        payload = self._base_payload()
        payload["recommended_action"] = "medical diagnosis: fracture"
        payload["risk_interpretation"] = "diagnosis: fracture suspected"

        result = self._analyze_with_payload(payload, merge_base=False)

        self.assertNotIn("medical diagnosis", result.recommended_action.lower())
        self.assertNotIn("diagnosis:", result.explanation.lower())

    def test_raw_response_does_not_enter_public_summary_fields(self) -> None:
        payload = self._base_payload()
        payload["raw_response"] = "secret raw response"

        result = self._analyze_with_payload(payload, merge_base=False)

        public_text = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        self.assertNotIn("secret raw response", public_text)

    def _analyze_with_payload(self, updates: dict, *, merge_base: bool = True):
        payload = self._base_payload()
        if merge_base:
            payload.update(updates)
        else:
            payload = updates
        semantics, evidence = build_synthetic_case("fall_candidate_support")
        adapter = QwenOllamaReviewAdapter(
            endpoint_url="http://127.0.0.1:11434/api/chat",
            model="qwen-vision-cn:latest",
            timeout_seconds=1,
            transport=lambda request, timeout: {"message": {"content": json.dumps(payload)}},
        )
        return IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(semantics, evidence)

    @staticmethod
    def _base_payload() -> dict:
        return {
            "schema_version": "vlm_review_result_v1",
            "support_fall_alarm": True,
            "semantic_event_type": "fallen_confirmed",
            "observed_process": "structured event only",
            "adl_likelihood": "low",
            "uncertainty": ["text_only_no_images"],
            "risk_interpretation": "Advisory explanation only.",
            "alarm_title": "Local advisory",
            "alarm_body": "Review live stream.",
            "recommended_action": "Check live stream and confirm onsite.",
        }


if __name__ == "__main__":
    unittest.main()
