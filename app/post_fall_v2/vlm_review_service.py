from __future__ import annotations

import concurrent.futures
import time
from threading import BoundedSemaphore, Lock
from typing import Protocol

from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframePackage


class FallVLMAnalyzer(Protocol):
    def analyze_fall_event(self, event: FallEvent, keyframes: KeyframePackage) -> FallDetailResult:
        ...


class DummyFallVLMAnalyzer:
    def analyze_fall_event(self, event: FallEvent, keyframes: KeyframePackage) -> FallDetailResult:
        available_frames = [frame for frame in keyframes.frames if frame.frame_id]
        return FallDetailResult(
            incident_id=event.incident_id,
            analysis_status="completed",
            posture="unknown",
            movement_level="unknown",
            attempt_to_stand="unknown",
            persistent_ground_state="unknown",
            visibility="unknown",
            occlusion="unknown",
            scene_risks=[],
            possible_help_gesture="unknown",
            summary=f"Dummy VLM advisory: {len(available_frames)} keyframes available for post-fall review.",
            review_points=[
                "Review confirmed fall keyframes.",
                "Check whether the person remains on the ground.",
                "Check surrounding environmental risks.",
            ],
            confidence=None,
            model_name="dummy_post_fall_v2_vlm",
        )


class VLMReviewService:
    def __init__(
        self,
        *,
        enabled: bool,
        timeout_seconds: float,
        analyzer: FallVLMAnalyzer | None = None,
        queue_capacity: int = 2,
    ) -> None:
        self.enabled = bool(enabled)
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.analyzer = analyzer or DummyFallVLMAnalyzer()
        self.call_count = 0
        self.timeout_count = 0
        self.failure_count = 0
        self.rejected_count = 0
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="post-fall-v2-vlm")
        self._capacity = BoundedSemaphore(max(1, int(queue_capacity)))
        self._queue_capacity = max(1, int(queue_capacity))
        self._inflight: set[str] = set()
        self._outstanding: set[str] = set()
        self._finished: dict[str, FallDetailResult] = {}
        self._lock = Lock()

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return len(self._outstanding)

    def analyze_fall_event(self, event: FallEvent, keyframes: KeyframePackage) -> FallDetailResult:
        if not self.enabled:
            return FallDetailResult(
                incident_id=event.incident_id,
                analysis_status="disabled",
                summary="VLM review disabled by configuration.",
            )
        with self._lock:
            completed = self._finished.get(event.incident_id)
            if completed is not None:
                return completed
            if event.incident_id in self._inflight or event.incident_id in self._outstanding:
                self.rejected_count += 1
                return _rejected(event, "duplicate_incident_submission")
        if not self._capacity.acquire(blocking=False):
            with self._lock:
                self.rejected_count += 1
            return _rejected(event, "vlm_queue_full")
        with self._lock:
            self._inflight.add(event.incident_id)
            self._outstanding.add(event.incident_id)
            self.call_count += 1
        future = self._executor.submit(self.analyzer.analyze_fall_event, event, keyframes)
        future.add_done_callback(lambda _future: self._release_capacity(event.incident_id))
        started = time.monotonic()
        try:
            result = future.result(timeout=self.timeout_seconds)
        except concurrent.futures.TimeoutError:
            with self._lock:
                self.timeout_count += 1
            future.cancel()
            result = FallDetailResult(
                incident_id=event.incident_id,
                analysis_status="timeout",
                summary="VLM review timed out; binary FallEvent remains valid.",
                error_message=f"timeout after {self.timeout_seconds}s",
            )
        except Exception as exc:
            with self._lock:
                self.failure_count += 1
            result = FallDetailResult(
                incident_id=event.incident_id,
                analysis_status="failed",
                summary="VLM review failed; binary FallEvent remains valid.",
                error_message=str(exc),
            )
        if result.confidence is not None:
            confidence = max(0.0, min(1.0, float(result.confidence)))
            result = FallDetailResult(**{**result.to_record(), "confidence": confidence})
        if not result.model_name:
            result = FallDetailResult(**{**result.to_record(), "model_name": self.analyzer.__class__.__name__})
        latency_ms = int((time.monotonic() - started) * 1000)
        if not result.summary:
            result = FallDetailResult(**{**result.to_record(), "summary": f"VLM review completed in {latency_ms} ms."})
        with self._lock:
            self._inflight.discard(event.incident_id)
            self._finished[event.incident_id] = result
        return result

    def _release_capacity(self, incident_id: str) -> None:
        with self._lock:
            if incident_id not in self._outstanding:
                return
            self._outstanding.discard(incident_id)
        self._capacity.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _rejected(event: FallEvent, reason: str) -> FallDetailResult:
    return FallDetailResult(
        incident_id=event.incident_id,
        analysis_status="failed",
        visibility="insufficient_visual_evidence",
        summary="本地千问任务未进入分析队列，跌倒事件仍以二分类确认结果为准。",
        review_points=["复核实时画面。"],
        error_message=reason,
    )
