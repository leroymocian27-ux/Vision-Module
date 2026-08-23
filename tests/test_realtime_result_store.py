from __future__ import annotations

import unittest

import numpy as np

from app.detection.realtime_result_store import DetectionSnapshot, RealtimeResultStore


class RealtimeResultStoreTest(unittest.TestCase):
    def test_detection_history_can_return_previous_frame(self) -> None:
        store = RealtimeResultStore()
        first = self._snapshot(10)
        second = self._snapshot(12)

        store.update_detection(first)
        store.update_detection(second)

        self.assertIs(store.latest_detection("camera_01"), second)
        self.assertIs(store.detection_for_frame("camera_01", 10), first)
        self.assertIs(store.detection_for_frame("camera_01", 12), second)

    def test_detection_history_is_bounded(self) -> None:
        store = RealtimeResultStore()

        for seq in range(RealtimeResultStore.DETECTION_HISTORY_LIMIT + 2):
            store.update_detection(self._snapshot(seq))

        self.assertIsNone(store.detection_for_frame("camera_01", 0))
        self.assertIsNone(store.detection_for_frame("camera_01", 1))
        self.assertIsNotNone(store.detection_for_frame("camera_01", 2))

    @staticmethod
    def _snapshot(seq: int) -> DetectionSnapshot:
        return DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=seq,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-05T00:00:00Z",
            monotonic_at=1.0,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[],
        )


if __name__ == "__main__":
    unittest.main()
