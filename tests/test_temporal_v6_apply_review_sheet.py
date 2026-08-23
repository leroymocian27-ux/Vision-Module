from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.apply_temporal_v6_review_sheet import apply_review_sheet


class TemporalV6ApplyReviewSheetTest(unittest.TestCase):
    def test_applies_reviewed_review_fields_to_seed_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            output = root / "updated.jsonl"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(
                sheet,
                {
                    "video_id": "ur_fall/fall-08.mp4",
                    "review_status": "reviewed",
                    "usable_for_training": "true",
                    "review_decision": "confirmed_fall_train",
                    "fall_start_ms": "1000",
                    "ground_contact_start_ms": "1400",
                    "low_posture_start_ms": "1400",
                    "motion_end_ms": "1800",
                    "recovery_start_ms": "",
                    "recovered_within_5s": "false",
                    "scene_type": "floor_risk_zone",
                    "support_surface": "none",
                    "occlusion_level": "low",
                    "track_quality_issue": "false",
                    "pose_quality_issue": "true",
                    "fall_subtype": "hard_recall_fall",
                    "reviewer": "professor_a",
                    "review_notes": "Confirmed fall with weak low-posture evidence.",
                },
            )

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=output, dry_run=False)
            updated = json.loads(output.read_text(encoding="utf-8").splitlines()[0])

        self.assertTrue(result["written"])
        self.assertEqual(result["validation"]["error_count"], 0)
        self.assertEqual(updated["review_status"], "reviewed")
        self.assertTrue(updated["usable_for_training"])
        self.assertEqual(updated["fall_start_ms"], 1000)
        self.assertFalse(updated["recovered_within_5s"])
        self.assertEqual(updated["reviewer"], "professor_a")

    def test_reads_utf8_bom_sheet_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            output = root / "updated.jsonl"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(
                sheet,
                {
                    "video_id": "ur_fall/fall-08.mp4",
                    "review_status": "reviewed",
                    "usable_for_training": "false",
                    "review_decision": "exclude_uncertain",
                    "reviewer": "professor_a",
                    "review_notes": "unclear_video",
                },
                encoding="utf-8-sig",
            )

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=output, dry_run=False)
            updated = json.loads(output.read_text(encoding="utf-8").splitlines()[0])

        self.assertTrue(result["written"])
        self.assertEqual(updated["review_status"], "reviewed")
        self.assertEqual(updated["review_decision"], "exclude_uncertain")

    def test_dry_run_does_not_write_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            output = root / "updated.jsonl"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(sheet, {"video_id": "ur_fall/fall-08.mp4", "review_status": "needs_temporal_review", "usable_for_training": "false"})

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=output, dry_run=True)

        self.assertFalse(result["written"])
        self.assertFalse(output.exists())

    def test_blank_sheet_fields_do_not_overwrite_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            output = root / "updated.jsonl"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(
                sheet,
                {
                    "video_id": "ur_fall/fall-08.mp4",
                    "review_status": "needs_temporal_review",
                    "usable_for_training": "false",
                    "review_decision": "",
                    "reviewer": "",
                },
            )

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=output, dry_run=True)

        self.assertEqual(result["changed_count"], 0)

    def test_no_change_same_output_path_does_not_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(sheet, {"video_id": "ur_fall/fall-08.mp4", "review_status": "needs_temporal_review", "usable_for_training": "false"})

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=seed, dry_run=False)

        self.assertFalse(result["written"])

    def test_invalid_training_row_is_not_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = root / "seed.jsonl"
            sheet = root / "sheet.csv"
            output = root / "updated.jsonl"
            seed.write_text(json.dumps(seed_row()) + "\n", encoding="utf-8")
            write_sheet(
                sheet,
                {
                    "video_id": "ur_fall/fall-08.mp4",
                    "review_status": "reviewed",
                    "usable_for_training": "true",
                    "review_decision": "confirmed_fall_train",
                },
            )

            result = apply_review_sheet(sheet_path=sheet, input_path=seed, output_path=output, dry_run=False)

        self.assertFalse(result["written"])
        self.assertGreater(result["validation"]["error_count"], 0)
        self.assertFalse(output.exists())


def seed_row() -> dict:
    return {
        "video_id": "ur_fall/fall-08.mp4",
        "source_dataset": "ur_fall",
        "binary_label": "fall",
        "expected_alarm": True,
        "review_status": "needs_temporal_review",
        "usable_for_training": False,
        "residual_category": "insufficient_multi_evidence_for_rules",
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


def write_sheet(path: Path, row: dict[str, str], *, encoding: str = "utf-8") -> None:
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
    with path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    unittest.main()
