from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_fall_hint_threshold_sweep import persist_sweep_progress


class FallHintThresholdSweepPersistenceTest(unittest.TestCase):
    def test_persist_sweep_progress_writes_summary_and_details_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_csv = root / "threshold_sweep_summary.csv"
            details_csv = root / "threshold_sweep_details.csv"

            persist_sweep_progress(
                summary_csv=summary_csv,
                details_csv=details_csv,
                summary_rows=[
                    {
                        "model_name": "candidate_d",
                        "threshold": 0.35,
                        "test_precision": 0.91,
                        "empty_holdout_fp_images": 2,
                    }
                ],
                detail_rows=[
                    {
                        "model_name": "candidate_d",
                        "threshold": 0.35,
                        "detail_type": "empty_holdout",
                        "image": "empty_001.jpg",
                        "prediction_box_count": 0,
                    },
                    {
                        "model_name": "candidate_d",
                        "threshold": 0.35,
                        "detail_type": "diagnostic",
                        "image": "adl_001.jpg",
                        "false_fallen_on_adl": False,
                    },
                ],
            )

            summary_rows = list(csv.DictReader(summary_csv.open("r", encoding="utf-8", newline="")))
            detail_rows = list(csv.DictReader(details_csv.open("r", encoding="utf-8", newline="")))

        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["model_name"], "candidate_d")
        self.assertEqual(summary_rows[0]["threshold"], "0.35")
        self.assertEqual(len(detail_rows), 2)
        self.assertEqual({row["detail_type"] for row in detail_rows}, {"empty_holdout", "diagnostic"})


if __name__ == "__main__":
    unittest.main()
