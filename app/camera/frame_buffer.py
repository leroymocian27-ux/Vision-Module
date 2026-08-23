from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np


@dataclass(frozen=True)
class FramePacket:
    camera_id: str
    seq: int
    captured_at: float
    frame: np.ndarray
    source: str = "unknown"
    source_generation: int = 1
    received_at: float | None = None

    @property
    def width(self) -> int:
        return int(self.frame.shape[1])

    @property
    def height(self) -> int:
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
            packet = FramePacket(
                camera_id=self.camera_id,
                seq=self._seq,
                captured_at=time.monotonic(),
                frame=frame,
                source=self.source,
                source_generation=self.source_generation,
                received_at=time.monotonic(),
            )
            self._packet = packet
            return packet

    def latest(self) -> FramePacket | None:
        with self._lock:
            return self._packet
