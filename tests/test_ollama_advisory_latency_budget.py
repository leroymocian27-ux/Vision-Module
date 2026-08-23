from __future__ import annotations

import unittest

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.vlm_adapter import QwenOllamaReviewAdapter
from scripts.evaluate_ollama_advisory_review import EvaluationConfig, build_synthetic_case, evaluate


class OllamaAdvisoryLatencyBudgetTest(unittest.TestCase):
    def test_timeout_records_degradation_and_generates_result(self) -> None:
        report = evaluate(
            self._config(cases=("fall_candidate_support",), allow_local_ollama=True),
            transport=lambda payload, timeout_seconds: (_ for _ in ()).throw(TimeoutError("too slow")),
        )

        case = report["cases"][0]
        self.assertTrue(case["success"])
        self.assertTrue(case["fallback_used"])
        self.assertIn("vlm_timeout", case["degradation_used"])

    def test_connection_refused_records_failed_degradation(self) -> None:
        report = evaluate(
            self._config(cases=("fall_candidate_support",), allow_local_ollama=True),
            transport=lambda payload, timeout_seconds: (_ for _ in ()).throw(ConnectionError("refused")),
        )

        case = report["cases"][0]
        self.assertTrue(case["success"])
        self.assertTrue(case["fallback_used"])
        self.assertIn("vlm_failed", case["degradation_used"])

    def test_slow_response_over_budget_can_fail_open(self) -> None:
        def slow_timeout(payload, timeout_seconds):
            del payload, timeout_seconds
            raise TimeoutError("simulated slow response beyond advisory budget")

        semantics, evidence = build_synthetic_case("fall_candidate_support")
        result = IntelligentAnalysisEngine(
            vlm_analyzer=QwenOllamaReviewAdapter(
                endpoint_url="http://127.0.0.1:11434/api/chat",
                model="qwen-vision-cn:latest",
                timeout_seconds=0.01,
                transport=slow_timeout,
            )
        ).analyze(semantics, evidence)

        self.assertEqual(result.final_event_type, "fall_candidate")
        self.assertEqual(result.final_risk_level, "high")
        self.assertIn("vlm_timeout", result.degradation_used)

    @staticmethod
    def _config(*, cases, allow_local_ollama) -> EvaluationConfig:
        return EvaluationConfig(
            model="qwen-vision-cn:latest",
            fallback_model="qwen3.5:9b",
            endpoint="http://127.0.0.1:11434/api/chat",
            timeout=0.01,
            cases=tuple(cases),
            max_cases=6,
            output=__import__("pathlib").Path("tmp_qwen_ollama_eval/test.json"),
            jsonl=__import__("pathlib").Path("tmp_qwen_ollama_eval/test.jsonl"),
            allow_local_ollama=allow_local_ollama,
        )


if __name__ == "__main__":
    unittest.main()
