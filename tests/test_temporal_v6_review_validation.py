from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.validate_temporal_v6_review_seed import main, validate_rows


class TemporalV6ReviewValidationTest(unittest.TestCase):
    def test_unreviewed_seed_rows_are_allowed(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/fall-08.mp4",
                "review_status": "needs_temporal_review",
                "usable_for_training": False,
                "fall_start_ms": None,
                "ground_contact_start_ms": None,
                "low_posture_start_ms": None,
            }
        ]

        summary = validate_rows(rows)

        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["usable_for_training_count"], 0)

    def test_training_row_requires_review_status_and_trainable_decision(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/fall-08.mp4",
                "review_status": "needs_temporal_review",
                "usable_for_training": True,
                "review_decision": "ambiguous_second_review",
            }
        ]

        summary = validate_rows(rows)

        codes = {error["code"] for error in summary["errors"]}
        self.assertIn("usable_row_not_approved", codes)
        self.assertIn("non_trainable_review_decision", codes)
        self.assertIn("missing_event_time", codes)

    def test_valid_reviewed_training_row_passes(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/fall-21.mp4",
                "review_status": "reviewed",
                "usable_for_training": True,
                "review_decision": "confirmed_fall_train",
                "fall_start_ms": 1200,
                "ground_contact_start_ms": 1800,
                "low_posture_start_ms": 1760,
                "motion_end_ms": 2200,
                "recovery_start_ms": None,
                "recovered_within_5s": False,
                "scene_type": "floor_risk_zone",
                "support_surface": "none",
                "occlusion_level": "low",
                "reviewer": "professor_a",
                "review_notes": "Confirmed slow fall into floor-risk zone.",
            }
        ]

        summary = validate_rows(rows)

        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["usable_for_training_count"], 1)

    def test_timeline_order_is_checked(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/fall-21.mp4",
                "review_status": "reviewed",
                "usable_for_training": True,
                "review_decision": "confirmed_fall_train",
                "fall_start_ms": 1200,
                "ground_contact_start_ms": 800,
                "low_posture_start_ms": 1760,
                "recovered_within_5s": False,
                "scene_type": "floor_risk_zone",
                "support_surface": "none",
                "occlusion_level": "low",
                "reviewer": "professor_a",
                "review_notes": "Invalid timing should be rejected.",
            }
        ]

        summary = validate_rows(rows)

        self.assertIn("timeline_order_error", {error["code"] for error in summary["errors"]})

    def test_cli_returns_nonzero_for_invalid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "review.jsonl"
            input_path.write_text(
                json.dumps(
                    {
                        "video_id": "ur_fall/fall-05.mp4",
                        "review_status": "reviewed",
                        "usable_for_training": True,
                        "review_decision": "exclude_not_fall",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            import sys

            old_argv = sys.argv
            try:
                sys.argv = ["validate_temporal_v6_review_seed.py", "--input", str(input_path)]
                exit_code = main()
            finally:
                sys.argv = old_argv

        self.assertEqual(exit_code, 1)

    def test_hard_negative_reviewed_row_passes(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/adl-01.mp4",
                "review_status": "reviewed",
                "usable_for_training": True,
                "review_decision": "hard_negative_train",
                "fall_start_ms": 400,
                "ground_contact_start_ms": 600,
                "low_posture_start_ms": 600,
                "motion_end_ms": 900,
                "recovery_start_ms": 1200,
                "recovered_within_5s": True,
                "scene_type": "adl_floor_or_mixed_zone",
                "support_surface": "none",
                "occlusion_level": "low",
                "reviewer": "professor_a",
                "review_notes": "voluntary_lying",
                "track_quality_issue": False,
                "pose_quality_issue": False,
            }
        ]

        summary = validate_rows(rows)

        self.assertEqual(summary["error_count"], 0)
        self.assertEqual(summary["usable_for_training_count"], 1)

    def test_detection_issue_trainable_row_requires_quality_confirmation(self) -> None:
        rows = [
            {
                "video_id": "ur_fall/fall-18.mp4",
                "review_status": "reviewed",
                "usable_for_training": True,
                "review_decision": "confirmed_fall_but_detection_issue",
                "fall_start_ms": 400,
                "ground_contact_start_ms": 600,
                "low_posture_start_ms": 600,
                "motion_end_ms": 900,
                "recovery_start_ms": None,
                "recovered_within_5s": False,
                "scene_type": "floor_risk_zone",
                "support_surface": "none",
                "occlusion_level": "medium",
                "reviewer": "professor_a",
                "review_notes": "confirmed fall but evidence quality issue not labeled",
                "track_quality_issue": False,
                "pose_quality_issue": False,
            }
        ]

        summary = validate_rows(rows)

        self.assertIn("missing_quality_issue_confirmation", {error["code"] for error in summary["errors"]})


if __name__ == "__main__":
    unittest.main()
