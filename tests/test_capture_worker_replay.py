from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from app.camera.capture_worker import CaptureWorker
from app.camera.frame_buffer import FrameBuffer
from app.camera.source_models import CameraSourceConfig
from app.core.config import Settings


class FakeVideoCapture:
    def __init__(self, source_url: str) -> None:
        self.source_url = source_url
        self.released = False
        self.frames = [
            np.zeros((8, 10, 3), dtype=np.uint8),
            np.ones((8, 10, 3), dtype=np.uint8),
        ]
        self.read_count = 0
        FakeVideoCapture.instances.append(self)

    instances: list["FakeVideoCapture"] = []

    def isOpened(self) -> bool:
        return True

    def get(self, prop: int) -> float:
        if prop == 5:
            return 2.0
        return 0.0

    def set(self, prop: int, value: object) -> bool:
        return True

    def read(self):
        if self.read_count >= len(self.frames):
            return False, None
        frame = self.frames[self.read_count]
        self.read_count += 1
        return True, frame

    def release(self) -> None:
        self.released = True


class CaptureWorkerReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_cv2 = sys.modules.get("cv2")
        FakeVideoCapture.instances = []
        fake_cv2 = types.SimpleNamespace(
            VideoCapture=FakeVideoCapture,
            CAP_PROP_FPS=5,
            CAP_PROP_OPEN_TIMEOUT_MSEC=53,
            CAP_PROP_READ_TIMEOUT_MSEC=54,
            CAP_PROP_BUFFERSIZE=38,
        )
        sys.modules["cv2"] = fake_cv2

    def tearDown(self) -> None:
        if self.previous_cv2 is None:
            sys.modules.pop("cv2", None)
        else:
            sys.modules["cv2"] = self.previous_cv2

    def test_local_file_capture_uses_video_fps_throttle_and_completes(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video_file:
            buffer = FrameBuffer("camera_01")
            worker = CaptureWorker(
                CameraSourceConfig(
                    camera_id="camera_01",
                    source_url=str(Path(video_file.name)),
                ),
                buffer,
                Settings(
                    capture_read_warn_ms=10000,
                    capture_read_stale_ms=20000,
                    stream_stale_threshold_ms=20000,
                    opencv_capture_buffersize=1,
                ),
            )
            wait_mock = Mock(return_value=False)
            worker._stop_event.wait = wait_mock

            worker._run()

        self.assertEqual(buffer.latest().seq, 2)
        waits = [call.args[0] for call in wait_mock.call_args_list]
        self.assertEqual(len(waits), 2)
        self.assertTrue(all(delay > 0.0 for delay in waits))
        self.assertLessEqual(waits[0], 0.5)
        self.assertEqual(worker.status().reconnect_reason, "eof")
        self.assertEqual(worker.status().stream_state, "disconnected")
        self.assertTrue(FakeVideoCapture.instances[0].released)

    def test_invalid_video_fps_falls_back_to_ten_fps(self) -> None:
        cap = Mock()
        cap.get.return_value = 0.0

        self.assertEqual(CaptureWorker._local_file_replay_fps(cap), 10.0)


if __name__ == "__main__":
    unittest.main()
