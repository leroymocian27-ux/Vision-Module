from __future__ import annotations

import asyncio
import time

import numpy as np

from app.camera.frame_buffer import FrameBuffer
from app.core.config import Settings


class LatestFrameVideoTrack:
    def __init__(self, frame_buffer: FrameBuffer, settings: Settings) -> None:
        from aiortc import VideoStreamTrack

        class _Track(VideoStreamTrack):
            def __init__(self) -> None:
                super().__init__()
                self._buffer = frame_buffer
                self._settings = settings
                self._last_seq = 0
                self._last_sent_at: float | None = None
                target_fps = max(1, int(getattr(settings, "webrtc_video_fps", 15) or 15))
                self._target_interval = 1.0 / target_fps
                self._fallback_frame = np.zeros(
                    (
                        settings.mock_camera_height,
                        settings.mock_camera_width,
                        3,
                    ),
                    dtype=np.uint8,
                )

            async def recv(self):
                from av import VideoFrame

                pts, time_base = await self.next_timestamp()
                await self._pace()
                packet = self._buffer.latest()
                if packet is None:
                    await asyncio.sleep(0.02)
                    frame = self._fallback_frame
                else:
                    frame = packet.frame
                    self._last_seq = packet.seq
                video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
                video_frame.pts = pts
                video_frame.time_base = time_base
                return video_frame

            async def _pace(self) -> None:
                now = time.monotonic()
                if self._last_sent_at is None:
                    self._last_sent_at = now
                    return
                wait_for = self._target_interval - (now - self._last_sent_at)
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                self._last_sent_at = time.monotonic()

        self.track = _Track()
