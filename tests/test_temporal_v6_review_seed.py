from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_temporal_v6_review_seed import build_review_rows, main


class TemporalV6ReviewSeedTest(unittest.TestCase):
    def test_builds_review_rows_with_event_fields_and_suggestions(self) -> None:
        audit = {
            "items": [
                {
                    "video": "fall-18.mp4",
                    "video_id": "ur_fall/fall-18.mp4",
                    "path": "../../datasets/ur_fall/videos/fall-18.mp4",
                    "scene_type": "floor_risk_zone",
                    "support_surface": "none",
                    "residual_category": "detector_or_tracking_evidence_missing",
                    "recommended_review_action": "Review detector.",
                    "best_timestamp_ms": 0,
                    "best_frame_index": 0,
                    "best_motion_path": "normal",
                    "max_scores": {"v6_fall_evidence_score": 0.12},
                    "missing_evidence": ["low_posture_weak"],
                }
            ]
        }

        rows = build_review_rows(audit)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["video_id"], "ur_fall/fall-18.mp4")
        self.assertEqual(row["review_status"], "needs_temporal_review")
        self.assertFalse(row["usable_for_training"])
        self.assertEqual(row["suggested_review_decision"], "confirmed_fall_but_detection_issue")
        self.assertEqual(row["fall_subtype"], "fall_with_tracking_loss")
        self.assertIn("fall_start_ms", row)
        self.assertTrue(row["track_quality_issue"])

    def test_cli_writes_jsonl_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_path = root / "audit.json"
            output_path = root / "seed.jsonl"
            summary_path = root / "summary.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "video": "fall-20.mp4",
                                "video_id": "ur_fall/fall-20.mp4",
                                "path": "../../datasets/ur_fall/videos/fall-20.mp4",
                                "residual_category": "slow_or_normal_lying_ambiguous",
                                "max_scores": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            import sys

            old_argv = sys.argv
            try:
                sys.argv = [
                    "build_temporal_v6_review_seed.py",
                    "--audit",
                    str(audit_path),
                    "--output",
                    str(output_path),
                    "--summary",
                    str(summary_path),
                ]
                exit_code = main()
            finally:
                sys.argv = old_argv

            row = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(row["suggested_review_decision"], "ambiguous_second_review")
        self.assertEqual(summary["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
