from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.evaluate_ollama_advisory_review import EvaluationConfig, evaluate, main, write_report


class OllamaAdvisoryEvaluationScriptTest(unittest.TestCase):
    def test_default_effective_dry_run_does_not_call_ollama(self) -> None:
        called = False

        def transport(payload, timeout_seconds):
            nonlocal called
            called = True
            return {"message": {"content": "{}"}}

        config = self._config(cases=("fall_candidate_support",), allow_local_ollama=False, dry_run=False)

        report = evaluate(config, transport=transport)

        self.assertTrue(report["dry_run"])
        self.assertFalse(called)
        self.assertFalse(report["cases"][0]["called_ollama"])

    def test_allow_local_ollama_required_before_call(self) -> None:
        called_payloads = []

        def transport(payload, timeout_seconds):
            called_payloads.append(payload)
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "schema_version": "vlm_review_result_v1",
                            "support_fall_alarm": True,
                            "semantic_event_type": "fall_candidate",
                            "observed_process": "structured review",
                            "adl_likelihood": "low",
                            "uncertainty": [],
                            "risk_interpretation": "structured evidence only",
                            "alarm_title": "Local advisory",
                            "alarm_body": "Review onsite.",
                            "recommended_action": "Check live stream.",
                        }
                    )
                }
            }

        blocked = evaluate(self._config(cases=("fall_candidate_support",), allow_local_ollama=False), transport=transport)
        allowed = evaluate(self._config(cases=("fall_candidate_support",), allow_local_ollama=True), transport=transport)

        self.assertEqual(len(called_payloads), 1)
        self.assertFalse(blocked["cases"][0]["called_ollama"])
        self.assertTrue(allowed["cases"][0]["called_ollama"])

    def test_non_localhost_endpoint_is_rejected(self) -> None:
        config = self._config(endpoint="https://example.com/api/chat")

        with self.assertRaises(ValueError):
            evaluate(config)

    def test_output_json_and_jsonl_format_are_written(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "eval.json"
            jsonl = Path(tmp) / "eval.jsonl"
            report = evaluate(self._config(cases=("fall_candidate_support", "missing_keyframes"), output=output, jsonl=jsonl))

            write_report(report, output, jsonl)

            loaded = json.loads(output.read_text(encoding="utf-8"))
            lines = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(loaded["summary"]["total_cases"], 2)
            self.assertEqual(len(lines), 2)

    def test_missing_samples_keep_recommendation_conservative(self) -> None:
        report = evaluate(self._config(cases=("fall_candidate_support",), max_cases=1))

        self.assertEqual(report["summary"]["p95_latency_ms"], "not_enough_samples")
        self.assertNotEqual(report["summary"]["recommended_status"], "READY_FOR_STAGING")

    def test_cli_writes_default_dry_run_report(self) -> None:
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "ollama_advisory_eval.json"
            jsonl = Path(tmp) / "ollama_advisory_eval.jsonl"

            exit_code = main(["--max-cases", "1", "--output", str(output), "--jsonl", str(jsonl)])

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())
            self.assertTrue(jsonl.exists())
            self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["dry_run"])

    @staticmethod
    def _config(
        *,
        cases=("fall_candidate_support",),
        max_cases=6,
        endpoint="http://127.0.0.1:11434/api/chat",
        allow_local_ollama=False,
        dry_run=False,
        output=Path("tmp_qwen_ollama_eval/test.json"),
        jsonl=Path("tmp_qwen_ollama_eval/test.jsonl"),
    ) -> EvaluationConfig:
        return EvaluationConfig(
            model="qwen-vision-cn:latest",
            fallback_model="qwen3.5:9b",
            endpoint=endpoint,
            timeout=0.01,
            cases=tuple(cases),
            max_cases=max_cases,
            output=Path(output),
            jsonl=Path(jsonl),
            allow_local_ollama=allow_local_ollama,
            dry_run=dry_run,
        )


if __name__ == "__main__":
    unittest.main()
