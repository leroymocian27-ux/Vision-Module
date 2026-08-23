from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_temporal_v6_post_review_pipeline import run_pipeline


class TemporalV6PostReviewPipelineTest(unittest.TestCase):
    def test_pipeline_reports_not_ready_without_reviewed_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp), approved=False)

            result = run_test_pipeline(env)

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["ready_for_training"])
        self.assertEqual(result["reviewed_training_dataset"]["trainable_review_rows"], 0)
        self.assertEqual(result["apply_review_sheet"]["changed_count"], 0)

    def test_pipeline_becomes_ready_with_valid_reviewed_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = make_env(Path(tmp), approved=True)

            result = run_test_pipeline(env)

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["ready_for_training"])
        self.assertEqual(result["reviewed_training_dataset"]["trainable_review_rows"], 1)
        self.assertEqual(result["reviewed_training_dataset"]["written_sequences"], 1)
        self.assertEqual(result["lstm_training_manifest"]["residual_reviewed_input_count"], 1)


def run_test_pipeline(env: dict[str, Path]) -> dict:
    fake_acceptance = {
        "passed": False,
        "summary": {"slow_fall_recall": 0.7},
        "checks": [{"name": "slow_fall_review_recall", "passed": False, "actual": 0.7, "required": ">= 0.80"}],
    }
    with patch("scripts.run_temporal_v6_post_review_pipeline.check_acceptance", return_value=fake_acceptance):
        return run_pipeline(
            sheet_path=env["sheet"],
            review_path=env["review"],
            sequence_root=env["sequence_root"],
            residual_output_dir=env["residual_output"],
            lstm_manifest_path=env["lstm_manifest"],
            summary_path=env["summary"],
            fps=25.0,
            dry_run=False,
        )


def make_env(root: Path, *, approved: bool) -> dict[str, Path]:
    sheet = root / "sheet.csv"
    review = root / "review.jsonl"
    sequence_root = root / "sequences"
    source_sequence = sequence_root / "ur_fall" / "fall-08.jsonl"
    residual_output = root / "residual"
    lstm_manifest = root / "lstm_manifest.json"
    summary = root / "summary.json"
    source_sequence.parent.mkdir(parents=True)
    write_review(review)
    write_sheet(sheet, approved=approved)
    write_sequence(source_sequence)
    return {
        "sheet": sheet,
        "review": review,
        "sequence_root": sequence_root,
        "residual_output": residual_output,
        "lstm_manifest": lstm_manifest,
        "summary": summary,
    }


def write_review(path: Path) -> None:
    row = {
        "video_id": "ur_fall/fall-08.mp4",
        "source_dataset": "ur_fall",
        "binary_label": "fall",
        "expected_alarm": True,
        "review_status": "needs_temporal_review",
        "usable_for_training": False,
        "review_decision": "",
        "fall_subtype": "hard_recall_fall",
        "scene_type": "floor_risk_zone",
        "support_surface": "none",
        "fall_start_ms": None,
        "ground_contact_start_ms": None,
        "low_posture_start_ms": None,
        "motion_end_ms": None,
        "recovery_start_ms": None,
        "recovered_within_5s": None,
        "occlusion_level": "unknown",
        "track_quality_issue": False,
        "pose_quality_issue": False,
        "reviewer": None,
        "review_notes": "",
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def write_sheet(path: Path, *, approved: bool) -> None:
    fields = [
        "video_id",
        "review_status",
        "usable_for_training",
        "review_decision",
        "fall_start_ms",
        "ground_contact_start_ms",
        "low_posture_start_ms",
        "motion_end_ms",
        "recovery_start_ms",
        "recovered_within_5s",
        "scene_type",
        "support_surface",
        "occlusion_level",
        "track_quality_issue",
        "pose_quality_issue",
        "fall_subtype",
        "reviewer",
        "review_notes",
    ]
    if approved:
        row = {
            "video_id": "ur_fall/fall-08.mp4",
            "review_status": "reviewed",
            "usable_for_training": "true",
            "review_decision": "confirmed_fall_train",
            "fall_start_ms": "40",
            "ground_contact_start_ms": "80",
            "low_posture_start_ms": "80",
            "motion_end_ms": "120",
            "recovery_start_ms": "",
            "recovered_within_5s": "false",
            "scene_type": "floor_risk_zone",
            "support_surface": "none",
            "occlusion_level": "low",
            "track_quality_issue": "false",
            "pose_quality_issue": "false",
            "fall_subtype": "hard_recall_fall",
            "reviewer": "professor_a",
            "review_notes": "Confirmed fall.",
        }
    else:
        row = {"video_id": "ur_fall/fall-08.mp4", "review_status": "needs_temporal_review", "usable_for_training": "false"}
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


def write_sequence(path: Path) -> None:
    rows = []
    for frame_seq in range(0, 40):
        rows.append(
            {
                "schema_version": "fall_lstm_features_v1",
                "schema_hash": "db4246cef1eb39a1",
                "sequence_key": "track:test:1",
                "split_group": "fall-08",
                "split": "unassigned",
                "frame_seq": frame_seq,
                "vector": [0.0] * 15,
                "label": "fall",
                "usable_for_training": True,
                "track_quality": {},
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
