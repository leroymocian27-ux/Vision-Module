from __future__ import annotations

import unittest

import numpy as np

from app.events.ring_frame_buffer import RingFrameBuffer


class RingFrameBufferTest(unittest.TestCase):
    def test_extracts_nearest_frames_for_event_offsets(self) -> None:
        buffer = RingFrameBuffer(window_seconds=8, max_frames_per_camera=20)
        for index, second in enumerate(range(0, 7)):
            buffer.add_frame(
                "camera_01",
                index,
                f"2026-07-17T09:30:0{second}+00:00",
                np.full((2, 2, 3), index, dtype=np.uint8),
            )

        selections = buffer.extract_event_keyframes(
            "camera_01",
            "2026-07-17T09:30:03+00:00",
            [-3000, -1000, 0, 1000, 3000],
        )

        self.assertEqual([item.role for item in selections], ["pre_context", "pre_fall", "trigger", "post_fall", "post_check"])
        self.assertEqual([item.frame.frame_seq if item.frame else None for item in selections], [0, 2, 3, 4, 6])

    def test_missing_frames_are_reported_without_raising(self) -> None:
        buffer = RingFrameBuffer(window_seconds=1)

        selections = buffer.extract_event_keyframes("camera_01", "2026-07-17T09:30:00+00:00", [0])

        self.assertIsNone(selections[0].frame)
        self.assertEqual(selections[0].missing_reason, "no_buffered_frames")

    def test_limits_window_and_memory(self) -> None:
        buffer = RingFrameBuffer(window_seconds=2, max_frames_per_camera=2, max_bytes_per_camera=30)
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        for index in range(4):
            buffer.add_frame("camera_01", index, f"2026-07-17T09:30:0{index}+00:00", image)

        self.assertLessEqual(buffer.frame_count("camera_01"), 2)
        self.assertLessEqual(buffer.byte_size("camera_01"), 30)
