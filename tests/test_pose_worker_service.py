from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

import numpy as np

from app.core.config import Settings
from app.detection.realtime_result_store import DetectionSnapshot, ObjectSnapshot, RealtimeResultStore
from app.schemas.vision_result import DetectedObject
from app.services.pose_worker_service import PoseWorkerService


class _FakePoseService:
    placeholder_mode = False

    def __init__(self) -> None:
        self.desync_reasons: list[str] = []
        self.skip_reasons: list[str] = []
        self.enriched_frame_seq: int | None = None

    def record_worker_tick(self, camera_id: str) -> None:
        pass

    def record_context(self, *args, **kwargs) -> None:
        pass

    def record_skip(self, camera_id: str, reason: str) -> None:
        self.skip_reasons.append(reason)

    def record_desync(self, camera_id: str, **kwargs) -> None:
        self.desync_reasons.append(str(kwargs.get("reason")))

    def enrich(self, camera_id: str, frame, objects, frame_seq=None, **kwargs):
        self.enriched_frame_seq = frame_seq
        return [item.model_copy(update={"pose": {"keypoints": [{"confidence": 0.9}]}}) for item in objects]


class _FakeSourceManager:
    def __init__(self, status) -> None:
        self._status = status

    def worker_status(self, camera_id: str):
        return self._status


class PoseWorkerServiceTest(unittest.TestCase):
    def test_tick_uses_detection_history_matching_tracking_frame(self) -> None:
        store = RealtimeResultStore()
        pose_service = _FakePoseService()
        worker = PoseWorkerService(
            settings=Settings(),
            source_manager=None,
            realtime_store=store,
            pose_service=pose_service,  # type: ignore[arg-type]
        )
        tracked = DetectedObject(
            label="person",
            confidence=0.9,
            bbox=[100.0, 100.0, 200.0, 320.0],
            track_id=1,
            is_target=True,
        )
        old_detection = self._detection(10)
        latest_detection = self._detection(13)
        store.update_detection(old_detection)
        store.update_detection(latest_detection)
        store.update_tracking(
            ObjectSnapshot(
                camera_id="camera_01",
                frame_seq=10,
                frame_width=640,
                frame_height=360,
                timestamp="2026-07-05T00:00:00Z",
                monotonic_at=time.monotonic(),
                objects=[tracked],
            )
        )

        worker._tick("camera_01")

        self.assertEqual(pose_service.enriched_frame_seq, 10)
        self.assertNotIn("frame_tracking_desync", pose_service.desync_reasons)
        pose = store.latest_pose("camera_01")
        self.assertIsNotNone(pose)
        assert pose is not None
        self.assertEqual(pose.frame_seq, 10)

    def test_repeated_stale_detection_frame_is_counted_once(self) -> None:
        store = RealtimeResultStore()
        pose_service = _FakePoseService()
        worker = PoseWorkerService(
            settings=Settings(pose_max_frame_age_ms=10),
            source_manager=None,
            realtime_store=store,
            pose_service=pose_service,  # type: ignore[arg-type]
        )
        tracking = ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=10,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-05T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[100.0, 100.0, 200.0, 320.0],
                    track_id=1,
                    is_target=True,
                )
            ],
        )
        stale_detection = self._detection(10, monotonic_at=time.monotonic() - 1.0)

        first = worker._matching_detection_frame("camera_01", tracking, stale_detection)
        second = worker._matching_detection_frame("camera_01", tracking, stale_detection)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(pose_service.desync_reasons, ["pose_frame_stale"])
        self.assertEqual(pose_service.skip_reasons, ["pose_frame_stale_duplicate"])

    def test_stale_detection_from_eof_source_is_classified_separately(self) -> None:
        store = RealtimeResultStore()
        pose_service = _FakePoseService()
        source_manager = _FakeSourceManager(
            SimpleNamespace(
                stream_state="disconnected",
                reconnect_reason="eof",
                connected=False,
                frame_age_ms=2000.0,
            )
        )
        worker = PoseWorkerService(
            settings=Settings(pose_max_frame_age_ms=10),
            source_manager=source_manager,  # type: ignore[arg-type]
            realtime_store=store,
            pose_service=pose_service,  # type: ignore[arg-type]
        )
        tracking = self._tracking(10)
        stale_detection = self._detection(10, monotonic_at=time.monotonic() - 1.0)

        result = worker._matching_detection_frame("camera_01", tracking, stale_detection)

        self.assertIsNone(result)
        self.assertEqual(pose_service.desync_reasons, ["pose_frame_stale_source_eof"])

    def test_stale_detection_with_fresh_connected_source_is_detection_lag(self) -> None:
        store = RealtimeResultStore()
        pose_service = _FakePoseService()
        source_manager = _FakeSourceManager(
            SimpleNamespace(
                stream_state="connected",
                reconnect_reason=None,
                connected=True,
                frame_age_ms=1.0,
            )
        )
        worker = PoseWorkerService(
            settings=Settings(pose_max_frame_age_ms=10),
            source_manager=source_manager,  # type: ignore[arg-type]
            realtime_store=store,
            pose_service=pose_service,  # type: ignore[arg-type]
        )
        tracking = self._tracking(10)
        stale_detection = self._detection(10, monotonic_at=time.monotonic() - 1.0)

        result = worker._matching_detection_frame("camera_01", tracking, stale_detection)

        self.assertIsNone(result)
        self.assertEqual(pose_service.desync_reasons, ["pose_frame_stale_detection_lag"])

    @staticmethod
    def _detection(seq: int, monotonic_at: float | None = None) -> DetectionSnapshot:
        return DetectionSnapshot(
            camera_id="camera_01",
            frame_seq=seq,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-05T00:00:00Z",
            monotonic_at=time.monotonic() if monotonic_at is None else monotonic_at,
            frame=np.zeros((360, 640, 3), dtype=np.uint8),
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[100.0, 100.0, 200.0, 320.0],
                    track_id=1,
                    is_target=True,
                )
            ],
        )

    @staticmethod
    def _tracking(seq: int) -> ObjectSnapshot:
        return ObjectSnapshot(
            camera_id="camera_01",
            frame_seq=seq,
            frame_width=640,
            frame_height=360,
            timestamp="2026-07-05T00:00:00Z",
            monotonic_at=time.monotonic(),
            objects=[
                DetectedObject(
                    label="person",
                    confidence=0.9,
                    bbox=[100.0, 100.0, 200.0, 320.0],
                    track_id=1,
                    is_target=True,
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
