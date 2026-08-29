from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import numpy as np


class FramePacket:
    def __init__(
        self,
        *,
        camera_id: str,
        seq: int,
        captured_at: float,
        frame: np.ndarray | None = None,
        source: str = "unknown",
        source_generation: int = 1,
        received_at: float | None = None,
        jpeg_bytes: bytes | None = None,
        frame_width: int | None = None,
        frame_height: int | None = None,
    ) -> None:
        if frame is None and not jpeg_bytes:
            raise ValueError("FramePacket requires frame or jpeg_bytes")
        self.camera_id = camera_id
        self.seq = int(seq)
        self.captured_at = float(captured_at)
        self.source = source
        self.source_generation = int(source_generation)
        self.received_at = received_at
        self.jpeg_bytes = bytes(jpeg_bytes) if jpeg_bytes is not None else None
        self._frame = frame
        self._frame_width = frame_width
        self._frame_height = frame_height
        self._decode_lock = threading.Lock()

    @property
    def frame(self) -> np.ndarray:
        if self._frame is not None:
            return self._frame
        if not self.jpeg_bytes:
            raise ValueError("FramePacket has no frame data")
        with self._decode_lock:
            if self._frame is None:
                import cv2

                decoded = cv2.imdecode(np.frombuffer(self.jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                if decoded is None:
                    raise ValueError("failed to decode JPEG frame")
                self._frame = decoded
                self._frame_height = int(decoded.shape[0])
                self._frame_width = int(decoded.shape[1])
        return self._frame

    @property
    def width(self) -> int:
        if self._frame_width is not None:
            return int(self._frame_width)
        return int(self.frame.shape[1])

    @property
    def height(self) -> int:
        if self._frame_height is not None:
            return int(self._frame_height)
        return int(self.frame.shape[0])

    @property
    def age_ms(self) -> float:
        return round((time.monotonic() - self.captured_at) * 1000, 2)

    @property
    def captured_at_iso(self) -> str:
        wall_clock = time.time() - (time.monotonic() - self.captured_at)
        return datetime.fromtimestamp(wall_clock, timezone.utc).isoformat(timespec="milliseconds")

    @property
    def received_at_iso(self) -> str:
        received_at = self.received_at if self.received_at is not None else self.captured_at
        wall_clock = time.time() - (time.monotonic() - received_at)
        return datetime.fromtimestamp(wall_clock, timezone.utc).isoformat(timespec="milliseconds")


class FrameBuffer:
    """Non-consuming latest-frame cache shared by video and detection paths."""

    def __init__(self, camera_id: str, *, source: str = "unknown", source_generation: int = 1) -> None:
        self.camera_id = camera_id
        self.source = source
        self.source_generation = source_generation
        self._lock = threading.Lock()
        self._packet: FramePacket | None = None
        self._seq = 0

    def update(self, frame: np.ndarray) -> FramePacket:
        with self._lock:
            self._seq += 1
            now = time.monotonic()
            packet = FramePacket(
                camera_id=self.camera_id,
                seq=self._seq,
                captured_at=now,
                frame=frame,
                source=self.source,
                source_generation=self.source_generation,
                received_at=now,
            )
            self._packet = packet
            return packet

    def update_jpeg(
        self,
        jpeg_bytes: bytes,
        *,
        width: int | None = None,
        height: int | None = None,
        captured_at: float | None = None,
        received_at: float | None = None,
    ) -> FramePacket:
        now = time.monotonic()
        with self._lock:
            self._seq += 1
            packet = FramePacket(
                camera_id=self.camera_id,
                seq=self._seq,
                captured_at=now if captured_at is None else captured_at,
                source=self.source,
                source_generation=self.source_generation,
                received_at=now if received_at is None else received_at,
                jpeg_bytes=jpeg_bytes,
                frame_width=width,
                frame_height=height,
            )
            self._packet = packet
            return packet

    def latest(self) -> FramePacket | None:
        with self._lock:
            return self._packet
