from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_temporal_v6_review_progress import summarize_review_progress


class TemporalV6ReviewProgressSummaryTest(unittest.TestCase):
    def test_pending_sheet_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "sheet.csv"
            write_sheet(
                sheet,
                [
                    {
                        "video_id": "ur_fall/fall-08.mp4",
                        "review_status": "needs_temporal_review",
                        "usable_for_training": "false",
                        "review_decision": "",
                    }
                ],
            )

            summary = summarize_review_progress(sheet)

        self.assertEqual(summary["pending_rows"], 1)
        self.assertFalse(summary["ready_for_apply"])

    def test_reviewed_trainable_row_can_be_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "sheet.csv"
            write_sheet(
                sheet,
                [
                    {
                        "video_id": "ur_fall/fall-21.mp4",
                        "review_status": "reviewed",
                        "usable_for_training": "true",
                        "review_decision": "confirmed_fall_train",
                        "fall_start_ms": "1200",
                        "ground_contact_start_ms": "1800",
                        "low_posture_start_ms": "1800",
                        "motion_end_ms": "2200",
                        "recovery_start_ms": "",
                        "recovered_within_5s": "false",
                        "scene_type": "floor_risk_zone",
                        "support_surface": "none",
                        "occlusion_level": "low",
                        "track_quality_issue": "false",
                        "pose_quality_issue": "false",
                        "reviewer": "professor_a",
                        "review_notes": "Confirmed fall.",
                    }
                ],
            )

            summary = summarize_review_progress(sheet)

        self.assertTrue(summary["ready_for_apply"])
        self.assertEqual(summary["trainable_ready_rows"], 1)
        self.assertEqual(summary["validation_error_count"], 0)

    def test_detection_issue_without_quality_flag_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sheet = Path(tmp) / "sheet.csv"
            write_sheet(
                sheet,
                [
                    {
                        "video_id": "ur_fall/fall-18.mp4",
                        "review_status": "reviewed",
                        "usable_for_training": "true",
                        "review_decision": "confirmed_fall_but_detection_issue",
                        "fall_start_ms": "400",
                        "ground_contact_start_ms": "600",
                        "low_posture_start_ms": "600",
                        "motion_end_ms": "900",
                        "recovery_start_ms": "",
                        "recovered_within_5s": "false",
                        "scene_type": "floor_risk_zone",
                        "support_surface": "none",
                        "occlusion_level": "medium",
                        "track_quality_issue": "false",
                        "pose_quality_issue": "false",
                        "reviewer": "professor_a",
                        "review_notes": "fall with quality issue",
                    }
                ],
            )

            summary = summarize_review_progress(sheet)

        self.assertFalse(summary["ready_for_apply"])
        self.assertIn("missing_quality_issue_confirmation", summary["rows"][0]["error_codes"])


def write_sheet(path: Path, rows: list[dict[str, str]]) -> None:
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
        "reviewer",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
