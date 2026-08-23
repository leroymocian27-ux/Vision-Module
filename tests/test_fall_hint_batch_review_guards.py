from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import extend_fall_hint_seed_finetune_with_review_batch as merge_mod
from scripts import validate_fall_hint_review_batch as validate_mod


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FallHintBatchReviewGuardsTest(unittest.TestCase):
    def test_validate_batch_reports_draft_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "datasets" / "fall_hint_v2_raw"
            batch_dir = raw_root / "batch_test"
            self._create_batch_with_frame(batch_dir, image_name="frame_001.jpg")

            stdout = io.StringIO()
            with patch.object(validate_mod, "RAW_ROOT", raw_root), patch(
                "sys.argv",
                [
                    "validate_fall_hint_review_batch.py",
                    "--batch-id",
                    "batch_test",
                    "--write-report",
                ],
            ), redirect_stdout(stdout):
                rc = validate_mod.main()

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["frame_count"], 1)
            self.assertEqual(payload["status_counts"], {"draft": 1})
            self.assertFalse(payload["ready_for_merge"])
            self.assertTrue((batch_dir / "meta" / "review_validation_summary.json").exists())

    def test_extend_merge_refuses_when_batch_not_fully_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "datasets" / "fall_hint_v2_raw"
            batch_dir = raw_root / "batch_test"
            self._create_batch_with_frame(batch_dir, image_name="frame_001.jpg")

            base_dataset = root / "datasets" / "base_dataset"
            self._create_base_dataset(base_dataset)
            output_dataset = root / "datasets" / "merged_dataset"

            with patch.object(merge_mod, "RAW_ROOT", raw_root), patch(
                "sys.argv",
                [
                    "extend_fall_hint_seed_finetune_with_review_batch.py",
                    "--batch-id",
                    "batch_test",
                    "--base",
                    str(base_dataset),
                    "--output",
                    str(output_dataset),
                ],
            ):
                with self.assertRaises(SystemExit) as ctx:
                    merge_mod.main()

            self.assertIn("not fully ready_for_merge", str(ctx.exception))

    def test_extend_merge_adds_reviewed_batch_to_train_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_root = root / "datasets" / "fall_hint_v2_raw"
            batch_dir = raw_root / "batch_test"
            self._create_batch_with_frame(
                batch_dir,
                image_name="frame_001.jpg",
                reviewed=True,
                label_text="2 0.500000 0.500000 0.200000 0.200000\n",
                source_video="demo_source.mp4",
                video_id="demo_video_001",
            )

            base_dataset = root / "datasets" / "base_dataset"
            self._create_base_dataset(base_dataset)
            output_dataset = root / "datasets" / "merged_dataset"

            stdout = io.StringIO()
            with patch.object(merge_mod, "RAW_ROOT", raw_root), patch(
                "sys.argv",
                [
                    "extend_fall_hint_seed_finetune_with_review_batch.py",
                    "--batch-id",
                    "batch_test",
                    "--base",
                    str(base_dataset),
                    "--output",
                    str(output_dataset),
                ],
            ), redirect_stdout(stdout):
                rc = merge_mod.main()

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["added_train_images"], 1)
            self.assertTrue(payload["val_test_preserved_from_base"])

            manifest_rows = list(
                csv.DictReader((output_dataset / "meta" / "manifest.csv").open("r", encoding="utf-8-sig", newline=""))
            )
            self.assertEqual(len(manifest_rows), 2)
            added_row = next(row for row in manifest_rows if row["source_batch_id"] == "batch_test")
            self.assertEqual(added_row["split"], "train")
            self.assertEqual(added_row["source_role"], "hardcase_review_train")

            val_images = list((output_dataset / "images" / "val").glob("*"))
            self.assertEqual(len(val_images), 1)
            train_images = list((output_dataset / "images" / "train").glob("*"))
            self.assertEqual(len(train_images), 1)

    @staticmethod
    def _create_batch_with_frame(
        batch_dir: Path,
        *,
        image_name: str,
        reviewed: bool = False,
        label_text: str = "",
        source_video: str = "",
        video_id: str = "",
    ) -> None:
        frames_dir = batch_dir / "frames"
        labels_dir = batch_dir / "human_review" / "labels"
        meta_dir = batch_dir / "human_review" / "meta"
        batch_meta_dir = batch_dir / "meta"

        write_text(frames_dir / image_name, "fake-image")
        write_text(labels_dir / f"{Path(image_name).stem}.txt", label_text)
        write_csv(
            batch_meta_dir / "frame_manifest.csv",
            [
                {
                    "image": image_name,
                    "video_id": video_id or Path(image_name).stem,
                    "scene": "manual_boundary_lying",
                    "group": "targeted_review",
                    "source_video": source_video,
                    "frame_index": "",
                }
            ],
        )
        if reviewed:
            write_text(
                meta_dir / f"{Path(image_name).stem}.json",
                json.dumps({"image": image_name, "status": "reviewed", "label_count": 1}, ensure_ascii=False),
            )

    @staticmethod
    def _create_base_dataset(base_dataset: Path) -> None:
        for split in ["train", "val", "test"]:
            (base_dataset / "images" / split).mkdir(parents=True, exist_ok=True)
            (base_dataset / "labels" / split).mkdir(parents=True, exist_ok=True)
        (base_dataset / "meta").mkdir(parents=True, exist_ok=True)

        write_text(base_dataset / "data.yaml", "path: dummy\ntrain: images/train\nval: images/val\ntest: images/test\n")
        write_text(base_dataset / "meta" / "empty_holdout_manifest.csv", "image,label\n")
        write_text(base_dataset / "images" / "val" / "existing_val.jpg", "fake-image")
        write_text(base_dataset / "labels" / "val" / "existing_val.txt", "1 0.5 0.5 0.2 0.2\n")
        write_csv(
            base_dataset / "meta" / "manifest.csv",
            [
                {
                    "split": "val",
                    "image": "images/val/existing_val.jpg",
                    "label": "labels/val/existing_val.txt",
                    "source_archive_image": "images/fhv2_reviewed_999999.jpg",
                    "source_archive_label": "labels/fhv2_reviewed_999999.txt",
                    "source_batch_id": "batch_999",
                    "source_original_image": "existing_val.jpg",
                    "source_video": "existing_source.mp4",
                    "video_id": "existing_video_id",
                    "classes": "1",
                    "class_names": "fallen",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
