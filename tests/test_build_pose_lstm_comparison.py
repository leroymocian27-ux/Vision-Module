from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_pose_lstm_comparison import build_comparison_report, extract_metrics


class BuildPoseLstmComparisonTest(unittest.TestCase):
    def test_extracts_f1_from_event_confusion(self) -> None:
        metrics = extract_metrics(
            {
                "event_metrics": {
                    "confusion": {
                        "true_positive": 9,
                        "false_positive": 2,
                        "false_negative": 1,
                        "true_negative": 20,
                    }
                }
            }
        )

        self.assertAlmostEqual(metrics["precision"], 9 / 11, places=6)
        self.assertAlmostEqual(metrics["recall"], 0.9, places=6)
        self.assertAlmostEqual(metrics["f1"], 0.857143, places=6)
        self.assertEqual(metrics["false_positive_count"], 2)

    def test_comparison_passes_when_pose_lstm_improves_f1_without_more_fp(self) -> None:
        with JsonPair(
            baseline=event_metrics(tp=8, fp=2, fn=2, tn=20),
            pose=event_metrics(tp=9, fp=2, fn=1, tn=20),
        ) as files:
            report = build_comparison_report(baseline_path=files.baseline, pose_path=files.pose)

        self.assertTrue(report["summary"]["comparison"]["passed"])
        self.assertGreater(report["summary"]["comparison"]["f1_delta"], 0)
        self.assertEqual(report["summary"]["comparison"]["false_positive_delta"], 0)

    def test_comparison_blocks_when_pose_f1_does_not_beat_baseline(self) -> None:
        with JsonPair(
            baseline={"summary": {"f1": 0.84, "false_positive_count": 1}},
            pose={"summary": {"f1": 0.83, "false_positive_count": 1}},
        ) as files:
            report = build_comparison_report(baseline_path=files.baseline, pose_path=files.pose)

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn(
            "pose_lstm_not_better_than_baseline_f1",
            report["summary"]["comparison"]["blockers"],
        )

    def test_comparison_blocks_when_pose_false_positive_count_is_worse(self) -> None:
        with JsonPair(
            baseline={"v6_event_metrics": {"fall_event_f1": 0.80, "confusion": {"false_positive": 1}}},
            pose={"v6_event_metrics": {"fall_event_f1": 0.85, "confusion": {"false_positive": 2}}},
        ) as files:
            report = build_comparison_report(baseline_path=files.baseline, pose_path=files.pose)

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn(
            "pose_lstm_false_positives_worse_than_baseline",
            report["summary"]["comparison"]["blockers"],
        )

    def test_comparison_blocks_when_pose_does_not_beat_zero_pose_ablation(self) -> None:
        with JsonTriple(
            baseline={"summary": {"f1": 0.80, "false_positive_count": 2}},
            pose={"summary": {"f1": 0.86, "false_positive_count": 2}},
            ablation={"summary": {"f1": 0.86, "false_positive_count": 2}},
        ) as files:
            report = build_comparison_report(
                baseline_path=files.baseline,
                pose_path=files.pose,
                pose_ablation_path=files.ablation,
            )

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn(
            "pose_lstm_not_better_than_zero_pose_ablation",
            report["summary"]["comparison"]["blockers"],
        )
        self.assertEqual(report["summary"]["comparison"]["zero_pose_ablation_f1_delta"], 0.0)
        self.assertEqual(report["summary"]["pose_lstm_zero_pose_ablation"]["f1"], 0.86)

    def test_comparison_records_pose_manifest_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence = root / "seq.jsonl"
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "require_pose": True,
                        "trainable_input_count": 1,
                        "schema_versions": ["fall_lstm_features_v1"],
                        "schema_hashes": ["schema123"],
                        "input_files": [str(sequence)],
                        "pose_training_gate": {
                            "passed": True,
                            "usable_rows": 10,
                            "pose_available_true_rows": 8,
                            "pose_available_true_ratio": 0.8,
                            "known_pose_quality_ratio": 1.0,
                            "pose_provider_counts": {"yolo11_legacy": 10},
                            "pose_model_path_counts": {"yolo11n-pose.pt": 10},
                            "pose_device_counts": {"cuda:0": 10},
                            "pose_available_missing_provider_rows": 0,
                            "pose_available_missing_model_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_sha256 = sha256_file(manifest)
            baseline = root / "baseline.json"
            pose = root / "pose.json"
            ablation = root / "ablation.json"
            metric_payloads = [
                (
                    baseline,
                    {
                        "summary": {"f1": 0.80, "false_positive_count": 1},
                        "input_files": [str(sequence)],
                        "input_manifest": {"path": str(manifest), "sha256": manifest_sha256},
                        "train_config": {"input_manifest_sha256": "baseline-can-differ"},
                    },
                ),
                (
                    pose,
                    {
                        "summary": {"f1": 0.86, "false_positive_count": 1},
                        "input_files": [str(sequence)],
                        "input_manifest": {"path": str(manifest), "sha256": manifest_sha256},
                        "train_config": {"input_manifest_sha256": manifest_sha256},
                    },
                ),
                (
                    ablation,
                    {
                        "summary": {"f1": 0.82, "false_positive_count": 1},
                        "input_files": [str(sequence)],
                        "input_manifest": {"path": str(manifest), "sha256": manifest_sha256},
                        "train_config": {"input_manifest_sha256": manifest_sha256},
                    },
                ),
            ]
            for path, payload in metric_payloads:
                path.write_text(json.dumps(payload), encoding="utf-8")

            report = build_comparison_report(
                baseline_path=baseline,
                pose_path=pose,
                pose_ablation_path=ablation,
                lstm_manifest_path=manifest,
            )

        provenance = report["summary"]["lstm_manifest"]
        self.assertTrue(report["summary"]["comparison"]["passed"])
        self.assertEqual(provenance["schema_hashes"], ["schema123"])
        self.assertEqual(provenance["pose_provider_counts"]["yolo11_legacy"], 10)
        self.assertEqual(provenance["pose_model_path_counts"]["yolo11n-pose.pt"], 10)
        self.assertEqual(provenance["pose_device_counts"]["cuda:0"], 10)
        self.assertEqual(len(provenance["sha256"]), 64)
        self.assertTrue(provenance["input_files_match_metrics"])
        self.assertTrue(provenance["metric_manifest_sha256s_match_manifest"])
        self.assertTrue(provenance["pose_train_config_manifest_sha256s_match_manifest"])

    def test_comparison_blocks_when_metric_inputs_do_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "require_pose": True,
                        "input_files": [str(root / "manifest_seq.jsonl")],
                        "pose_training_gate": {
                            "passed": True,
                            "pose_available_missing_provider_rows": 0,
                            "pose_available_missing_model_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            baseline = root / "baseline.json"
            pose = root / "pose.json"
            for path, f1 in [(baseline, 0.80), (pose, 0.86)]:
                path.write_text(
                    json.dumps({"summary": {"f1": f1, "false_positive_count": 1}, "input_files": [str(root / "other.jsonl")]}),
                    encoding="utf-8",
                )

            report = build_comparison_report(
                baseline_path=baseline,
                pose_path=pose,
                lstm_manifest_path=manifest,
            )

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn("lstm_metrics_input_files_do_not_match_manifest", report["summary"]["comparison"]["blockers"])
        self.assertIn("lstm_metrics_manifest_sha256s_do_not_match_manifest", report["summary"]["comparison"]["blockers"])

    def test_comparison_blocks_when_metric_manifest_hashes_do_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence = root / "seq.jsonl"
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "require_pose": True,
                        "input_files": [str(sequence)],
                        "pose_training_gate": {
                            "passed": True,
                            "pose_available_missing_provider_rows": 0,
                            "pose_available_missing_model_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            baseline = root / "baseline.json"
            pose = root / "pose.json"
            for path, f1 in [(baseline, 0.80), (pose, 0.86)]:
                path.write_text(
                    json.dumps(
                        {
                            "summary": {"f1": f1, "false_positive_count": 1},
                            "input_files": [str(sequence)],
                            "input_manifest": {"path": str(manifest), "sha256": "b" * 64},
                        }
                    ),
                    encoding="utf-8",
                )

            report = build_comparison_report(
                baseline_path=baseline,
                pose_path=pose,
                lstm_manifest_path=manifest,
            )

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn(
            "lstm_metrics_manifest_sha256s_do_not_match_manifest",
            report["summary"]["comparison"]["blockers"],
        )

    def test_comparison_blocks_when_pose_train_config_hashes_do_not_match_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence = root / "seq.jsonl"
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "require_pose": True,
                        "input_files": [str(sequence)],
                        "pose_training_gate": {
                            "passed": True,
                            "pose_available_missing_provider_rows": 0,
                            "pose_available_missing_model_rows": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            manifest_sha256 = sha256_file(manifest)
            baseline = root / "baseline.json"
            pose = root / "pose.json"
            for path, f1, train_hash in [
                (baseline, 0.80, "baseline-can-differ"),
                (pose, 0.86, "c" * 64),
            ]:
                path.write_text(
                    json.dumps(
                        {
                            "summary": {"f1": f1, "false_positive_count": 1},
                            "input_files": [str(sequence)],
                            "input_manifest": {"path": str(manifest), "sha256": manifest_sha256},
                            "train_config": {"input_manifest_sha256": train_hash},
                        }
                    ),
                    encoding="utf-8",
                )

            report = build_comparison_report(
                baseline_path=baseline,
                pose_path=pose,
                lstm_manifest_path=manifest,
            )

        self.assertFalse(report["summary"]["comparison"]["passed"])
        self.assertIn(
            "pose_lstm_train_config_manifest_sha256s_do_not_match_manifest",
            report["summary"]["comparison"]["blockers"],
        )


def event_metrics(*, tp: int, fp: int, fn: int, tn: int) -> dict:
    return {
        "event_metrics": {
            "confusion": {
                "true_positive": tp,
                "false_positive": fp,
                "false_negative": fn,
                "true_negative": tn,
            }
        }
    }


class JsonPair:
    def __init__(self, *, baseline: dict, pose: dict) -> None:
        self.payloads = {"baseline.json": baseline, "pose.json": pose}

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, payload in self.payloads.items():
            (self.root / name).write_text(json.dumps(payload), encoding="utf-8")
        self.baseline = self.root / "baseline.json"
        self.pose = self.root / "pose.json"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tmp.cleanup()


class JsonTriple(JsonPair):
    def __init__(self, *, baseline: dict, pose: dict, ablation: dict) -> None:
        self.payloads = {"baseline.json": baseline, "pose.json": pose, "ablation.json": ablation}

    def __enter__(self):
        super().__enter__()
        self.ablation = self.root / "ablation.json"
        return self


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
