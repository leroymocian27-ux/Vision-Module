from __future__ import annotations

import unittest
from pathlib import Path

from scripts.check_temporal_v6_acceptance import check_acceptance


class TemporalV6AcceptanceGateTest(unittest.TestCase):
    def test_acceptance_fails_when_slow_recall_below_gate(self) -> None:
        with FakeJsonFiles(
            slow=comparison(recall=0.70, tp=21, fn=9),
            fp=comparison(fp=0, tn=33),
            ur=comparison(recall=0.75, tp=3, fn=1, fp=0, tn=8),
        ) as files:
            result = check_acceptance(
                slow_fall_path=files.slow,
                fp_path=files.fp,
                ur_mini_path=files.ur,
                min_slow_fall_recall=0.80,
                max_fp=0,
                max_duplicates=0,
                max_ur_mini_fp=0,
            )

        self.assertFalse(result["passed"])
        slow_check = next(item for item in result["checks"] if item["name"] == "slow_fall_review_recall")
        self.assertFalse(slow_check["passed"])
        self.assertEqual(slow_check["actual"], 0.70)

    def test_acceptance_passes_when_all_gates_pass(self) -> None:
        with FakeJsonFiles(
            slow=comparison(recall=0.84, tp=25, fn=5),
            fp=comparison(fp=0, tn=33),
            ur=comparison(recall=0.75, tp=3, fn=1, fp=0, tn=8),
        ) as files:
            result = check_acceptance(
                slow_fall_path=files.slow,
                fp_path=files.fp,
                ur_mini_path=files.ur,
                min_slow_fall_recall=0.80,
                max_fp=0,
                max_duplicates=0,
                max_ur_mini_fp=0,
            )

        self.assertTrue(result["passed"])

    def test_duplicate_alarm_fails_gate(self) -> None:
        with FakeJsonFiles(
            slow=comparison(recall=0.84, tp=25, fn=5, duplicates=[{"video": "fall-01.mp4"}]),
            fp=comparison(fp=0, tn=33),
            ur=comparison(recall=0.75, tp=3, fn=1, fp=0, tn=8),
        ) as files:
            result = check_acceptance(
                slow_fall_path=files.slow,
                fp_path=files.fp,
                ur_mini_path=files.ur,
                min_slow_fall_recall=0.80,
                max_fp=0,
                max_duplicates=0,
                max_ur_mini_fp=0,
            )

        self.assertFalse(result["passed"])
        duplicate_check = next(item for item in result["checks"] if item["name"] == "slow_fall_review_duplicate_alarm_videos")
        self.assertFalse(duplicate_check["passed"])


def comparison(
    *,
    recall: float | None = None,
    tp: int = 0,
    fn: int = 0,
    fp: int = 0,
    tn: int = 0,
    duplicates: list[dict] | None = None,
) -> dict:
    return {
        "v6_event_metrics": {
            "fall_event_recall": recall,
            "confusion": {
                "true_positive": tp,
                "false_negative": fn,
                "false_positive": fp,
                "true_negative": tn,
            },
        },
        "duplicate_alarm_videos": duplicates or [],
    }


class FakeJsonFiles:
    def __init__(self, *, slow: dict, fp: dict, ur: dict) -> None:
        self.payloads = {"slow.json": slow, "fp.json": fp, "ur.json": ur}

    def __enter__(self):
        import json
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, payload in self.payloads.items():
            (self.root / name).write_text(json.dumps(payload), encoding="utf-8")
        self.slow = self.root / "slow.json"
        self.fp = self.root / "fp.json"
        self.ur = self.root / "ur.json"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
