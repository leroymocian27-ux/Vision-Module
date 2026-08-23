from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_temporal_v6_manifests import load_labels, write_manifest


class TemporalV6ManifestBuilderTest(unittest.TestCase):
    def test_builds_reviewed_manifest_items_with_adl_subtypes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            labels_path = tmp_path / "labels.jsonl"
            labels_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "video_id": "ur_fall/adl-06.mp4",
                                "source_dataset": "ur_fall",
                                "binary_label": "non_fall",
                                "non_fall_subtype": "bending",
                                "usable_for_training": True,
                                "split_group": "adl_06",
                                "notes": "reviewed: bend forward and recover",
                            }
                        ),
                        json.dumps(
                            {
                                "video_id": "ur_fall/fall-01.mp4",
                                "source_dataset": "ur_fall",
                                "binary_label": "fall",
                                "non_fall_subtype": None,
                                "usable_for_training": True,
                                "split_group": "fall_01",
                                "notes": "",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            rows = load_labels(labels_path, source_dataset="ur_fall")
            result = write_manifest(tmp_path / "manifest.json", rows, purpose="test")
            payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result["video_count"], 2)
        self.assertEqual(payload["videos"][0]["hard_negative_type"], "bending")
        self.assertFalse(payload["videos"][0]["expected_alarm"])
        self.assertTrue(payload["videos"][1]["expected_alarm"])


if __name__ == "__main__":
    unittest.main()
