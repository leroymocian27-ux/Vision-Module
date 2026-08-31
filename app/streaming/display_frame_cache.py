from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

import cv2

from app.camera.frame_buffer import FramePacket
from app.monitoring.metrics import FPSMeter


@dataclass(frozen=True)
class DisplayFrameEntry:
    camera_id: str
    frame_seq: int
    source_generation: int
    target_height: int
    jpeg_quality: int
    content: bytes
    width: int
    height: int
    encoded_at: float
    source_frame_age_ms: float
    encode_ms: float
    cache_hit: bool = False


class DisplayFrameCache:
    """Shared display JPEG cache so multiple viewers do not re-encode one frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, DisplayFrameEntry] = {}
        self._encoded_frames: dict[str, int] = {}
        self._cache_hits: dict[str, int] = {}
        self._served_frames: dict[str, int] = {}
        self._mjpeg_served_frames: dict[str, int] = {}
        self._latest_frame_served_frames: dict[str, int] = {}
        self._encode_fps: dict[str, FPSMeter] = {}
        self._served_fps: dict[str, FPSMeter] = {}
        self._mjpeg_served_fps: dict[str, FPSMeter] = {}
        self._latest_frame_served_fps: dict[str, FPSMeter] = {}
        self._encode_ms: dict[str, float] = {}
        self._encode_ms_max: dict[str, float] = {}
        self._encode_locks: dict[str, threading.Lock] = {}

    def render(self, packet: FramePacket, settings) -> DisplayFrameEntry:
        target_height = int(getattr(settings, "display_frame_height", 0) or 0)
        jpeg_quality = int(getattr(settings, "display_jpeg_quality", 72) or 72)
        camera_id = packet.camera_id
        with self._lock:
            entry = self._entries.get(camera_id)
            if self._is_cache_match(entry, packet, target_height, jpeg_quality):
                self._cache_hits[camera_id] = self._cache_hits.get(camera_id, 0) + 1
                return replace(entry, cache_hit=True)
            encode_lock = self._encode_locks.setdefault(camera_id, threading.Lock())

        with encode_lock:
            with self._lock:
                entry = self._entries.get(camera_id)
                if self._is_cache_match(entry, packet, target_height, jpeg_quality):
                    self._cache_hits[camera_id] = self._cache_hits.get(camera_id, 0) + 1
                    return replace(entry, cache_hit=True)
            started = time.monotonic()
            frame = _resize_display_frame(packet.frame, target_height)
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality],
            )
            if not ok:
                raise ValueError("DISPLAY_FRAME_ENCODE_FAILED")
            encode_ms = round((time.monotonic() - started) * 1000, 2)
            height = int(frame.shape[0])
            width = int(frame.shape[1])
            entry = DisplayFrameEntry(
                camera_id=camera_id,
                frame_seq=packet.seq,
                source_generation=packet.source_generation,
                target_height=target_height,
                jpeg_quality=jpeg_quality,
                content=encoded.tobytes(),
                width=width,
                height=height,
                encoded_at=time.monotonic(),
                source_frame_age_ms=packet.age_ms,
                encode_ms=encode_ms,
            )
        with self._lock:
            self._entries[camera_id] = entry
            self._encoded_frames[camera_id] = self._encoded_frames.get(camera_id, 0) + 1
            self._encode_ms[camera_id] = encode_ms
            self._encode_ms_max[camera_id] = round(
                max(encode_ms, self._encode_ms_max.get(camera_id, 0.0)),
                2,
            )
            self._encode_fps.setdefault(camera_id, FPSMeter()).tick()
            return entry

    def mark_served(self, camera_id: str, *, consumer: str = "display_mjpg") -> None:
        with self._lock:
            self._served_frames[camera_id] = self._served_frames.get(camera_id, 0) + 1
            self._served_fps.setdefault(camera_id, FPSMeter()).tick()
            if consumer == "latest_frame":
                self._latest_frame_served_frames[camera_id] = self._latest_frame_served_frames.get(camera_id, 0) + 1
                self._latest_frame_served_fps.setdefault(camera_id, FPSMeter()).tick()
            else:
                self._mjpeg_served_frames[camera_id] = self._mjpeg_served_frames.get(camera_id, 0) + 1
                self._mjpeg_served_fps.setdefault(camera_id, FPSMeter()).tick()

    def status(self, camera_id: str | None = None) -> dict:
        with self._lock:
            entries = {
                key: value
                for key, value in self._entries.items()
                if camera_id is None or key == camera_id
            }
            if camera_id is not None:
                camera_ids = {camera_id}
            else:
                camera_ids = (
                    set(self._entries)
                    | set(self._encoded_frames)
                    | set(self._served_frames)
                    | set(self._mjpeg_served_frames)
                    | set(self._latest_frame_served_frames)
                )
            per_camera = {}
            for key in sorted(camera_ids):
                entry = entries.get(key)
                per_camera[key] = {
                    "encoded_frames": self._encoded_frames.get(key, 0),
                    "cache_hits": self._cache_hits.get(key, 0),
                    "served_frames": self._served_frames.get(key, 0),
                    "display_mjpeg_served_frames": self._mjpeg_served_frames.get(key, 0),
                    "latest_frame_served_frames": self._latest_frame_served_frames.get(key, 0),
                    "display_encode_fps": self._encode_fps.get(key, FPSMeter()).fps,
                    "display_served_fps": self._served_fps.get(key, FPSMeter()).fps,
                    "display_mjpeg_served_fps": self._mjpeg_served_fps.get(key, FPSMeter()).fps,
                    "latest_frame_served_fps": self._latest_frame_served_fps.get(key, FPSMeter()).fps,
                    "last_frame_seq": entry.frame_seq if entry else None,
                    "last_source_generation": entry.source_generation if entry else None,
                    "encoded_width": entry.width if entry else None,
                    "encoded_height": entry.height if entry else None,
                    "target_height": entry.target_height if entry else None,
                    "jpeg_quality": entry.jpeg_quality if entry else None,
                    "encode_ms": self._encode_ms.get(key),
                    "encode_ms_max": self._encode_ms_max.get(key),
                    "display_age_ms": round((time.monotonic() - entry.encoded_at) * 1000, 2) if entry else None,
                    "source_frame_age_ms_at_encode": entry.source_frame_age_ms if entry else None,
                }
            return {
                "cache_entries": len(entries),
                "cameras": per_camera,
            }

    def reset(self, camera_id: str | None = None) -> None:
        with self._lock:
            keys = [camera_id] if camera_id is not None else list(
                set(self._entries)
                | set(self._encoded_frames)
                | set(self._served_frames)
                | set(self._mjpeg_served_frames)
                | set(self._latest_frame_served_frames)
            )
            for key in keys:
                self._entries.pop(key, None)
                self._encoded_frames.pop(key, None)
                self._cache_hits.pop(key, None)
                self._served_frames.pop(key, None)
                self._mjpeg_served_frames.pop(key, None)
                self._latest_frame_served_frames.pop(key, None)
                self._encode_fps.pop(key, None)
                self._served_fps.pop(key, None)
                self._mjpeg_served_fps.pop(key, None)
                self._latest_frame_served_fps.pop(key, None)
                self._encode_ms.pop(key, None)
                self._encode_ms_max.pop(key, None)

    @staticmethod
    def _is_cache_match(
        entry: DisplayFrameEntry | None,
        packet: FramePacket,
        target_height: int,
        jpeg_quality: int,
    ) -> bool:
        return bool(
            entry is not None
            and entry.frame_seq == packet.seq
            and entry.source_generation == packet.source_generation
            and entry.target_height == target_height
            and entry.jpeg_quality == jpeg_quality
        )


def _resize_display_frame(frame, target_height: int):
    shape = getattr(frame, "shape", ())
    height = int(shape[0] or 0) if len(shape) >= 1 else 0
    width = int(shape[1] or 0) if len(shape) >= 2 else 0
    if target_height <= 0 or height <= 0 or width <= 0 or height <= target_height:
        return frame
    target_width = max(1, round(width * target_height / height))
    return cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)


_DISPLAY_FRAME_CACHE = DisplayFrameCache()


def get_display_frame_cache() -> DisplayFrameCache:
    return _DISPLAY_FRAME_CACHE
