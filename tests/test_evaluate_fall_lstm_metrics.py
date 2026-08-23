from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.evaluate_fall_lstm_metrics import build_report, load_windows, metrics_at_threshold


class EvaluateFallLstmMetricsTest(unittest.TestCase):
    def test_load_windows_filters_split_and_can_zero_pose_features(self) -> None:
        schema = test_schema()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seq.jsonl"
            rows = [
                row(schema, group="g1", key="fall", frame=i, label="fall", split="test", pose_value=1.0)
                for i in range(3)
            ]
            rows.extend(
                row(schema, group="g2", key="adl", frame=i, label="non_fall", split="train", pose_value=1.0)
                for i in range(3)
            )
            write_jsonl(path, rows)

            windows = load_windows([path], schema, stride=1, split="test", seed=42, zero_pose_features=True)

        self.assertEqual(len(windows), 2)
        self.assertEqual({item["label"] for item in windows}, {1})
        first_vector = windows[0]["x"][0]
        self.assertEqual(first_vector[2], 0.0)
        self.assertEqual(first_vector[3], -1.0)

    def test_metrics_at_threshold_reports_confusion_and_f1(self) -> None:
        result = metrics_at_threshold(
            np.asarray([0.9, 0.7, 0.4, 0.2], dtype=np.float32),
            np.asarray([1, 0, 1, 0], dtype=np.int32),
            ["fall", "sitting", "fall", "standing"],
            threshold=0.65,
        )

        self.assertEqual(
            result["confusion"],
            {"true_positive": 1, "false_positive": 1, "false_negative": 1, "true_negative": 1},
        )
        self.assertEqual(result["subtype_false_positive_counts"], {"sitting": 1})
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(result["f1"], 0.5)

    def test_build_report_outputs_event_metrics_for_comparison_gate(self) -> None:
        windows = [
            {"label": 1, "split": "test", "non_fall_subtype": None},
            {"label": 0, "split": "test", "non_fall_subtype": "squatting"},
        ]
        report = build_report(
            probabilities=np.asarray([0.8, 0.2], dtype=np.float32),
            windows=windows,
            model_path=Path("model.onnx"),
            schema_path=Path("features.json"),
            train_config_path=None,
            input_paths=[Path("input.jsonl")],
            input_manifest_path=None,
            split="test",
            stride=4,
            threshold=0.65,
            zero_pose_features=False,
        )

        self.assertEqual(report["summary"]["f1"], 1.0)
        self.assertEqual(report["summary"]["false_positive_count"], 0)
        self.assertEqual(report["event_metrics"]["fall_event_f1"], 1.0)
        self.assertEqual(report["event_metrics"]["confusion"]["true_positive"], 1)
        self.assertIsNone(report["train_config"])
        self.assertIsNone(report["input_manifest"])

    def test_build_report_records_input_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text('{"input_files":["input.jsonl"]}', encoding="utf-8")
            windows = [{"label": 1, "split": "test", "non_fall_subtype": None}]

            report = build_report(
                probabilities=np.asarray([0.8], dtype=np.float32),
                windows=windows,
                model_path=Path("model.onnx"),
                schema_path=Path("features.json"),
                train_config_path=None,
                input_paths=[Path("input.jsonl")],
                input_manifest_path=manifest,
                split="test",
                stride=4,
                threshold=0.65,
                zero_pose_features=False,
            )

        self.assertEqual(report["input_manifest"]["path"], str(manifest))
        self.assertEqual(len(report["input_manifest"]["sha256"]), 64)

    def test_build_report_records_train_config_hash_and_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train_config = root / "train_config.json"
            train_config.write_text(
                json.dumps(
                    {
                        "input_manifest": "manifest.json",
                        "input_manifest_sha256": "a" * 64,
                        "input_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            windows = [{"label": 1, "split": "test", "non_fall_subtype": None}]

            report = build_report(
                probabilities=np.asarray([0.8], dtype=np.float32),
                windows=windows,
                model_path=Path("model.onnx"),
                schema_path=Path("features.json"),
                train_config_path=train_config,
                input_paths=[Path("input.jsonl")],
                input_manifest_path=None,
                split="test",
                stride=4,
                threshold=0.65,
                zero_pose_features=False,
            )

        self.assertEqual(report["train_config"]["path"], str(train_config))
        self.assertEqual(len(report["train_config"]["sha256"]), 64)
        self.assertEqual(report["train_config"]["input_manifest_sha256"], "a" * 64)


def test_schema() -> dict:
    return {
        "schema_version": "test_schema",
        "schema_hash": "abc123",
        "input_dim": 4,
        "window_size": 2,
        "feature_names": ["bbox", "speed", "pose_available", "head_height_ratio_filled"],
        "missing_pose_fill": {
            "pose_available": 0.0,
            "head_height_ratio_filled": -1.0,
        },
    }


def row(
    schema: dict,
    *,
    group: str,
    key: str,
    frame: int,
    label: str,
    split: str,
    pose_value: float,
) -> dict:
    return {
        "schema_version": schema["schema_version"],
        "schema_hash": schema["schema_hash"],
        "sequence_key": key,
        "split_group": group,
        "frame_seq": frame,
        "split": split,
        "usable_for_training": True,
        "vector": [0.1, 0.2, pose_value, pose_value],
        "label": label,
        "non_fall_subtype": "squatting" if label == "non_fall" else None,
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
