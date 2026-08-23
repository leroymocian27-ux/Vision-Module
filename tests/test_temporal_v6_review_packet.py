from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_temporal_v6_review_packet import build_packet


class TemporalV6ReviewPacketTest(unittest.TestCase):
    def test_builds_review_sheet_and_frame_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.jsonl"
            audit = root / "audit.json"
            frames_dir = root / "frames"
            output = root / "packet"
            frames_dir.mkdir()
            review.write_text(
                json.dumps(
                    {
                        "video_id": "ur_fall/fall-08.mp4",
                        "video_path": "../../datasets/ur_fall/videos/fall-08.mp4",
                        "review_status": "needs_temporal_review",
                        "usable_for_training": False,
                        "residual_category": "insufficient_multi_evidence_for_rules",
                        "suggested_review_decision": "confirmed_fall_train",
                        "fall_subtype": "hard_recall_fall",
                        "best_timestamp_ms": 1000,
                        "best_frame_index": 25,
                        "missing_evidence": ["low_posture_weak"],
                        "recommended_review_action": "Review this hard case.",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            audit.write_text(json.dumps({"items": []}), encoding="utf-8")
            (frames_dir / "offline_eval_fall-08_frames.jsonl").write_text(
                "".join(
                    json.dumps(frame_row(timestamp_ms=timestamp_ms, frame_index=index)) + "\n"
                    for index, timestamp_ms in enumerate([0, 400, 1000, 1800, 3000])
                ),
                encoding="utf-8",
            )

            summary = build_packet(
                review_path=review,
                audit_path=audit,
                frames_dir=frames_dir,
                output_dir=output,
                window_ms=800,
            )

            sheet_rows = list(csv.DictReader((output / "residual_fn_review_sheet.csv").open(encoding="utf-8")))
            window_rows = list(csv.DictReader((output / "frame_windows" / "ur_fall_fall-08_mp4_window.csv").open(encoding="utf-8")))

        self.assertEqual(summary["review_rows"], 1)
        self.assertEqual(sheet_rows[0]["video_id"], "ur_fall/fall-08.mp4")
        self.assertEqual(sheet_rows[0]["frame_window_csv"], "frame_windows/ur_fall_fall-08_mp4_window.csv")
        self.assertEqual([row["timestamp_ms"] for row in window_rows], ["400", "1000", "1800"])

    def test_missing_frame_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            review = root / "review.jsonl"
            audit = root / "audit.json"
            review.write_text(json.dumps({"video_id": "ur_fall/fall-99.mp4"}) + "\n", encoding="utf-8")
            audit.write_text(json.dumps({"items": []}), encoding="utf-8")

            summary = build_packet(
                review_path=review,
                audit_path=audit,
                frames_dir=root / "missing_frames",
                output_dir=root / "packet",
                window_ms=800,
            )

        self.assertEqual(len(summary["missing_frame_files"]), 1)


def frame_row(*, timestamp_ms: int, frame_index: int) -> dict:
    return {
        "video_name": "fall-08.mp4",
        "frame_index": frame_index,
        "timestamp_ms": timestamp_ms,
        "fall_state": "normal",
        "alarm_confirmed": False,
        "fall_prob": 0.1,
        "fall_hint_label": "falling",
        "fall_hint_confidence": 0.5,
        "lstm_probability": 0.1,
        "v6_motion_path": "motion_observe",
        "v6_fall_evidence_score": 0.3,
        "v6_adl_suppression_score": 0.2,
        "v6_decision_reason": "[]",
    }


if __name__ == "__main__":
    unittest.main()
