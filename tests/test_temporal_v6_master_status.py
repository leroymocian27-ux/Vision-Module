from __future__ import annotations

import unittest

from scripts.summarize_temporal_v6_status import summarize_status


class TemporalV6MasterStatusTest(unittest.TestCase):
    def test_detects_post_review_blocker_after_review_packet_ready(self) -> None:
        result = summarize_status_from_payloads(
            review_packet={"review_rows": 9, "missing_frame_files": [], "sheet": "sheet.csv"},
            post_review={
                "ready_for_training": False,
                "reason": "no_reviewed_residual_training_rows",
                "review_validation": {"usable_for_training_count": 0, "error_count": 0},
                "reviewed_training_dataset": {"trainable_review_rows": 0, "written_sequences": 0},
            },
            candidate={"status": "dry_run", "acceptance_gate": None},
            acceptance={"passed": False, "summary": {"slow_fall_recall": 0.7}},
            promotion={"ready": False, "checks": [{"name": "model_exists", "passed": False}]},
        )

        self.assertEqual(result["overall_status"], "in_progress")
        self.assertEqual(result["blocking_stage"], "post_review_training_data")
        self.assertEqual(result["stages"]["review_packet"]["status"], "ready")

    def test_complete_when_all_stages_pass(self) -> None:
        result = summarize_status_from_payloads(
            review_packet={"review_rows": 9, "missing_frame_files": [], "sheet": "sheet.csv"},
            post_review={
                "ready_for_training": True,
                "review_validation": {"usable_for_training_count": 4, "error_count": 0},
                "reviewed_training_dataset": {"trainable_review_rows": 4, "written_sequences": 4},
            },
            candidate={"status": "ok", "acceptance_gate": {"passed": True}},
            acceptance={"passed": True, "summary": {"slow_fall_recall": 0.84}},
            promotion={"ready": True, "checks": [], "promotion_env": {"TEMPORAL_MODEL_PROVIDER": "shadow"}},
        )

        self.assertEqual(result["overall_status"], "complete")
        self.assertIsNone(result["blocking_stage"])


def summarize_status_from_payloads(**payloads):
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths = {}
        for name, payload in payloads.items():
            path = root / f"{name}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[name] = path
        return summarize_status(
            review_packet_path=paths["review_packet"],
            post_review_path=paths["post_review"],
            candidate_path=paths["candidate"],
            acceptance_path=paths["acceptance"],
            promotion_path=paths["promotion"],
        )


if __name__ == "__main__":
    unittest.main()
