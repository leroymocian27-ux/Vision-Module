from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np

from app.events.schemas import EvidenceKeyframe
from app.events.timeline_image import build_timeline_image


class TimelineImageTest(unittest.TestCase):
    def test_builds_timeline_with_missing_placeholders(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            keyframe_dir = root / "keyframes"
            keyframe_dir.mkdir()
            image = np.full((32, 48, 3), 120, dtype=np.uint8)
            self.assertTrue(cv2.imwrite(str(keyframe_dir / "t0.jpg"), image))
            output = root / "timeline.jpg"

            result = build_timeline_image(
                [
                    EvidenceKeyframe(role="trigger", offset_ms=0, frame_seq=42, fall_state="fallen_candidate", image_path="keyframes/t0.jpg"),
                    EvidenceKeyframe(role="post_check", offset_ms=5000, missing_reason="no_frame_near_target"),
                ],
                root,
                output,
                cell_width=80,
                cell_height=60,
            )

            self.assertEqual(result, output)
            self.assertTrue(output.exists())
            composed = cv2.imread(str(output), cv2.IMREAD_COLOR)
            self.assertIsNotNone(composed)
            self.assertEqual(composed.shape[:2], (120, 240))

    def test_ignores_absolute_keyframe_paths(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.jpg"
            self.assertTrue(cv2.imwrite(str(outside), np.zeros((20, 20, 3), dtype=np.uint8)))
            output = root / "timeline.jpg"

            build_timeline_image(
                [EvidenceKeyframe(role="trigger", offset_ms=0, image_path=str(outside))],
                root,
                output,
                cell_width=80,
                cell_height=60,
            )

            self.assertTrue(output.exists())

    def test_all_missing_frames_still_build_placeholder_image(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "timeline.jpg"

            build_timeline_image([], directory, output, cell_width=80, cell_height=60)

            self.assertTrue(output.exists())
            composed = cv2.imread(str(output), cv2.IMREAD_COLOR)
            self.assertIsNotNone(composed)
            self.assertEqual(composed.shape[:2], (120, 240))


if __name__ == "__main__":
    unittest.main()
