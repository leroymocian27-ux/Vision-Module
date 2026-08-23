from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_pose_temporal_sequences import check_pose_temporal_sequences


class CheckPoseTemporalSequencesTest(unittest.TestCase):
    def test_passes_pose_aware_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(
                root / "seq.jsonl",
                [
                    row(pose_available=True, quality="high_confidence", confidence=0.9),
                    row(pose_available=False, quality="low_quality", confidence=0.0, rejected_reason="no_visible_keypoints"),
                ],
            )

            result = check_pose_temporal_sequences(
                input_dir=root,
                min_pose_available_ratio=0.5,
                min_known_quality_ratio=1.0,
                expected_input_dim=15,
            )

        self.assertTrue(result["passed"])
        self.assertEqual(result["summary"]["pose_quality_counts"]["high_confidence"], 1)
        self.assertEqual(result["summary"]["pose_rejected_reason_counts"]["no_visible_keypoints"], 1)
        self.assertEqual(result["summary"]["pose_provider_counts"]["yolo11_legacy"], 2)
        self.assertEqual(result["summary"]["pose_model_path_counts"]["yolo11n-pose.pt"], 2)

    def test_fails_when_quality_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root / "seq.jsonl", [row(pose_available=True, quality=None, confidence=0.9)])

            result = check_pose_temporal_sequences(
                input_dir=root,
                min_pose_available_ratio=0.1,
                min_known_quality_ratio=0.95,
                expected_input_dim=15,
            )

        self.assertFalse(result["passed"])
        self.assertEqual(result["summary"]["pose_quality_counts"]["unknown"], 1)

    def test_fails_when_mismatch_is_marked_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_rows(root / "seq.jsonl", [row(pose_available=True, quality="pose_track_mismatch", confidence=0.9)])

            result = check_pose_temporal_sequences(
                input_dir=root,
                min_pose_available_ratio=0.1,
                min_known_quality_ratio=0.95,
                expected_input_dim=15,
            )

        self.assertFalse(result["passed"])
        self.assertEqual(result["summary"]["mismatch_available_rows"], 1)

    def test_fails_when_available_pose_lacks_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = row(pose_available=True, quality="valid", confidence=0.9)
            bad.pop("pose_runtime")
            write_rows(root / "seq.jsonl", [bad])

            result = check_pose_temporal_sequences(
                input_dir=root,
                min_pose_available_ratio=0.1,
                min_known_quality_ratio=0.95,
                expected_input_dim=15,
            )

        self.assertFalse(result["passed"])
        self.assertEqual(result["summary"]["pose_available_missing_provider_rows"], 1)
        self.assertEqual(result["summary"]["pose_available_missing_model_rows"], 1)


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(item) + "\n" for item in rows), encoding="utf-8")


def row(
    *,
    pose_available: bool,
    quality: str | None,
    confidence: float,
    rejected_reason: str | None = None,
) -> dict:
    target_feature = {
        "pose_available": pose_available,
        "pose_confidence": confidence,
        "pose_rejected_reason": rejected_reason,
    }
    if quality is not None:
        target_feature["pose_quality_level"] = quality
    return {
        "source_dataset": "ur_fall",
        "label": "fall",
        "target_feature": target_feature,
        "pose_runtime": {
            "pose_enabled": True,
            "pose_provider": "yolo11_legacy",
            "pose_model_path": "yolo11n-pose.pt",
            "pose_device": "cuda:0",
        },
        "vector": [0.0] * 15,
    }


if __name__ == "__main__":
    unittest.main()
