from __future__ import annotations

import concurrent.futures
import time
from threading import BoundedSemaphore, Lock
from typing import Any, Protocol

from app.events.qwen_keyframe import POST_FALL_FUSION_VERSION, POST_FALL_PROMPT_VERSION, POST_FALL_SCHEMA_VERSION
from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframePackage


FUSION_VERSION = POST_FALL_FUSION_VERSION


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
        submitted = time.monotonic()
        queue_wait: dict[str, float] = {}

        def _run_analyzer() -> FallDetailResult:
            queue_wait["vlm_queue_wait_ms"] = round((time.monotonic() - submitted) * 1000, 3)
            return self.analyzer.analyze_fall_event(event, keyframes)

        future = self._executor.submit(_run_analyzer)
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
                failure_reason="timeout",
                prompt_version=POST_FALL_PROMPT_VERSION,
                schema_version=POST_FALL_SCHEMA_VERSION,
                fusion_version=FUSION_VERSION,
            )
        except Exception as exc:
            with self._lock:
                self.failure_count += 1
            result = FallDetailResult(
                incident_id=event.incident_id,
                analysis_status="failed",
                summary="VLM review failed; binary FallEvent remains valid.",
                error_message=str(exc),
                failure_reason="exception",
                prompt_version=POST_FALL_PROMPT_VERSION,
                schema_version=POST_FALL_SCHEMA_VERSION,
                fusion_version=FUSION_VERSION,
            )
        timing = {**(result.timing or {}), **queue_wait}
        if result.confidence is not None:
            confidence = max(0.0, min(1.0, float(result.confidence)))
            result = FallDetailResult(**{**result.to_record(), "confidence": confidence})
        if not result.model_name:
            result = FallDetailResult(**{**result.to_record(), "model_name": self.analyzer.__class__.__name__})
        latency_ms = int((time.monotonic() - started) * 1000)
        if not result.summary:
            result = FallDetailResult(**{**result.to_record(), "summary": f"VLM review completed in {latency_ms} ms."})
        if result.analysis_status != "completed" and not result.failure_reason:
            result = FallDetailResult(**{**result.to_record(), "failure_reason": result.error_message or result.analysis_status})
        result = FallDetailResult(
            **{
                **result.to_record(),
                "fusion_version": result.fusion_version or FUSION_VERSION,
                "timing": {**timing, "vlm_total_service_ms": round((time.monotonic() - started) * 1000, 3)},
            }
        )
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
        failure_reason=reason,
        prompt_version=POST_FALL_PROMPT_VERSION,
        schema_version=POST_FALL_SCHEMA_VERSION,
        fusion_version=FUSION_VERSION,
    )


def build_competition_decision(
    *,
    detail: FallDetailResult | None,
    binary_probability: float | None,
    persistent_strong_candidate: bool,
    candidate_alert_active: bool = False,
) -> dict[str, object]:
    description = _description(detail, candidate_alert_active)
    confidence = _confidence(detail, binary_probability)
    activity = _activity(detail)
    if detail is None:
        return {
            "last_frame_description": description,
            "is_true_fall": False,
            "activity": activity,
            "confidence": confidence,
            "decision_source": "binary_candidate" if candidate_alert_active else "binary_monitor",
        }
    if detail.analysis_status != "completed":
        decision = {
            "last_frame_description": description,
            "is_true_fall": True,
            "activity": activity,
            "confidence": confidence,
            "decision_source": "vlm_failure_fallback",
            "failure_reason": detail.failure_reason or detail.error_message or detail.analysis_status,
        }
        return decision

    visible_distress = (detail.visible_distress or "unclear").strip().lower()
    vlm_flag = detail.vlm_is_true_fall
    posture_state = (detail.posture_state or "unclear").strip().lower()

    if activity in {"confirmed_fall", "possible_fall_or_distress"}:
        return _decision(description, True, activity, confidence, "vlm_semantic_review")
    if activity == "uncertain":
        return _decision(description, True, activity, confidence, "uncertain_fallback")

    clear_phone = activity == "lying_using_phone" and _at_least(confidence, 0.80) and visible_distress == "no" and vlm_flag is False
    clear_reading = activity == "lying_reading" and _at_least(confidence, 0.80) and visible_distress == "no" and vlm_flag is False
    clear_normal = (
        activity == "normal_activity"
        and _at_least(confidence, 0.90)
        and visible_distress == "no"
        and posture_state != "unclear"
        and vlm_flag is False
        and not persistent_strong_candidate
    )
    if clear_phone or clear_reading or clear_normal:
        return _decision(description, False, activity, confidence, "vlm_semantic_review")
    if persistent_strong_candidate:
        return _decision(description, True, activity, confidence, "detector_safety_override")
    return _decision(description, True, activity, confidence, "uncertain_fallback")


def _decision(
    description: str,
    is_true_fall: bool,
    activity: str,
    confidence: float | None,
    source: str,
) -> dict[str, object]:
    return {
        "last_frame_description": description,
        "is_true_fall": is_true_fall,
        "activity": activity,
        "confidence": confidence,
        "decision_source": source,
    }


def _description(detail: FallDetailResult | None, candidate_alert_active: bool) -> str:
    if detail is not None:
        text = (detail.last_frame_description or detail.summary or detail.posture or "").strip()
        if text:
            return text[:120]
    if candidate_alert_active:
        return "小模型已触发跌倒候选，等待本地千问复核。"
    return "未触发跌倒候选。"


def _activity(detail: FallDetailResult | None) -> str:
    if detail is None:
        return "unknown"
    value = (detail.activity or detail.fall_verdict or detail.scene_type or "unknown").strip()
    return value or "unknown"


def _confidence(detail: FallDetailResult | None, binary_probability: float | None) -> float | None:
    value: Any = detail.confidence if detail is not None else binary_probability
    if value is None:
        return None
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold
