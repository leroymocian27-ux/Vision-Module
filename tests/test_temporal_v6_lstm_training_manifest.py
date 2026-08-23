from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_temporal_v6_lstm_training_manifest import build_manifest


class TemporalV6LstmTrainingManifestTest(unittest.TestCase):
    def test_builds_manifest_with_base_and_residual_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            output = root / "manifest.json"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(base_dir / "adl-01.jsonl", label="non_fall", subtype="sitting")
            write_sequence(base_dir / "fall-01.jsonl", label="fall", subtype=None)
            reviewed = residual_dir / "ur_fall" / "fall-21.jsonl"
            reviewed.parent.mkdir()
            write_sequence(reviewed, label="fall", subtype="slow_fall", review_source="temporal_v6_residual_review")
            (residual_dir / "train_inputs.json").write_text(
                json.dumps({"input_files": ["ur_fall/fall-21.jsonl"]}),
                encoding="utf-8",
            )

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=output,
                model_version="v6_test",
                epochs=3,
                stride=2,
            )

        self.assertEqual(manifest["base_input_count"], 2)
        self.assertTrue(manifest["include_residual"])
        self.assertEqual(manifest["residual_input_count"], 1)
        self.assertEqual(manifest["residual_reviewed_input_count"], 1)
        self.assertEqual(manifest["label_counts"]["fall"], 4)
        self.assertEqual(manifest["label_counts"]["non_fall"], 2)
        self.assertEqual(manifest["acceptance_gates_after_training"]["slow_fall_review_recall_min"], 0.80)
        self.assertFalse(manifest["require_pose"])
        self.assertIn("pose_training_gate", manifest)
        self.assertIn("--input-manifest", manifest["train_command"])
        self.assertIn("--model-version v6_test", manifest["train_command"])

    def test_skips_files_with_no_usable_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(base_dir / "bad.jsonl", label="fall", subtype=None, usable=False)

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=root / "manifest.json",
                model_version="v6",
                epochs=1,
                stride=1,
            )

        self.assertEqual(manifest["trainable_input_count"], 0)
        self.assertEqual(manifest["skipped_unusable_input_count"], 1)
        self.assertIsNone(manifest["train_command"])

    def test_require_pose_blocks_unknown_pose_quality_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(base_dir / "old.jsonl", label="fall", subtype=None)

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=root / "manifest.json",
                model_version="v6_pose",
                epochs=1,
                stride=1,
                require_pose=True,
                min_pose_available_ratio=0.05,
                min_known_pose_quality_ratio=0.95,
            )

        self.assertFalse(manifest["pose_training_gate"]["passed"])
        self.assertEqual(manifest["pose_training_gate"]["pose_quality_counts"]["unknown"], 2)
        self.assertIsNone(manifest["train_command"])

    def test_require_pose_allows_pose_aware_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(
                base_dir / "pose.jsonl",
                label="fall",
                subtype=None,
                pose_available=True,
                pose_quality_level="high_confidence",
            )

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=root / "manifest.json",
                model_version="v6_pose",
                epochs=1,
                stride=1,
                require_pose=True,
                min_pose_available_ratio=0.05,
                min_known_pose_quality_ratio=0.95,
            )

        self.assertTrue(manifest["pose_training_gate"]["passed"])
        self.assertEqual(manifest["pose_training_gate"]["pose_available_true_rows"], 2)
        self.assertEqual(manifest["pose_training_gate"]["pose_provider_counts"]["yolo11_legacy"], 2)
        self.assertEqual(manifest["pose_training_gate"]["pose_model_path_counts"]["yolo11n-pose.pt"], 2)
        self.assertIn("--model-version v6_pose", manifest["train_command"])

    def test_require_pose_blocks_available_pose_without_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(
                base_dir / "pose_without_runtime.jsonl",
                label="fall",
                subtype=None,
                pose_available=True,
                pose_quality_level="valid",
                include_pose_runtime=False,
            )

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=root / "manifest.json",
                model_version="v6_pose",
                epochs=1,
                stride=1,
                require_pose=True,
                min_pose_available_ratio=0.05,
                min_known_pose_quality_ratio=0.95,
            )

        self.assertFalse(manifest["pose_training_gate"]["passed"])
        self.assertEqual(manifest["pose_training_gate"]["pose_available_missing_provider_rows"], 2)
        self.assertEqual(manifest["pose_training_gate"]["pose_available_missing_model_rows"], 2)
        self.assertIsNone(manifest["train_command"])

    def test_can_skip_residual_inputs_for_pose_smoke_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_dir = root / "base"
            residual_dir = root / "residual"
            base_dir.mkdir()
            residual_dir.mkdir()
            write_sequence(
                base_dir / "pose.jsonl",
                label="fall",
                subtype=None,
                pose_available=True,
                pose_quality_level="high_confidence",
            )
            write_sequence(residual_dir / "old_residual.jsonl", label="fall", subtype=None)

            manifest = build_manifest(
                base_dirs=[base_dir],
                residual_dir=residual_dir,
                output_path=root / "manifest.json",
                model_version="v6_pose_smoke",
                epochs=1,
                stride=1,
                require_pose=True,
                include_residual=False,
            )

        self.assertFalse(manifest["include_residual"])
        self.assertEqual(manifest["residual_input_count"], 0)
        self.assertTrue(manifest["pose_training_gate"]["passed"])
        self.assertNotIn("unknown", manifest["pose_training_gate"]["pose_quality_counts"])


def write_sequence(
    path: Path,
    *,
    label: str,
    subtype: str | None,
    review_source: str | None = None,
    usable: bool = True,
    pose_available: bool | None = None,
    pose_quality_level: str | None = None,
    include_pose_runtime: bool = True,
) -> None:
    rows = []
    for frame_seq in range(2):
        row = {
                "schema_version": "fall_lstm_features_v1",
                "schema_hash": "db4246cef1eb39a1",
                "sequence_key": f"track:{path.stem}:1",
                "split_group": path.stem,
                "split": "unassigned",
                "frame_seq": frame_seq,
                "vector": [0.0] * 15,
                "label": label,
                "non_fall_subtype": subtype if label == "non_fall" else None,
                "fall_subtype": subtype if label == "fall" else None,
                "review_source": review_source,
                "usable_for_training": usable,
            }
        if pose_available is not None or pose_quality_level is not None:
            row["target_feature"] = {
                "pose_available": bool(pose_available),
                "pose_confidence": 0.9 if pose_available else 0.0,
                "pose_quality_level": pose_quality_level or "pose_absent",
                "pose_rejected_reason": None,
            }
            if include_pose_runtime:
                row["pose_runtime"] = {
                    "pose_enabled": True,
                    "pose_provider": "yolo11_legacy",
                    "pose_model_path": "yolo11n-pose.pt",
                    "pose_device": "cuda:0",
                }
        rows.append(row)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
