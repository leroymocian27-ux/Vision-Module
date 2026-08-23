from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_pose_model_quality import build_pose_model_quality_report


class CheckPoseModelQualityTest(unittest.TestCase):
    def test_passes_when_candidate_beats_baseline_and_matches_configured_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "models" / "pose_candidate.pt"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            metrics = write_json(
                root / "metrics.json",
                metric_payload(
                    candidate_model=str(model),
                    baseline_map=0.88,
                    candidate_map=0.89,
                    baseline_recall=0.95,
                    candidate_recall=0.95,
                ),
            )

            report = build_pose_model_quality_report(
                metrics_path=metrics,
                configured_model=str(model),
            )

        self.assertTrue(report["summary"]["passed"])
        self.assertEqual(report["summary"]["blockers"], [])
        self.assertAlmostEqual(report["summary"]["delta_pose_map50_95"], 0.01)

    def test_blocks_when_candidate_pose_map_is_below_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "models" / "pose_candidate.pt"
            model.parent.mkdir(parents=True)
            model.write_bytes(b"model")
            metrics = write_json(
                root / "metrics.json",
                metric_payload(
                    candidate_model=str(model),
                    baseline_map=0.883491,
                    candidate_map=0.848643,
                    baseline_recall=1.0,
                    candidate_recall=1.0,
                ),
            )

            report = build_pose_model_quality_report(
                metrics_path=metrics,
                configured_model=str(model),
            )

        self.assertFalse(report["summary"]["passed"])
        self.assertIn("candidate_pose_map50_95_below_baseline", report["summary"]["blockers"])

    def test_allows_configured_baseline_model_even_when_candidate_is_worse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "yolo11n-pose.pt"
            baseline.write_bytes(b"baseline")
            candidate = root / "models" / "worse_candidate.pt"
            candidate.parent.mkdir(parents=True)
            candidate.write_bytes(b"candidate")
            metrics = write_json(
                root / "metrics.json",
                metric_payload(
                    baseline_model=str(baseline),
                    candidate_model=str(candidate),
                    baseline_map=0.883491,
                    candidate_map=0.848643,
                    baseline_recall=1.0,
                    candidate_recall=1.0,
                ),
            )

            report = build_pose_model_quality_report(
                metrics_path=metrics,
                configured_model=str(baseline),
            )

        self.assertTrue(report["summary"]["passed"])
        self.assertTrue(report["summary"]["uses_baseline_model"])
        self.assertEqual(report["summary"]["blockers"], [])

    def test_blocks_when_configured_model_does_not_match_metrics_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = root / "models" / "configured.pt"
            candidate = root / "models" / "candidate.pt"
            configured.parent.mkdir(parents=True)
            configured.write_bytes(b"configured")
            candidate.write_bytes(b"candidate")
            metrics = write_json(
                root / "metrics.json",
                metric_payload(
                    candidate_model=str(candidate),
                    baseline_map=0.88,
                    candidate_map=0.89,
                    baseline_recall=0.95,
                    candidate_recall=0.95,
                ),
            )

            report = build_pose_model_quality_report(
                metrics_path=metrics,
                configured_model=str(configured),
            )

        self.assertFalse(report["summary"]["passed"])
        self.assertIn("configured_pose_model_does_not_match_metrics_candidate", report["summary"]["blockers"])


def metric_payload(
    *,
    candidate_model: str,
    baseline_model: str = "yolo11n-pose.pt",
    baseline_map: float,
    candidate_map: float,
    baseline_recall: float,
    candidate_recall: float,
) -> dict:
    return {
        "baseline_model": baseline_model,
        "candidate_model": candidate_model,
        "device": "0",
        "baseline": {
            "pose_map50_95": baseline_map,
            "pose_recall": baseline_recall,
        },
        "candidate": {
            "pose_map50_95": candidate_map,
            "pose_recall": candidate_recall,
        },
        "delta": {
            "pose_map50_95": round(candidate_map - baseline_map, 6),
            "pose_recall": round(candidate_recall - baseline_recall, 6),
        },
    }


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
