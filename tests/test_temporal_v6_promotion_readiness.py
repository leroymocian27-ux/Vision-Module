from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_temporal_v6_promotion_readiness import check_readiness


class TemporalV6PromotionReadinessTest(unittest.TestCase):
    def test_not_ready_when_artifacts_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = check_readiness(
                model_path=root / "fall_lstm_v6.onnx",
                schema_path=root / "fall_lstm_v6_features.json",
                metrics_path=root / "fall_lstm_v6_metrics.json",
                train_config_path=root / "fall_lstm_v6_train_config.json",
                candidate_summary_path=root / "candidate.json",
            )

        self.assertFalse(result["ready"])
        self.assertIsNone(result["promotion_env"])

    def test_ready_when_artifacts_and_acceptance_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "fall_lstm_v6.onnx"
            schema = root / "fall_lstm_v6_features.json"
            metrics = root / "fall_lstm_v6_metrics.json"
            train_config = root / "fall_lstm_v6_train_config.json"
            candidate = root / "candidate.json"
            model.write_bytes(b"onnx")
            schema.write_text(json.dumps({"schema_version": "fall_lstm_features_v1"}), encoding="utf-8")
            metrics.write_text(
                json.dumps({"trained_from_inputs": ["a.jsonl"], "onnx_validation": {"passed": True}}),
                encoding="utf-8",
            )
            train_config.write_text(
                json.dumps({"input_manifest": "data/temporal_v6_training/lstm_v6_training_manifest.json", "input_count": 1}),
                encoding="utf-8",
            )
            candidate.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "comparison_paths": {
                            "slow_fall": "slow.json",
                            "fp_regression": "fp.json",
                            "ur_mini": "ur.json",
                        },
                        "acceptance_gate": {
                            "passed": True,
                            "summary": {"slow_fall_recall": 0.84},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = check_readiness(
                model_path=model,
                schema_path=schema,
                metrics_path=metrics,
                train_config_path=train_config,
                candidate_summary_path=candidate,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["promotion_env"]["TEMPORAL_MODEL_PROVIDER"], "shadow")

    def test_not_ready_when_candidate_acceptance_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "fall_lstm_v6.onnx"
            schema = root / "fall_lstm_v6_features.json"
            metrics = root / "fall_lstm_v6_metrics.json"
            train_config = root / "fall_lstm_v6_train_config.json"
            candidate = root / "candidate.json"
            model.write_bytes(b"onnx")
            schema.write_text("{}", encoding="utf-8")
            metrics.write_text(json.dumps({"trained_from_inputs": ["a.jsonl"], "onnx_validation": {"passed": True}}), encoding="utf-8")
            train_config.write_text(json.dumps({"input_manifest": "manifest.json", "input_count": 1}), encoding="utf-8")
            candidate.write_text(json.dumps({"status": "ok", "comparison_paths": {"slow_fall": "s", "fp_regression": "f", "ur_mini": "u"}, "acceptance_gate": {"passed": False}}), encoding="utf-8")

            result = check_readiness(
                model_path=model,
                schema_path=schema,
                metrics_path=metrics,
                train_config_path=train_config,
                candidate_summary_path=candidate,
            )

        self.assertFalse(result["ready"])
        failed = [check["name"] for check in result["checks"] if not check["passed"]]
        self.assertIn("candidate_acceptance_passed", failed)


if __name__ == "__main__":
    unittest.main()
