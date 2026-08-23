from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.create_fall_confusion_matrices import (
    Confusion,
    Panel,
    extract_confusion,
    metrics_dict,
    render_svg,
    write_csv,
)


class CreateFallConfusionMatricesTest(unittest.TestCase):
    def test_extracts_event_metrics_confusion(self) -> None:
        payload = {
            "event_metrics": {
                "confusion": {
                    "true_negative": 78,
                    "false_positive": 22,
                    "false_negative": 18,
                    "true_positive": 82,
                }
            }
        }

        confusion = extract_confusion(payload)

        self.assertEqual(confusion.true_negative, 78)
        self.assertEqual(confusion.false_positive, 22)
        self.assertEqual(confusion.false_negative, 18)
        self.assertEqual(confusion.true_positive, 82)
        self.assertEqual(metrics_dict(confusion)["accuracy"], 0.8)

    def test_computes_confusion_from_offline_video_summary(self) -> None:
        payload = {
            "videos": [
                {"expected_alarm": True, "alarm_confirmed_frames": 3, "confirmed_frames": 0},
                {"expected_alarm": True, "alarm_confirmed_frames": 0, "confirmed_frames": 0},
                {"expected_alarm": False, "alarm_confirmed_frames": 1, "confirmed_frames": 0},
                {"expected_alarm": False, "alarm_confirmed_frames": 0, "confirmed_frames": 0},
            ]
        }

        confusion = extract_confusion(payload)

        self.assertEqual(
            confusion.as_dict(),
            {
                "true_negative": 1,
                "false_positive": 1,
                "false_negative": 1,
                "true_positive": 1,
            },
        )

    def test_writes_csv_and_svg(self) -> None:
        panel = Panel(
            title="YOLO + Pose + LSTM",
            confusion=Confusion(true_negative=93, false_positive=7, false_negative=6, true_positive=94),
            source="metrics.json",
            note="event-level",
        )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "matrix.csv"
            write_csv(csv_path, [panel])
            svg = render_svg([panel])

            csv_payload = csv_path.read_text(encoding="utf-8")

        self.assertIn("YOLO + Pose + LSTM", csv_payload)
        self.assertIn("true_negative", csv_payload)
        self.assertIn("<svg", svg)
        self.assertIn("93", svg)
        self.assertIn("F1-score", svg)


if __name__ == "__main__":
    unittest.main()
