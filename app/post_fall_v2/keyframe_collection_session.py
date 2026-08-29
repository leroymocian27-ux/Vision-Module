from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

import cv2

from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.schemas import BufferedFrame, KeyframeItem, KeyframePackage, monotonic_to_utc_iso


KeyframeCollectionStatus = Literal["collecting", "ready", "degraded", "expired", "cancelled"]


@dataclass(frozen=True)
class KeyframeCollectionSnapshot:
    incident_id: str
    camera_id: str
    confirmed_monotonic: float
    confirmed_at: str
    required_offsets_ms: list[int]
    collected_frames: list[KeyframeItem]
    missing_offsets: list[int]
    started_at: float
    deadline: float
    status: KeyframeCollectionStatus
    resolved_offsets: list[int] = field(default_factory=list)
    max_offset_error_ms: int | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "incident_id": self.incident_id,
            "camera_id": self.camera_id,
            "confirmed_monotonic": self.confirmed_monotonic,
            "confirmed_at": self.confirmed_at,
            "required_offsets_ms": list(self.required_offsets_ms),
            "collected_frames": [item.to_record() for item in self.collected_frames],
            "missing_offsets": list(self.missing_offsets),
            "started_at": self.started_at,
            "deadline": self.deadline,
            "status": self.status,
            "resolved_offsets": list(self.resolved_offsets),
            "max_offset_error_ms": self.max_offset_error_ms,
        }


@dataclass(frozen=True)
class _ResolvedFrame:
    item: KeyframeItem
    frame: BufferedFrame | None


class KeyframeCollectionSession:
    def __init__(
        self,
        *,
        incident_id: str,
        camera_id: str,
        confirmed_monotonic: float,
        confirmed_at: str | None = None,
        required_offsets_ms: tuple[int, ...] = (-1000, 0, 3000),
        tolerance_ms: int = 750,
        collection_window_seconds: float = 3.5,
        max_observations: int = 128,
    ) -> None:
        self.incident_id = incident_id
        self.camera_id = camera_id
        self.confirmed_monotonic = float(confirmed_monotonic)
        self.confirmed_at = confirmed_at or monotonic_to_utc_iso(confirmed_monotonic)
        self.required_offsets_ms = tuple(int(value) for value in required_offsets_ms)
        self.tolerance_ms = max(0, int(tolerance_ms))
        self.collection_window_seconds = max(0.1, float(collection_window_seconds))
        self.started_at = time.monotonic()
        self.deadline = self.started_at + self.collection_window_seconds
        self.max_observations = max(8, int(max_observations))
        self._lock = threading.Lock()
        self._cancelled = False
        self._observations: deque[BufferedFrame] = deque()
        self._seen_frame_ids: set[str] = set()

    def prime_buffer(self, frames: list[BufferedFrame]) -> None:
        for frame in frames:
            self.observe_buffered_frame(frame)

    def observe_sampled_frame(self, sampled) -> bool:
        if self._cancelled or sampled.camera_id != self.camera_id:
            return False
        frame = BufferedFrame(
            camera_id=sampled.camera_id,
            frame_id=sampled.frame_id,
            frame_seq=sampled.frame_seq,
            timestamp=sampled.captured_at,
            monotonic_at=sampled.captured_monotonic,
            source_width=sampled.source_width,
            source_height=sampled.source_height,
            frame=sampled.frame.copy(),
            target_binding=getattr(sampled, "target_binding", None),
        )
        return self.observe_buffered_frame(frame)

    def observe_buffered_frame(self, frame: BufferedFrame) -> bool:
        if self._cancelled or frame.camera_id != self.camera_id:
            return False
        with self._lock:
            if frame.frame_id in self._seen_frame_ids:
                return False
            self._seen_frame_ids.add(frame.frame_id)
            self._observations.append(frame)
            while len(self._observations) > self.max_observations:
                oldest = self._observations.popleft()
                self._seen_frame_ids.discard(oldest.frame_id)
            return True

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self._observations.clear()
            self._seen_frame_ids.clear()

    def release_media(self) -> None:
        with self._lock:
            self._observations.clear()
            self._seen_frame_ids.clear()

    def status(self, now_monotonic: float | None = None) -> KeyframeCollectionStatus:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        if self._cancelled:
            return "cancelled"
        snapshot = self.snapshot(now_monotonic=now)
        return snapshot.status

    def snapshot(self, now_monotonic: float | None = None) -> KeyframeCollectionSnapshot:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        resolved = self._resolve(now)
        missing = [item.item.offset_ms for item in resolved if item.item.missing_reason]
        resolved_offsets = [item.item.offset_ms for item in resolved if item.item.frame_id]
        if self._cancelled:
            status: KeyframeCollectionStatus = "cancelled"
        elif not missing:
            status = "ready"
        elif now < self.deadline:
            status = "collecting"
        elif now >= self.deadline:
            status = "expired" if len(resolved_offsets) == 0 else "degraded"
        else:
            status = "degraded"
        return KeyframeCollectionSnapshot(
            incident_id=self.incident_id,
            camera_id=self.camera_id,
            confirmed_monotonic=self.confirmed_monotonic,
            confirmed_at=self.confirmed_at,
            required_offsets_ms=list(self.required_offsets_ms),
            collected_frames=[item.item for item in resolved if item.item.frame_id],
            missing_offsets=missing,
            started_at=self.started_at,
            deadline=self.deadline,
            status=status,
            resolved_offsets=resolved_offsets,
            max_offset_error_ms=self.tolerance_ms,
        )

    def build_package(self, now_monotonic: float | None = None) -> KeyframePackage:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        resolved = self._resolve(now)
        frames = [item.item for item in resolved]
        missing = [item.item.offset_ms for item in resolved if item.item.missing_reason]
        resolved_offsets = [item.item.offset_ms for item in resolved if item.item.frame_id]
        source_width = max((item.frame.source_width for item in resolved if item.frame is not None), default=0)
        source_height = max((item.frame.source_height for item in resolved if item.frame is not None), default=0)
        target_binding = next(
            (item.frame.target_binding for item in resolved if item.frame is not None and item.frame.target_binding),
            None,
        )
        status = "ready" if not missing and not self._cancelled else "degraded"
        if self._cancelled:
            status = "cancelled"  # type: ignore[assignment]
        elif now < self.deadline and missing:
            status = "collecting"
        elif missing:
            status = "degraded"
        return KeyframePackage(
            incident_id=self.incident_id,
            camera_id=self.camera_id,
            confirmed_at=self.confirmed_at,
            source_width=source_width,
            source_height=source_height,
            frames=frames,
            fall_probability_summary={},
            status=status if status in {"collecting", "ready", "degraded"} else "degraded",
            requested_offsets_ms=list(self.required_offsets_ms),
            resolved_offsets_ms=resolved_offsets,
            missing_offsets_ms=missing,
            max_offset_error_ms=self.tolerance_ms,
            target_binding=target_binding,
        )

    def export_qwen_images(
        self,
        *,
        max_images: int,
        max_image_bytes: int,
        max_edge: int = 1280,
        jpeg_quality: int = 85,
        now_monotonic: float | None = None,
    ) -> tuple[list[QwenImageInput], list[str]]:
        resolved = self._resolve(time.monotonic() if now_monotonic is None else now_monotonic)
        images: list[QwenImageInput] = []
        missing: list[str] = []
        for item in resolved:
            if item.item.missing_reason or item.frame is None:
                if item.item.missing_reason:
                    missing.append(item.item.missing_reason)
                continue
            if len(images) >= max(1, int(max_images)):
                break
            frame = _resize_for_qwen(item.frame.frame, max_edge=max_edge)
            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(40, min(95, int(jpeg_quality)))],
            )
            if not ok:
                missing.append("keyframe_encode_failed")
                continue
            image_bytes = encoded.tobytes()
            if len(image_bytes) > max(1024, int(max_image_bytes)):
                missing.append("keyframe_image_too_large")
                continue
            images.append(QwenImageInput(offset_ms=item.item.offset_ms, role=item.item.role, image_bytes=image_bytes))
        return images, list(dict.fromkeys(missing))

    def _resolve(self, now_monotonic: float) -> list[_ResolvedFrame]:
        with self._lock:
            observations = list(self._observations)
        used_frame_ids: set[str] = set()
        resolved: list[_ResolvedFrame] = []
        tolerance_seconds = self.tolerance_ms / 1000.0
        for offset_ms in self.required_offsets_ms:
            target = self.confirmed_monotonic + (offset_ms / 1000.0)
            if target > now_monotonic + tolerance_seconds:
                resolved.append(_ResolvedFrame(item=self._missing(offset_ms, "future_frame_not_available_yet"), frame=None))
                continue
            best: BufferedFrame | None = None
            best_error: float | None = None
            for frame in observations:
                if frame.frame_id in used_frame_ids:
                    continue
                error = abs(frame.monotonic_at - target)
                if error > tolerance_seconds:
                    continue
                if best is None or error < best_error:  # type: ignore[operator]
                    best = frame
                    best_error = error
            if best is None:
                resolved.append(_ResolvedFrame(item=self._missing(offset_ms, "no_frame_within_tolerance"), frame=None))
                continue
            used_frame_ids.add(best.frame_id)
            actual_offset_ms = int(round((best.monotonic_at - self.confirmed_monotonic) * 1000))
            timing_error_ms = int(round(abs(best.monotonic_at - target) * 1000))
            resolved.append(
                _ResolvedFrame(
                    item=KeyframeItem(
                        role=self._role(offset_ms),
                        offset_ms=offset_ms,
                        frame_id=best.frame_id,
                        frame_seq=best.frame_seq,
                        timestamp=best.timestamp,
                        actual_offset_ms=actual_offset_ms,
                        timing_error_ms=timing_error_ms,
                        target_binding=best.target_binding,
                    ),
                    frame=best,
                )
            )
        return resolved

    @staticmethod
    def _role(offset_ms: int) -> str:
        if offset_ms < -1000:
            return "pre_context"
        if offset_ms < 0:
            return "pre_fall"
        if offset_ms == 0:
            return "trigger"
        if offset_ms <= 3000:
            return "post_fall"
        return "post_check"

    @staticmethod
    def _missing(offset_ms: int, reason: str) -> KeyframeItem:
        return KeyframeItem(
            role=KeyframeCollectionSession._role(offset_ms),
            offset_ms=offset_ms,
            frame_id=None,
            frame_seq=None,
            timestamp=None,
            missing_reason=reason,
        )


def _resize_for_qwen(frame, *, max_edge: int):
    height, width = frame.shape[:2]
    limit = max(128, int(max_edge))
    if max(height, width) <= limit:
        return frame
    scale = limit / float(max(height, width))
    target = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(frame, target, interpolation=cv2.INTER_AREA)
