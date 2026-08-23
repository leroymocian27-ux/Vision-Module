from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from app.camera.source_manager import CameraSourceManager
from app.core.config import Settings
from app.core.logger import get_logger
from app.detection.realtime_result_store import RealtimeResultStore
from app.events.pipeline import EventPipelineService
from app.events.schemas import FallEventRecord
from app.post_fall_v2.binary_decision_aggregator import (
    BinaryDecisionAggregator,
    BinaryDecisionAggregatorConfig,
)
from app.post_fall_v2.fall_binary_classifier_service import FallBinaryClassifierService
from app.post_fall_v2.frame_sampler_service import FrameSamplerService
from app.post_fall_v2.keyframe_collection_session import KeyframeCollectionSession
from app.post_fall_v2.keyframe_package_service import KeyframePackageService
from app.post_fall_v2.rolling_event_buffer import RollingEventBuffer
from app.post_fall_v2.schemas import (
    FULL_FRAME_TRAIN_MATCHED,
    BinaryAggregateDecision,
    BinaryFrameResult,
    FallDetailResult,
    FallEvent,
    KeyframePackage,
    SampledFrame,
)
from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.vlm_review_service import VLMReviewService
from app.schemas.vision_result import DetectedObject, VisionResult
from app.streaming.result_channel_manager import ResultChannelManager

logger = get_logger(__name__)


@dataclass
class _RuntimeState:
    sampler_thread: threading.Thread
    worker_thread: threading.Thread
    stop_event: threading.Event
    queue: queue.Queue[SampledFrame]
    sampler: FrameSamplerService
    frames_sampled: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    frames_invalid: int = 0
    last_probability: float | None = None
    last_label: str | None = None
    last_inference_at: str | None = None
    last_error: str | None = None


class PostFallV2RuntimeService:
    """Formal Binary-First runtime chain for PIPELINE_MODE=post_fall_v2."""

    def __init__(
        self,
        *,
        settings: Settings,
        source_manager: CameraSourceManager,
        realtime_store: RealtimeResultStore,
        result_channels: ResultChannelManager,
        event_pipeline: EventPipelineService | None = None,
        vlm_review_service: VLMReviewService | None = None,
        classifier: FallBinaryClassifierService | None = None,
    ) -> None:
        self.settings = settings
        self.source_manager = source_manager
        self.realtime_store = realtime_store
        self.result_channels = result_channels
        self.event_pipeline = event_pipeline
        self.enabled = bool(settings.post_fall_v2_enabled)
        self._classifier = classifier
        self._classifier_error: str | None = None
        self._aggregator = BinaryDecisionAggregator(
            BinaryDecisionAggregatorConfig(
                threshold=settings.post_fall_v2_binary_threshold,
                window_size=settings.post_fall_v2_window_size,
                min_positive_frames=settings.post_fall_v2_min_positive_frames,
                min_consecutive_frames=settings.post_fall_v2_min_consecutive_frames,
                candidate_min_ms=settings.post_fall_v2_candidate_min_ms,
                recovery_min_ms=settings.post_fall_v2_recovery_min_ms,
                cooldown_ms=settings.post_fall_v2_cooldown_ms,
            )
        )
        self._event_buffer = RollingEventBuffer(
            window_seconds=settings.post_fall_v2_event_buffer_seconds,
            max_frames_per_camera=max(16, int(settings.post_fall_v2_event_buffer_seconds * settings.post_fall_v2_sample_fps * 2)),
        )
        self._keyframes = KeyframePackageService(
            offsets_ms=settings.event_keyframe_offsets_ms,
            tolerance_ms=settings.post_fall_v2_keyframe_tolerance_ms,
        )
        self._vlm = vlm_review_service or VLMReviewService(
            enabled=settings.post_fall_v2_vlm_enabled,
            timeout_seconds=settings.post_fall_v2_vlm_timeout_seconds,
        )
        self._states: dict[str, _RuntimeState] = {}
        self._events: dict[str, FallEvent] = {}
        self._vlm_threads: dict[str, threading.Thread] = {}
        self._keyframe_sessions: dict[str, KeyframeCollectionSession] = {}
        self._keyframe_threads: dict[str, threading.Thread] = {}
        self._keyframe_stops: dict[str, threading.Event] = {}
        self._keyframe_statuses: dict[str, dict] = {}
        self._qwen_media: dict[str, tuple[list[QwenImageInput], list[str]]] = {}
        self._vlm_submitted: set[str] = set()
        self._vlm_finished: set[str] = set()
        self._lock = threading.Lock()
        if self.enabled and self._classifier is None:
            self._load_classifier_safely()

    def start_for_camera(self, camera_id: str) -> None:
        if not self.enabled or self._classifier is None:
            return
        with self._lock:
            existing = self._states.get(camera_id)
            if existing and existing.worker_thread.is_alive():
                return
            stop_event = threading.Event()
            frame_queue: queue.Queue[SampledFrame] = queue.Queue(maxsize=max(1, self.settings.post_fall_v2_queue_size))
            sampler = FrameSamplerService(
                sample_fps=self.settings.post_fall_v2_sample_fps,
                max_frame_age_ms=self.settings.post_fall_v2_max_frame_age_ms,
            )
            state = _RuntimeState(
                sampler_thread=threading.Thread(
                    target=self._sample_loop,
                    args=(camera_id, stop_event, frame_queue, sampler),
                    name=f"post-fall-v2-runtime-sampler-{camera_id}",
                    daemon=True,
                ),
                worker_thread=threading.Thread(
                    target=self._worker_loop,
                    args=(camera_id, stop_event, frame_queue),
                    name=f"post-fall-v2-runtime-worker-{camera_id}",
                    daemon=True,
                ),
                stop_event=stop_event,
                queue=frame_queue,
                sampler=sampler,
            )
            self._states[camera_id] = state
            state.sampler_thread.start()
            state.worker_thread.start()
        logger.info("post_fall_v2_runtime_started camera_id=%s", camera_id)

    def stop_for_camera(self, camera_id: str) -> None:
        with self._lock:
            state = self._states.pop(camera_id, None)
        if state is None:
            return
        state.stop_event.set()
        self._cancel_keyframe_sessions(camera_id)
        for worker in (state.sampler_thread, state.worker_thread):
            if worker.is_alive():
                worker.join(timeout=3)
        self._event_buffer.clear(camera_id)
        self._aggregator.reset(camera_id)
        logger.info("post_fall_v2_runtime_stopped camera_id=%s", camera_id)

    def stop_all(self) -> None:
        for camera_id in list(self._states.keys()):
            self.stop_for_camera(camera_id)
        for stop_event in list(self._keyframe_stops.values()):
            stop_event.set()
        for session in list(self._keyframe_sessions.values()):
            session.cancel()
        for thread in list(self._keyframe_threads.values()):
            if thread.is_alive():
                thread.join(timeout=1)
        for thread in list(self._vlm_threads.values()):
            if thread.is_alive():
                thread.join(timeout=1)
        self._vlm.shutdown()

    def status(self, camera_id: str | None = None) -> dict:
        with self._lock:
            selected = self._states.get(camera_id) if camera_id else next(iter(self._states.values()), None)
            selected_camera_id = camera_id or (next(iter(self._states.keys()), None) if self._states else None)
            active_vlm = sum(1 for thread in self._vlm_threads.values() if thread.is_alive())
            event_count = len(self._events)
            active_collectors = sum(1 for thread in self._keyframe_threads.values() if thread.is_alive())
            latest_incident_id = next(reversed(self._events), None) if self._events else None
            keyframe_status = self._keyframe_statuses.get(latest_incident_id or "", {})
        running = bool(selected and selected.worker_thread.is_alive() and selected.sampler_thread.is_alive())
        return {
            "camera_id": selected_camera_id,
            "pipeline_mode": self.settings.pipeline_mode,
            "enabled": self.enabled,
            "running": running,
            "state": self._aggregator.status(selected_camera_id) if selected_camera_id else "idle",
            "active_incident_id": latest_incident_id,
            "binary_model_loaded": bool(self._classifier and self._classifier.loaded),
            "binary_model_sha256": self._classifier.model_sha256 if self._classifier else None,
            "binary_provider": self._classifier.provider if self._classifier else None,
            "binary_last_inference_at": selected.last_inference_at if selected else None,
            "binary_last_probability": selected.last_probability if selected else None,
            "binary_last_label": selected.last_label if selected else None,
            "sample_fps": self.settings.post_fall_v2_sample_fps,
            "queue_depth": selected.queue.qsize() if selected else 0,
            "frames_sampled": selected.frames_sampled if selected else 0,
            "frames_processed": selected.frames_processed if selected else 0,
            "frames_dropped": selected.frames_dropped if selected else 0,
            "frames_invalid": selected.frames_invalid if selected else 0,
            "vlm_enabled": self._vlm.enabled,
            "vlm_provider": getattr(self.settings, "post_fall_v2_qwen_provider", "dummy"),
            "vlm_model": getattr(self.settings, "post_fall_v2_qwen_model", None),
            "vlm_active_count": active_vlm,
            "vlm_call_count": self._vlm.call_count,
            "vlm_queue_depth": self._vlm.queue_depth,
            "vlm_queue_capacity": getattr(self._vlm, "_queue_capacity", None),
            "vlm_rejected_count": self._vlm.rejected_count,
            "vlm_submitted_count": len(self._vlm_submitted),
            "vlm_finished_count": len(self._vlm_finished),
            "keyframe_collection_active_count": active_collectors,
            "keyframe_collection_status": keyframe_status,
            "event_count": event_count,
            "last_error": self._classifier_error or (selected.last_error if selected else None),
        }

    def latest_event(self, incident_id: str) -> FallEvent | None:
        with self._lock:
            return self._events.get(incident_id)

    def events(self) -> list[FallEvent]:
        with self._lock:
            return list(self._events.values())

    def qwen_images_for_incident(self, incident_id: str) -> tuple[list[QwenImageInput], list[str]]:
        with self._lock:
            images, missing = self._qwen_media.get(incident_id, ([], ["qwen_media_not_available"]))
        return list(images), list(missing)

    def _sample_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
        sampler: FrameSamplerService,
    ) -> None:
        tick_interval = min(0.05, 1.0 / max(self.settings.post_fall_v2_sample_fps * 4, 1.0))
        while not stop_event.is_set():
            try:
                buffer = self.source_manager.get_buffer(camera_id)
                decision = sampler.try_sample(buffer.latest() if buffer else None)
                if decision.sampled is not None:
                    buffered = self._event_buffer.add_sampled_frame(decision.sampled)
                    self._observe_keyframe_sessions(buffered)
                    self._put_latest(camera_id, frame_queue, decision.sampled)
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_runtime_sampler_error camera_id=%s", camera_id)
            stop_event.wait(tick_interval)

    def _worker_loop(
        self,
        camera_id: str,
        stop_event: threading.Event,
        frame_queue: queue.Queue[SampledFrame],
    ) -> None:
        while not stop_event.is_set():
            try:
                sampled = frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                classifier = self._classifier
                if classifier is None:
                    self._set_error(camera_id, "classifier unavailable")
                    continue
                raw = classifier.infer(sampled)
                binary = BinaryFrameResult.from_classifier_result(raw)
                binary = BinaryFrameResult(**{**binary.to_record(), "frame_seq": sampled.frame_seq})
                aggregate = self._aggregator.update(binary)
                self._update_state(camera_id, binary)
                event = self._maybe_create_event(aggregate, sampled)
                self._publish(binary, aggregate, event)
            except Exception as exc:
                self._set_error(camera_id, str(exc))
                logger.exception("post_fall_v2_runtime_worker_error camera_id=%s", camera_id)

    def _maybe_create_event(self, decision: BinaryAggregateDecision, sampled: SampledFrame) -> FallEvent | None:
        if not decision.event_created or not decision.incident_id:
            return None
        session = self._new_keyframe_session(decision, sampled)
        session.prime_buffer(self._event_buffer.window(decision.camera_id))
        keyframes = replace(
            session.build_package(now_monotonic=sampled.captured_monotonic),
            fall_probability_summary=decision.evidence.to_record(),
        )
        collect_keyframes = self._vlm.enabled and self.settings.post_fall_v2_keyframe_post_collection_enabled
        event = FallEvent(
            incident_id=decision.incident_id,
            camera_id=decision.camera_id,
            state="fall_confirmed",
            started_at=decision.updated_at,
            confirmed_at=decision.updated_at,
            binary_evidence=decision.evidence.to_record(),
            keyframes=keyframes,
            vlm_status="collecting_keyframes" if collect_keyframes else ("pending" if self._vlm.enabled else "disabled"),
        )
        with self._lock:
            self._events[event.incident_id] = event
            self._keyframe_statuses[event.incident_id] = {
                "status": keyframes.status if not collect_keyframes else "collecting",
                "requested_offsets_ms": keyframes.requested_offsets_ms,
                "resolved_offsets_ms": keyframes.resolved_offsets_ms,
                "missing_offsets_ms": keyframes.missing_offsets_ms,
            }
        self._send_to_event_outbox(event, keyframes)
        if collect_keyframes:
            self._schedule_keyframe_collection(event, session)
        else:
            self._schedule_vlm(event, keyframes)
        logger.info("fall_event_created incident_id=%s camera_id=%s", event.incident_id, event.camera_id)
        return event

    def _new_keyframe_session(self, decision: BinaryAggregateDecision, sampled: SampledFrame) -> KeyframeCollectionSession:
        return KeyframeCollectionSession(
            incident_id=decision.incident_id or "",
            camera_id=decision.camera_id,
            confirmed_monotonic=sampled.captured_monotonic,
            confirmed_at=decision.updated_at,
            required_offsets_ms=self.settings.event_keyframe_offsets_ms,
            tolerance_ms=self.settings.post_fall_v2_keyframe_tolerance_ms,
            collection_window_seconds=self.settings.post_fall_v2_keyframe_collection_timeout_seconds,
            max_observations=max(16, int(self.settings.post_fall_v2_event_buffer_seconds * self.settings.post_fall_v2_sample_fps * 2)),
        )

    def _schedule_keyframe_collection(self, event: FallEvent, session: KeyframeCollectionSession) -> None:
        with self._lock:
            existing = self._keyframe_threads.get(event.incident_id)
            if existing and existing.is_alive():
                return
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run_keyframe_collection,
                args=(event.incident_id, stop_event),
                name=f"post-fall-v2-keyframes-{event.incident_id}",
                daemon=True,
            )
            self._keyframe_sessions[event.incident_id] = session
            self._keyframe_stops[event.incident_id] = stop_event
            self._keyframe_threads[event.incident_id] = thread
            thread.start()
        logger.info("keyframe_collection_started incident_id=%s", event.incident_id)

    def _run_keyframe_collection(self, incident_id: str, stop_event: threading.Event) -> None:
        try:
            while not stop_event.wait(0.05):
                with self._lock:
                    session = self._keyframe_sessions.get(incident_id)
                if session is None:
                    return
                snapshot = session.snapshot()
                with self._lock:
                    self._keyframe_statuses[incident_id] = snapshot.to_record()
                if snapshot.status in {"ready", "degraded", "expired", "cancelled"}:
                    break
            with self._lock:
                session = self._keyframe_sessions.get(incident_id)
            if stop_event.is_set() or (session is not None and session.status() == "cancelled"):
                with self._lock:
                    if session is not None:
                        self._keyframe_statuses[incident_id] = session.snapshot().to_record()
                    self._keyframe_sessions.pop(incident_id, None)
                return
            self._complete_keyframe_collection(incident_id)
        except Exception:
            logger.exception("keyframe_collection_failed incident_id=%s", incident_id)
            self._complete_keyframe_collection(incident_id, forced_error="keyframe_collection_failed")
        finally:
            with self._lock:
                self._keyframe_threads.pop(incident_id, None)
                self._keyframe_stops.pop(incident_id, None)

    def _complete_keyframe_collection(self, incident_id: str, forced_error: str | None = None) -> None:
        with self._lock:
            session = self._keyframe_sessions.pop(incident_id, None)
            event = self._events.get(incident_id)
        if session is None or event is None:
            return
        package = replace(session.build_package(), fall_probability_summary=event.binary_evidence)
        images, missing = session.export_qwen_images(
            max_images=self.settings.post_fall_v2_qwen_max_images,
            max_image_bytes=self.settings.post_fall_v2_qwen_max_image_bytes,
            max_edge=self.settings.post_fall_v2_qwen_image_max_edge,
            jpeg_quality=self.settings.post_fall_v2_qwen_jpeg_quality,
        )
        session.release_media()
        if forced_error:
            missing = list(dict.fromkeys([*missing, forced_error]))
        with self._lock:
            self._qwen_media[incident_id] = (images, missing)
            latest = self._events.get(incident_id, event)
            updated = replace(
                latest,
                keyframes=package,
                vlm_status="pending" if self._vlm.enabled else "disabled",
            )
            self._events[incident_id] = updated
            self._keyframe_statuses[incident_id] = {
                "status": package.status,
                "requested_offsets_ms": package.requested_offsets_ms,
                "resolved_offsets_ms": package.resolved_offsets_ms,
                "missing_offsets_ms": package.missing_offsets_ms,
                "missing_reasons": missing,
            }
        self._send_to_event_outbox(updated, package)
        self._publish_vlm_update(updated)
        self._schedule_vlm(updated, package)

    def _observe_keyframe_sessions(self, buffered) -> None:
        with self._lock:
            sessions = list(self._keyframe_sessions.values())
        for session in sessions:
            session.observe_buffered_frame(buffered)

    def _schedule_vlm(self, event: FallEvent, keyframes: KeyframePackage) -> None:
        if not self._vlm.enabled:
            return
        with self._lock:
            if event.incident_id in self._vlm_submitted:
                return
            existing = self._vlm_threads.get(event.incident_id)
            if existing and existing.is_alive():
                return
            self._vlm_submitted.add(event.incident_id)
            thread = threading.Thread(
                target=self._run_vlm,
                args=(event.incident_id, keyframes),
                name=f"post-fall-v2-vlm-{event.incident_id}",
                daemon=True,
            )
            self._vlm_threads[event.incident_id] = thread
            self._events[event.incident_id] = replace(event, vlm_status="running")
            thread.start()
        logger.info("vlm_review_started incident_id=%s", event.incident_id)

    def _run_vlm(self, incident_id: str, keyframes: KeyframePackage) -> None:
        with self._lock:
            event = self._events[incident_id]
        detail = self._vlm.analyze_fall_event(event, keyframes)
        with self._lock:
            latest = self._events[incident_id]
            updated = replace(
                latest,
                vlm_status=detail.analysis_status,
                vlm_analysis=detail,
            )
            self._events[incident_id] = updated
            self._qwen_media.pop(incident_id, None)
            self._vlm_finished.add(incident_id)
        self._publish_vlm_update(updated)
        logger.info("vlm_review_finished incident_id=%s status=%s", incident_id, detail.analysis_status)

    def _publish(
        self,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
        event: FallEvent | None,
    ) -> None:
        active_event = event
        if active_event is None and decision.incident_id:
            active_event = self.latest_event(decision.incident_id)
        fall_decision = {
            "pipeline": "post_fall_v2",
            "source": "post_fall_v2_binary",
            "fall_state": decision.fall_state,
            "status": "fallen_confirmed" if decision.fall_state == "confirmed" else decision.fall_state,
            "binary_label": binary.decision_label,
            "fall_probability": binary.fall_probability,
            "non_fall_probability": binary.non_fall_probability,
            "threshold": binary.threshold,
            "incident_id": decision.incident_id,
            "event_created": decision.event_created,
            "reason": decision.reason,
            "evidence": decision.evidence.to_record(),
        }
        if active_event is not None:
            fall_decision["vlm_status"] = active_event.vlm_status
            if active_event.keyframes is not None:
                fall_decision["keyframe_status"] = active_event.keyframes.status
                fall_decision["keyframe_missing_offsets_ms"] = active_event.keyframes.missing_offsets_ms
            if active_event.vlm_analysis is not None:
                fall_decision["vlm_summary"] = active_event.vlm_analysis.summary
            else:
                fall_decision["vlm_summary"] = None
        obj = DetectedObject(
            label="person",
            confidence=1.0,
            bbox=[0.0, 0.0, float(binary.source_width), float(binary.source_height)],
            track_id=0,
            is_target=True,
            temporal={
                "source": "post_fall_v2_binary",
                "fall_probability": binary.fall_probability,
                "window_size": decision.evidence.window_size,
            },
            fall_decision=fall_decision,
            alarm_preview={
                "confirmed": decision.fall_state == "confirmed",
                "risk_level": "high" if decision.fall_state == "confirmed" else "low",
                "fall_probability": binary.fall_probability,
                "source": "post_fall_v2_binary",
            },
        )
        result = VisionResult(
            camera_id=binary.camera_id,
            timestamp=binary.inferred_at,
            frame_seq=binary.frame_seq,
            frame_width=binary.source_width,
            frame_height=binary.source_height,
            objects=[obj],
            detector={
                "pipeline": "post_fall_v2",
                "model": binary.model_name,
                "model_version": binary.model_version,
                "binary_label": binary.decision_label,
                "fall_probability": binary.fall_probability,
                "_monotonic_at": time.monotonic(),
            },
        )
        self.realtime_store.update_published(result)
        self.result_channels.publish(result)

    def _publish_vlm_update(self, event: FallEvent) -> None:
        latest = self.realtime_store.latest_published(event.camera_id)
        if latest is None:
            return
        objects = []
        changed = False
        for obj in latest.objects:
            fall_decision = dict(obj.fall_decision or {})
            if fall_decision.get("incident_id") != event.incident_id:
                objects.append(obj)
                continue
            fall_decision["vlm_status"] = event.vlm_status
            if event.vlm_analysis is not None:
                fall_decision["vlm_summary"] = event.vlm_analysis.summary
            else:
                fall_decision["vlm_summary"] = None
            if event.keyframes is not None:
                fall_decision["keyframe_status"] = event.keyframes.status
                fall_decision["keyframe_missing_offsets_ms"] = event.keyframes.missing_offsets_ms
            objects.append(obj.model_copy(update={"fall_decision": fall_decision}))
            changed = True
        if not changed:
            return
        updated = latest.model_copy(
            update={
                "objects": objects,
                "detector": {
                    **latest.detector,
                    "vlm_status": event.vlm_status,
                    "_monotonic_at": time.monotonic(),
                },
            }
        )
        self.realtime_store.update_published(updated)
        self.result_channels.publish(updated)

    def _send_to_event_outbox(self, event: FallEvent, keyframes: KeyframePackage) -> None:
        if self.event_pipeline is None:
            return
        evidence = event.binary_evidence if isinstance(event.binary_evidence, dict) else {}
        record = FallEventRecord(
            incident_id=event.incident_id,
            camera_id=event.camera_id,
            track_id=0,
            event_type="fallen_confirmed",
            fall_state="fallen_confirmed",
            risk_level="high",
            risk_score=_as_float(evidence.get("max_fall_probability") or evidence.get("mean_fall_probability")),
            trigger_frame_seq=_as_int(evidence.get("frame_seq")),
            trigger_timestamp=event.confirmed_at,
            bbox=None,
            fall_probability=_as_float(evidence.get("fall_probability") or evidence.get("max_fall_probability")),
            fall_evidence_score=_as_float(evidence.get("max_fall_probability")),
            metadata={
                "pipeline": "post_fall_v2",
                "binary_evidence": event.binary_evidence,
                "keyframes": keyframes.to_record(),
            },
        )
        try:
            self.event_pipeline.outbox.add_event(record)
        except Exception:
            logger.exception("post_fall_v2_event_outbox_add_failed incident_id=%s", event.incident_id)

    def _cancel_keyframe_sessions(self, camera_id: str) -> None:
        with self._lock:
            sessions = [
                (incident_id, session, self._keyframe_stops.get(incident_id), self._keyframe_threads.get(incident_id))
                for incident_id, session in self._keyframe_sessions.items()
                if session.camera_id == camera_id
            ]
        for incident_id, session, stop_event, thread in sessions:
            if stop_event is not None:
                stop_event.set()
            session.cancel()
            if thread is not None and thread.is_alive():
                thread.join(timeout=1)
            with self._lock:
                self._keyframe_sessions.pop(incident_id, None)
                self._qwen_media.pop(incident_id, None)

    def _put_latest(self, camera_id: str, frame_queue: queue.Queue[SampledFrame], sampled: SampledFrame) -> None:
        dropped = 0
        while frame_queue.full():
            try:
                frame_queue.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        try:
            frame_queue.put_nowait(sampled)
        except queue.Full:
            dropped += 1
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.frames_sampled += 1
                state.frames_dropped += dropped

    def _update_state(self, camera_id: str, binary: BinaryFrameResult) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return
            state.frames_processed += 1
            state.last_probability = binary.fall_probability
            state.last_label = binary.decision_label
            state.last_inference_at = binary.inferred_at
            if not binary.valid:
                state.frames_invalid += 1
                state.last_error = binary.error_message
            else:
                state.last_error = None

    def _set_error(self, camera_id: str, message: str) -> None:
        with self._lock:
            state = self._states.get(camera_id)
            if state:
                state.last_error = message

    def _load_classifier_safely(self) -> None:
        if self.settings.post_fall_v2_input_policy != FULL_FRAME_TRAIN_MATCHED:
            self._classifier_error = f"unsupported input policy: {self.settings.post_fall_v2_input_policy}"
            return
        try:
            self._classifier = FallBinaryClassifierService(
                model_path=self._resolve_path(self.settings.post_fall_v2_model_path),
                expected_sha256=self.settings.post_fall_v2_binary_model_sha256,
                threshold=self.settings.post_fall_v2_binary_threshold,
                input_policy=self.settings.post_fall_v2_input_policy,
                providers=[
                    part.strip()
                    for part in self.settings.post_fall_v2_binary_onnx_providers.split(",")
                    if part.strip()
                ],
            )
            self._classifier_error = None
        except Exception as exc:
            self._classifier = None
            self._classifier_error = str(exc)
            logger.exception("post_fall_v2_runtime_classifier_load_failed")

    @staticmethod
    def _resolve_path(path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return Path(__file__).resolve().parents[2] / candidate


def _as_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
