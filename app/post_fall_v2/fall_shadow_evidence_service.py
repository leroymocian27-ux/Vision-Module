from __future__ import annotations

import json
import time
from pathlib import Path
import threading

import cv2

from app.post_fall_v2.schemas import BinaryFallResult, SampledFrame


class FallShadowEvidenceService:
    def __init__(
        self,
        *,
        output_dir: str | Path,
        save_metadata: bool = True,
        save_frames: bool = False,
        save_frame_probability_threshold: float = 0.3,
        save_max_frames_per_minute: int = 6,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.save_metadata = save_metadata
        self.save_frames = save_frames
        self.save_frame_probability_threshold = float(save_frame_probability_threshold)
        self.save_max_frames_per_minute = max(0, int(save_max_frames_per_minute))
        self.last_error: str | None = None
        self.records_written = 0
        self.frames_saved = 0
        self.write_errors = 0
        self._lock = threading.Lock()
        self._frame_save_bucket: dict[tuple[str, int], int] = {}

    def write(self, result: BinaryFallResult, sampled: SampledFrame | None = None) -> None:
        if not self.save_metadata and not self.save_frames:
            return
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            record = result.to_record()
            if self.save_frames and sampled is not None and self._should_save_frame(result):
                frame_path = self._save_frame(result, sampled)
                record["saved_frame_path"] = str(frame_path)
            if self.save_metadata:
                path = self.output_dir / f"shadow_{result.camera_id}.jsonl"
                with self._lock:
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    self.records_written += 1
            self.last_error = None
        except Exception as exc:
            self.write_errors += 1
            self.last_error = str(exc)

    def _should_save_frame(self, result: BinaryFallResult) -> bool:
        if result.fall_probability is None:
            return False
        if result.fall_probability < self.save_frame_probability_threshold:
            return False
        if self.save_max_frames_per_minute <= 0:
            return False
        minute = int(time.time() // 60)
        key = (result.camera_id, minute)
        with self._lock:
            used = self._frame_save_bucket.get(key, 0)
            if used >= self.save_max_frames_per_minute:
                return False
            self._frame_save_bucket[key] = used + 1
        return True

    def _save_frame(self, result: BinaryFallResult, sampled: SampledFrame) -> Path:
        frames_dir = self.output_dir / "frames" / result.camera_id
        frames_dir.mkdir(parents=True, exist_ok=True)
        path = frames_dir / f"{result.frame_id}.jpg"
        if not cv2.imwrite(str(path), sampled.frame, [cv2.IMWRITE_JPEG_QUALITY, 88]):
            raise RuntimeError(f"failed to write frame: {path}")
        self.frames_saved += 1
        return path

