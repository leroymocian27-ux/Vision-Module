from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_temporal_v6_training_dataset import build_dataset
from scripts.train_fall_lstm import (
    calibration_windows,
    ensure_onnx_export_dependencies,
    input_file_sha256s,
    load_windows,
    manifest_metadata,
    resolve_input_paths,
    threshold_is_better,
)


class TemporalV6TrainingDatasetTest(unittest.TestCase):
    def test_builds_reviewed_sequence_with_event_frame_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence_root = root / "sequences"
            output_dir = root / "out"
            source = sequence_root / "ur_fall" / "fall-21.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                "".join(
                    json.dumps(sequence_row(frame_seq=frame_seq, label="fall")) + "\n"
                    for frame_seq in [0, 10, 20, 30]
                ),
                encoding="utf-8",
            )
            review_rows = [
                {
                    "video_id": "ur_fall/fall-21.mp4",
                    "review_status": "reviewed",
                    "usable_for_training": True,
                    "review_decision": "confirmed_fall_train",
                    "fall_subtype": "slow_fall",
                    "fall_start_ms": 400,
                    "ground_contact_start_ms": 600,
                    "low_posture_start_ms": 600,
                    "motion_end_ms": 800,
                    "recovery_start_ms": None,
                    "recovered_within_5s": False,
                    "scene_type": "floor_risk_zone",
                    "support_surface": "none",
                    "occlusion_level": "low",
                    "track_quality_issue": False,
                    "pose_quality_issue": False,
                    "reviewer": "professor_a",
                    "review_notes": "Confirmed slow fall.",
                }
            ]

            summary = build_dataset(
                review_rows=review_rows,
                sequence_root=sequence_root,
                output_dir=output_dir,
                fps=25.0,
                review_path=root / "review.jsonl",
            )

            output_rows = [
                json.loads(line)
                for line in (output_dir / "ur_fall" / "fall-21.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(summary["written_sequences"], 1)
        self.assertEqual(summary["fall_frame_rows"], 2)
        self.assertEqual([row["label"] for row in output_rows], ["non_fall", "fall", "fall", "non_fall"])
        self.assertEqual(output_rows[1]["event_start_frame"], 10)
        self.assertEqual(output_rows[1]["event_end_frame"], 20)
        self.assertEqual(output_rows[1]["fall_subtype"], "slow_fall")
        self.assertEqual(output_rows[1]["track_quality"]["occlusion_level"], "low")

    def test_no_reviewed_rows_writes_empty_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "out"

            summary = build_dataset(
                review_rows=[
                    {
                        "video_id": "ur_fall/fall-08.mp4",
                        "review_status": "needs_temporal_review",
                        "usable_for_training": False,
                    }
                ],
                sequence_root=root / "sequences",
                output_dir=output_dir,
                fps=25.0,
            )
            manifest = json.loads((output_dir / "train_inputs.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["written_sequences"], 0)
        self.assertEqual(manifest["input_files"], [])

    def test_hard_negative_row_writes_non_fall_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sequence_root = root / "sequences"
            output_dir = root / "out"
            source = sequence_root / "ur_fall" / "adl-01.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                "".join(
                    json.dumps(sequence_row(frame_seq=frame_seq, label="non_fall")) + "\n"
                    for frame_seq in [0, 10, 20, 30]
                ),
                encoding="utf-8",
            )
            review_rows = [
                {
                    "video_id": "ur_fall/adl-01.mp4",
                    "review_status": "reviewed",
                    "usable_for_training": True,
                    "review_decision": "hard_negative_train",
                    "fall_subtype": "slow_fall_or_lying_ambiguous",
                    "fall_start_ms": 400,
                    "ground_contact_start_ms": 600,
                    "low_posture_start_ms": 600,
                    "motion_end_ms": 800,
                    "recovery_start_ms": 1200,
                    "recovered_within_5s": True,
                    "scene_type": "adl_floor_or_mixed_zone",
                    "support_surface": "none",
                    "occlusion_level": "low",
                    "track_quality_issue": False,
                    "pose_quality_issue": False,
                    "reviewer": "professor_a",
                    "review_notes": "voluntary_lying",
                }
            ]

            summary = build_dataset(
                review_rows=review_rows,
                sequence_root=sequence_root,
                output_dir=output_dir,
                fps=25.0,
                review_path=root / "review.jsonl",
            )

            output_rows = [
                json.loads(line)
                for line in (output_dir / "ur_fall" / "adl-01.jsonl").read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(summary["written_sequences"], 1)
        self.assertEqual(summary["fall_frame_rows"], 0)
        self.assertEqual([row["label"] for row in output_rows], ["non_fall", "non_fall", "non_fall", "non_fall"])
        self.assertEqual(output_rows[0]["non_fall_subtype"], "voluntary_lying")

    def test_lstm_loader_skips_unusable_frames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.jsonl"
            rows = [
                tiny_train_row("good", 0, label="non_fall", usable=True),
                tiny_train_row("good", 1, label="non_fall", usable=True),
                tiny_train_row("bad", 0, label="fall", usable=False),
                tiny_train_row("bad", 1, label="fall", usable=False),
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

            windows = load_windows(
                [str(path)],
                {"schema_version": "test_schema", "schema_hash": "test_hash", "window_size": 2, "input_dim": 1},
                stride=1,
                seed=1,
            )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["label"], 0)

    def test_lstm_input_manifest_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({"input_files": ["data/temporal_sequences_phase6d/ur_fall/fall-01.jsonl"]}),
                encoding="utf-8",
            )

            paths = resolve_input_paths(None, str(manifest))

        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("data\\temporal_sequences_phase6d\\ur_fall\\fall-01.jsonl") or paths[0].endswith("data/temporal_sequences_phase6d/ur_fall/fall-01.jsonl"))

    def test_lstm_training_provenance_hashes_manifest_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"
            sequence = root / "seq.jsonl"
            manifest.write_text('{"input_files":["seq.jsonl"]}', encoding="utf-8")
            sequence.write_text('{"row":1}\n', encoding="utf-8")

            metadata = manifest_metadata(manifest)
            input_hashes = input_file_sha256s([str(sequence)])

        self.assertEqual(metadata["path"], str(manifest))
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertEqual(list(input_hashes), [str(sequence.resolve())])
        self.assertEqual(len(next(iter(input_hashes.values()))), 64)

    def test_lstm_training_checks_onnx_export_dependency_before_training(self) -> None:
        with patch("scripts.train_fall_lstm.importlib.util.find_spec", return_value=None):
            with self.assertRaises(SystemExit) as ctx:
                ensure_onnx_export_dependencies()

        self.assertIn("onnx package is required", str(ctx.exception))

    def test_threshold_calibration_prefers_val_then_train(self) -> None:
        windows = [
            {"split": "train", "label": 0},
            {"split": "train", "label": 1},
            {"split": "val", "label": 0},
            {"split": "val", "label": 1},
        ]

        scope, selected = calibration_windows(windows)

        self.assertEqual(scope, "val")
        self.assertEqual(len(selected), 2)

    def test_threshold_calibration_falls_back_to_train_for_dev_smoke(self) -> None:
        windows = [
            {"split": "train", "label": 0},
            {"split": "train", "label": 1},
            {"split": "val", "label": 1},
        ]

        scope, selected = calibration_windows(windows)

        self.assertEqual(scope, "train")
        self.assertEqual(len(selected), 2)

    def test_threshold_tie_breaker_prefers_fewer_fp_then_higher_threshold(self) -> None:
        current = {"f1": 0.75, "false_positive_count": 2, "threshold": 0.45}
        same_f1_less_fp = {"f1": 0.75, "false_positive_count": 1, "threshold": 0.35}
        same_f1_fp_higher_threshold = {"f1": 0.75, "false_positive_count": 2, "threshold": 0.5}

        self.assertTrue(threshold_is_better(same_f1_less_fp, current))
        self.assertTrue(threshold_is_better(same_f1_fp_higher_threshold, current))


def sequence_row(*, frame_seq: int, label: str) -> dict:
    return {
        "schema_version": "fall_lstm_features_v1",
        "schema_hash": "db4246cef1eb39a1",
        "feature_names": ["x"],
        "camera_id": "camera_01",
        "video_id": "ur_fall/fall-21.mp4",
        "source_dataset": "ur_fall",
        "split_group": "fall_21",
        "split": "unassigned",
        "usable_for_training": True,
        "track_id": 1,
        "sequence_key": "track:camera_01:1",
        "frame_seq": frame_seq,
        "vector": [0.0] * 15,
        "label": label,
        "track_quality": {},
    }


def tiny_train_row(sequence: str, frame_seq: int, *, label: str, usable: bool) -> dict:
    return {
        "schema_version": "test_schema",
        "schema_hash": "test_hash",
        "sequence_key": sequence,
        "split_group": sequence,
        "split": "unassigned",
        "frame_seq": frame_seq,
        "vector": [0.0],
        "label": label,
        "usable_for_training": usable,
    }


if __name__ == "__main__":
    unittest.main()
