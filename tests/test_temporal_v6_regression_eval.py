from __future__ import annotations

import unittest

from scripts.run_temporal_v6_regression_eval import build_comparison, temporal_runtime_config


class TemporalV6RegressionEvalTest(unittest.TestCase):
    def test_build_comparison_reports_confusion_delta(self) -> None:
        baseline = {
            "report": "baseline.md",
            "event_metrics": {
                "confusion": {
                    "true_positive": 3,
                    "false_negative": 1,
                    "false_positive": 4,
                    "true_negative": 8,
                },
                "v6": {
                    "motion_path_distribution": {},
                },
            },
            "videos": [
                {
                    "video": "adl-01.mp4",
                    "manifest_label": "non_fall",
                    "expected_alarm": False,
                    "hard_negative_type": "squatting",
                    "alarm_confirmed_frames": 2,
                    "confirmed_frames": 2,
                },
                {
                    "video": "fall-01.mp4",
                    "manifest_label": "fall",
                    "expected_alarm": True,
                    "alarm_confirmed_frames": 1,
                    "confirmed_frames": 1,
                },
            ],
        }
        v6 = {
            "report": "v6.md",
            "event_metrics": {
                "confusion": {
                    "true_positive": 3,
                    "false_negative": 1,
                    "false_positive": 2,
                    "true_negative": 10,
                },
                "v6": {
                    "motion_path_distribution": {
                        "fast_fall_path": 3,
                        "slow_fall_path": 2,
                    },
                },
            },
            "videos": [
                {
                    "video": "adl-01.mp4",
                    "manifest_label": "non_fall",
                    "expected_alarm": False,
                    "hard_negative_type": "squatting",
                    "alarm_confirmed_frames": 0,
                    "confirmed_frames": 0,
                },
                {
                    "video": "fall-01.mp4",
                    "manifest_label": "fall",
                    "expected_alarm": True,
                    "alarm_confirmed_frames": 1,
                    "confirmed_frames": 1,
                },
            ],
        }

        comparison = build_comparison(baseline, v6)

        self.assertEqual(comparison["delta"]["false_positive"], -2)
        self.assertEqual(comparison["delta"]["false_negative"], 0)
        self.assertTrue(comparison["acceptance_hint"]["fp_not_worse"])
        self.assertTrue(comparison["acceptance_hint"]["fn_not_worse"])
        self.assertTrue(comparison["acceptance_hint"]["fast_path_observed"])
        self.assertTrue(comparison["acceptance_hint"]["slow_path_observed"])
        self.assertTrue(comparison["acceptance_hint"]["no_duplicate_alarm"])
        self.assertEqual(comparison["hard_negative_summary"]["squatting"]["fp_improved"], 1)
        self.assertEqual(comparison["per_video"][0]["outcome_delta"], "fp_improved")
        self.assertEqual(comparison["temporal_runtime_config"], {})

    def test_build_comparison_records_temporal_runtime_config(self) -> None:
        baseline = {"event_metrics": {"confusion": {}, "v6": {}}, "videos": []}
        v6 = {"event_metrics": {"confusion": {}, "v6": {}}, "videos": []}
        runtime = temporal_runtime_config(
            provider="shadow",
            model_path="models/fall_lstm_v6.onnx",
            schema_path="models/fall_lstm_v6_features.json",
        )

        comparison = build_comparison(baseline, v6, temporal_config=runtime)

        self.assertEqual(
            comparison["temporal_runtime_config"],
            {
                "TEMPORAL_MODEL_PROVIDER": "shadow",
                "TEMPORAL_ONNX_MODEL_PATH": "models/fall_lstm_v6.onnx",
                "TEMPORAL_FEATURE_SCHEMA_PATH": "models/fall_lstm_v6_features.json",
            },
        )


if __name__ == "__main__":
    unittest.main()
