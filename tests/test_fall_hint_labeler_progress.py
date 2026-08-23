from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.fall_hint_labeler import server as labeler


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FallHintLabelerProgressTest(unittest.TestCase):
    def test_build_progress_counts_reviewed_and_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch_test"
            frames_dir = batch_dir / "frames"
            draft_dir = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
            review_labels_dir = batch_dir / "human_review" / "labels"
            review_meta_dir = batch_dir / "human_review" / "meta"
            meta_dir = batch_dir / "meta"

            write_text(frames_dir / "frame_001.jpg", "fake")
            write_text(frames_dir / "frame_002.jpg", "fake")
            write_text(frames_dir / "frame_003.jpg", "fake")
            write_text(draft_dir / "frame_001.txt", "0 0.5 0.5 0.2 0.2\n")
            write_text(draft_dir / "frame_002.txt", "")
            write_text(meta_dir / "frame_manifest.csv", "image,video_id,scene,group\n")
            write_text(
                review_labels_dir / "frame_001.txt",
                "0 0.500000 0.500000 0.200000 0.200000\n",
            )
            write_text(
                review_meta_dir / "frame_001.json",
                json.dumps({"image": "frame_001.jpg", "status": "reviewed", "label_count": 1}, ensure_ascii=False),
            )

            labeler.BATCH_ROOT = batch_dir
            labeler.FRAMES_DIR = frames_dir
            labeler.DRAFT_LABELS_DIR = draft_dir
            labeler.REVIEW_LABELS_DIR = review_labels_dir
            labeler.REVIEW_META_DIR = review_meta_dir

            progress = labeler.build_progress()

            self.assertEqual(progress["total"], 3)
            self.assertEqual(progress["reviewed"], 1)
            self.assertEqual(progress["draft"], 2)
            self.assertEqual(progress["remaining"], 2)

    def test_build_progress_treats_invalid_json_status_as_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            batch_dir = Path(tmp) / "batch_test"
            frames_dir = batch_dir / "frames"
            review_labels_dir = batch_dir / "human_review" / "labels"
            review_meta_dir = batch_dir / "human_review" / "meta"

            write_text(frames_dir / "frame_001.jpg", "fake")
            write_text(review_labels_dir / "frame_001.txt", "")
            write_text(review_meta_dir / "frame_001.json", "{broken-json")

            labeler.BATCH_ROOT = batch_dir
            labeler.FRAMES_DIR = frames_dir
            labeler.DRAFT_LABELS_DIR = batch_dir / "prelabels" / "hf_human_fall_yolo11_mapped" / "labels"
            labeler.REVIEW_LABELS_DIR = review_labels_dir
            labeler.REVIEW_META_DIR = review_meta_dir

            progress = labeler.build_progress()

            self.assertEqual(progress["reviewed"], 1)
            self.assertEqual(progress["draft"], 0)
            self.assertEqual(progress["remaining"], 0)


if __name__ == "__main__":
    unittest.main()
