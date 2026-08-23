from __future__ import annotations

import unittest
from pathlib import Path

from scripts.export_dataset_temporal_sequences import build_export_command, export_command_for_video, select_videos


class ExportDatasetTemporalSequencesTest(unittest.TestCase):
    def test_build_export_command_passes_enable_pose(self) -> None:
        cmd = build_export_command(
            video_path=Path("video.mp4"),
            output_path=Path("out.jsonl"),
            camera_id="camera_01",
            video_id="ur_fall/video.mp4",
            label="fall",
            frame_stride=2,
            enable_pose=True,
            device=None,
        )

        self.assertIn("--enable-pose", cmd)

    def test_build_export_command_omits_enable_pose_by_default(self) -> None:
        cmd = build_export_command(
            video_path=Path("video.mp4"),
            output_path=Path("out.jsonl"),
            camera_id="camera_01",
            video_id="ur_fall/video.mp4",
            label="fall",
            frame_stride=2,
            enable_pose=False,
            device=None,
        )

        self.assertNotIn("--enable-pose", cmd)

    def test_build_export_command_passes_device_override(self) -> None:
        cmd = build_export_command(
            video_path=Path("video.mp4"),
            output_path=Path("out.jsonl"),
            camera_id="camera_01",
            video_id="ur_fall/video.mp4",
            label="fall",
            frame_stride=2,
            enable_pose=True,
            device="cpu",
        )

        self.assertIn("--device", cmd)
        self.assertIn("cpu", cmd)

    def test_select_videos_filters_label_split_and_requested_ids(self) -> None:
        videos = select_videos(
            entry={},
            label_rows={
                "ur_fall/adl-01.mp4": {
                    "binary_label": "non_fall",
                    "split": "train",
                    "usable_for_training": True,
                },
                "ur_fall/fall-01.mp4": {
                    "binary_label": "fall",
                    "split": "train",
                    "usable_for_training": True,
                },
                "ur_fall/fall-02.mp4": {
                    "binary_label": "fall",
                    "split": "val",
                    "usable_for_training": True,
                },
            },
            dataset="ur_fall",
            split="train",
            label_filter="fall",
            video_ids=["fall-01.mp4", "fall-02.mp4"],
        )

        self.assertEqual(videos, ["fall-01.mp4"])

    def test_select_videos_filters_manifest_without_label_rows(self) -> None:
        videos = select_videos(
            entry={
                "videos": ["adl-01.mp4", "fall-01.mp4", "fall-02.mp4"],
                "labels": {"adl-01.mp4": "adl", "fall-01.mp4": "fall", "fall-02.mp4": "fall"},
            },
            label_rows={},
            dataset="ur_fall",
            split=None,
            label_filter="fall",
            video_ids=["ur_fall/fall-02.mp4"],
        )

        self.assertEqual(videos, ["fall-02.mp4"])

    def test_export_command_can_override_label_split_while_keeping_subtype(self) -> None:
        cmd = export_command_for_video(
            dataset="ur_fall",
            video_name="adl-01.mp4",
            entry={"labels": {"adl-01.mp4": "adl"}},
            label_row={
                "binary_label": "non_fall",
                "non_fall_subtype": "squatting",
                "split": "val",
                "usable_for_training": True,
            },
            output_dir=Path("out"),
            frame_stride=4,
            enable_pose=True,
            device="cpu",
            max_frames=360,
            split_override="unassigned",
        )

        self.assertIn("--non-fall-subtype", cmd)
        self.assertIn("squatting", cmd)
        self.assertIn("--split", cmd)
        self.assertEqual(cmd[cmd.index("--split") + 1], "unassigned")


if __name__ == "__main__":
    unittest.main()
