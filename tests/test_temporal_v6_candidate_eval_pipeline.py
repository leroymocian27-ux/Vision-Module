from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_temporal_v6_candidate_eval_pipeline import (
    build_commands,
    candidate_comparison_paths,
    run_candidate_pipeline,
)


class TemporalV6CandidateEvalPipelineTest(unittest.TestCase):
    def test_build_commands_include_candidate_model_config(self) -> None:
        commands = build_commands(
            model_path="models/fall_lstm_v6.onnx",
            schema_path="models/fall_lstm_v6_features.json",
            temporal_provider="shadow",
            output_root=Path("evaluations/fall_temporal_v6"),
        )

        slow = commands["slow_fall"]
        self.assertIn("--temporal-provider", slow)
        self.assertIn("shadow", slow)
        self.assertIn("--temporal-model-path", slow)
        self.assertIn("models/fall_lstm_v6.onnx", slow)
        self.assertIn("--temporal-schema-path", slow)
        self.assertIn("models/fall_lstm_v6_features.json", slow)

    def test_dry_run_writes_summary_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "summary.json"

            result = run_candidate_pipeline(
                model_path="models/fall_lstm_v6.onnx",
                schema_path="models/fall_lstm_v6_features.json",
                temporal_provider="shadow",
                output_root=root / "evals",
                summary_path=summary,
                dry_run=True,
                skip_eval=False,
            )
            summary_exists = summary.exists()

        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(summary_exists)
        self.assertIsNone(result["acceptance_gate"])

    def test_skip_eval_reports_missing_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = run_candidate_pipeline(
                model_path="models/fall_lstm_v6.onnx",
                schema_path="models/fall_lstm_v6_features.json",
                temporal_provider="shadow",
                output_root=root / "evals",
                summary_path=root / "summary.json",
                dry_run=False,
                skip_eval=True,
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "missing_candidate_comparison_json")
        self.assertEqual(len(result["missing"]), 3)

    def test_skip_eval_checks_existing_candidate_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "evals"
            for key, path in candidate_comparison_paths(output_root).items():
                path.parent.mkdir(parents=True)
                payload = comparison_payload(recall=0.84 if key == "slow_fall" else None, fp=0)
                path.write_text(json.dumps(payload), encoding="utf-8")

            result = run_candidate_pipeline(
                model_path="models/fall_lstm_v6.onnx",
                schema_path="models/fall_lstm_v6_features.json",
                temporal_provider="shadow",
                output_root=output_root,
                summary_path=root / "summary.json",
                dry_run=False,
                skip_eval=True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["acceptance_gate"]["passed"])


def comparison_payload(*, recall: float | None, fp: int) -> dict:
    return {
        "v6_event_metrics": {
            "fall_event_recall": recall,
            "confusion": {
                "true_positive": 25 if recall else 0,
                "false_negative": 5 if recall else 0,
                "false_positive": fp,
                "true_negative": 33 if recall is None else 0,
            },
        },
        "duplicate_alarm_videos": [],
    }


if __name__ == "__main__":
    unittest.main()
