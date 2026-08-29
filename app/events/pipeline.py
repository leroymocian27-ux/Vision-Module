from __future__ import annotations

import threading
from typing import Any

from app.camera.frame_buffer import FramePacket
from app.core.config import Settings
from app.core.logger import get_logger
from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.archive import EventArchive
from app.events.delivery import DeliveryOutbox
from app.events.evidence import EvidencePackageBuilder
from app.events.incident_manager import IncidentManager
from app.events.outbox import EventOutbox, SQLiteEventOutbox
from app.events.qwen_keyframe import QwenKeyframeAnalyzer
from app.events.qwen_keyframe_worker import QwenKeyframeWorker
from app.events.ring_frame_buffer import DEFAULT_EVENT_KEYFRAME_OFFSETS_MS, RingFrameBuffer
from app.events.semantic_builder import EventSemanticBuilder
from app.events.schemas import EventOutboxRecord, FallEventRecord
from app.events.vlm_adapter import EventVLMAdapter
from app.schemas.vision_result import VisionResult

logger = get_logger(__name__)
_EVENT_STATES = {"fallen_candidate", "fallen_confirmed", "confirmed_fall", "suspected_post_fall"}
_RISK_LEVELS = {"low", "medium", "high", "critical"}


class EventPipelineService:
    """Feature-flagged asynchronous event path independent of realtime fusion."""

    def __init__(self, settings: Settings, *, qwen_keyframe_analyzer: QwenKeyframeAnalyzer | None = None) -> None:
        self.settings = settings
        self.incidents = IncidentManager(cooldown_window_seconds=settings.event_incident_cooldown_seconds)
        self.outbox = (
            SQLiteEventOutbox(settings.event_outbox_sqlite_path)
            if settings.event_outbox_backend == "sqlite"
            else EventOutbox()
        )
        self.ring_buffer = RingFrameBuffer(
            window_seconds=settings.event_ring_buffer_seconds,
            max_frames_per_camera=settings.event_ring_buffer_max_frames,
            max_bytes_per_camera=settings.event_ring_buffer_max_bytes,
        )
        self.evidence_builder = EvidencePackageBuilder()
        self.semantic_builder = EventSemanticBuilder()
        self.vlm_adapter = EventVLMAdapter.from_settings(settings)
        self.analysis_engine = IntelligentAnalysisEngine(vlm_analyzer=self.vlm_adapter)
        self.archive = EventArchive(
            settings.event_archive_dir,
            enabled=settings.event_archive_enabled,
            save_keyframes=settings.event_archive_save_keyframes,
            save_json=settings.event_archive_save_json,
            max_events_per_camera=settings.event_archive_max_events_per_camera,
            retention_days=settings.event_archive_retention_days,
        )
        self.delivery_outbox = DeliveryOutbox(settings)
        self.qwen_keyframe_worker = self._build_qwen_keyframe_worker(qwen_keyframe_analyzer)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._post_keyframe_timers: dict[str, threading.Timer] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.event_pipeline_enabled)

    @property
    def ring_buffer_enabled(self) -> bool:
        return self.enabled and bool(self.settings.event_ring_buffer_enabled)

    def start(self) -> None:
        if not self.enabled or not self.settings.event_worker_enabled:
            return
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._recover_qwen_jobs()
        self._worker = threading.Thread(target=self._run, name="event-pipeline-worker", daemon=True)
        self._worker.start()
        logger.info("event_pipeline_worker_started")

    def stop(self) -> None:
        self._stop.set()
        for timer in self._post_keyframe_timers.values():
            timer.cancel()
        self._post_keyframe_timers.clear()
        if self.qwen_keyframe_worker is not None:
            self.qwen_keyframe_worker.stop()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=3)

    def record_frame_packet(self, packet: FramePacket) -> None:
        if not self.ring_buffer_enabled:
            return
        try:
            self.ring_buffer.add_frame(packet.camera_id, packet.seq, packet.captured_at_iso, packet.frame)
        except Exception:
            # Evidence capture is advisory and must never interfere with capture.
            logger.exception("event_ring_buffer_record_failed camera_id=%s", packet.camera_id)

    def observe_result(self, result: VisionResult) -> list[EventOutboxRecord]:
        if not self.enabled:
            return []
        records: list[EventOutboxRecord] = []
        for obj in result.objects:
            decision = obj.fall_decision if isinstance(obj.fall_decision, dict) else {}
            fall_state = str(decision.get("fall_state") or "").lower()
            if (
                str(decision.get("pipeline") or "").lower() == "post_fall_v2"
                and str(decision.get("safety_outcome") or "").lower() != "alert"
            ):
                # PFV2 delivery is authorized by the deterministic safety state
                # machine, not directly by either binary or Qwen output.
                continue
            if obj.label != "person" or obj.track_id is None or fall_state not in _EVENT_STATES:
                continue
            risk_level = str(decision.get("risk_level") or "medium").lower()
            if risk_level not in _RISK_LEVELS:
                risk_level = "medium"
            resolution = self.incidents.resolve(
                camera_id=result.camera_id,
                stream_name="primary",
                track_id=obj.track_id,
                person_id=obj.person_id,
                fall_state=fall_state,
                risk_level=risk_level,  # type: ignore[arg-type]
                timestamp=result.timestamp,
                trigger_frame_seq=result.frame_seq,
                bbox=list(obj.bbox),
                risk_score=_score(decision, obj),
                fall_probability=_number((obj.temporal or {}).get("fall_probability")),
                fall_evidence_score=_number(decision.get("fall_evidence_score")),
                adl_suppression_score=_number(decision.get("adl_suppression_score")),
                metadata={
                    "features": obj.features or {},
                    "temporal": obj.temporal or {},
                    "pose": obj.pose or {},
                    "fusion_debug": obj.fusion_debug or {},
                    "decision_reason": decision.get("reason") or decision.get("suppressed_reason"),
                },
            )
            records.append(self.outbox.add_event(resolution.record))
        return records

    def process_once(self, worker_id: str = "event-worker") -> EventOutboxRecord | None:
        if not self.enabled:
            return None
        claimed = self.outbox.claim_next(worker_id, self.settings.event_worker_lock_ttl_seconds)
        if claimed is None:
            return None
        try:
            event = claimed.event
            selections = self.ring_buffer.extract_event_keyframes(
                event.camera_id,
                event.trigger_timestamp,
                self.settings.event_keyframe_offsets_ms,
            )
            metadata = event.metadata if isinstance(event.metadata, dict) else {}
            evidence = self.evidence_builder.build(
                event,
                selections,
                feature_json=_as_dict(metadata.get("features")),
                fusion_debug=_as_dict(metadata.get("fusion_debug")),
                pose_quality=_as_text(_as_dict(metadata.get("pose")).get("pose_quality_level")),
                decision_reason=_as_text(metadata.get("decision_reason")),
            )
            self.outbox.mark_evidence_ready(event.incident_id, evidence)
            if not self.settings.event_semantic_enabled:
                try:
                    archive = self.archive.archive(evidence, selections, None, None)
                    if archive is not None:
                        self.outbox.mark_evidence_ready(event.incident_id, archive.evidence)
                        self.outbox.mark_archive(event.incident_id, archive.archive_path, archive.summary)
                        self._schedule_qwen_keyframe_analysis(event.incident_id)
                except Exception:
                    logger.exception("event_archive_failed incident_id=%s", event.incident_id)
                return self.outbox.get_event(event.incident_id)
            semantics = self.semantic_builder.build(
                event,
                evidence,
                features=_as_dict(metadata.get("features")),
                temporal=_as_dict(metadata.get("temporal")),
                pose=_as_dict(metadata.get("pose")),
                fusion_debug=_as_dict(metadata.get("fusion_debug")),
            )
            self.outbox.mark_semantic_ready(event.incident_id, semantics)
            trusted = self.analysis_engine.analyze(semantics, evidence)
            self.outbox.mark_reviewed(event.incident_id, trusted)
            try:
                archive = self.archive.archive(evidence, selections, semantics, trusted)
                if archive is not None:
                    self.outbox.mark_evidence_ready(event.incident_id, archive.evidence)
                    summary = dict(archive.summary)
                    if self.settings.event_post_keyframe_collection_enabled:
                        summary["evidence_status"] = "collecting"
                    self.outbox.mark_archive(event.incident_id, archive.archive_path, summary)
                    self._schedule_post_keyframe_collection(event.incident_id)
                    if not self.settings.event_post_keyframe_collection_enabled:
                        self._schedule_qwen_keyframe_analysis(event.incident_id)
            except Exception:
                logger.exception("event_archive_failed incident_id=%s", event.incident_id)
            pending = self.outbox.mark_delivery_pending(event.incident_id)
            if not self.delivery_outbox.enabled:
                return pending
            delivery = self.delivery_outbox.enqueue(trusted, pending.evidence_package or evidence, semantics)
            outcome = self.delivery_outbox.deliver(delivery.delivery_id)
            if outcome is not None and outcome.delivery_status == "sent":
                return self.outbox.mark_sent(event.incident_id)
            if outcome is not None and outcome.delivery_status in {"retry", "failed"}:
                return self.outbox.mark_retry(event.incident_id, outcome.last_error or outcome.delivery_status, outcome.next_retry_at)
            return pending
        except Exception as exc:
            logger.exception("event_pipeline_processing_failed incident_id=%s", claimed.incident_id)
            return self.outbox.mark_retry(claimed.incident_id, str(exc))

    def status(self) -> dict[str, Any]:
        records = self.outbox.records()
        counts = self.outbox.stats()
        return {
            "enabled": self.enabled,
            "ring_buffer_enabled": self.ring_buffer_enabled,
            "worker_enabled": bool(self.settings.event_worker_enabled),
            "semantic_enabled": bool(self.settings.event_semantic_enabled),
            "vlm_enabled": bool(self.settings.event_vlm_enabled),
            "qwen_keyframe_analysis_enabled": bool(self.qwen_keyframe_worker is not None),
            "qwen_keyframe_worker": self.qwen_keyframe_worker.status() if self.qwen_keyframe_worker is not None else {"running": False, "queued_or_running": 0},
            "outbox_backend": self.settings.event_outbox_backend,
            "worker_running": bool(self._worker and self._worker.is_alive()),
            "outbox_count": len(records),
            "outbox_statuses": {status: sum(item.status == status for item in records) for status in {item.status for item in records}},
            "pending_count": counts.get("pending", 0),
            "processing_count": counts.get("processing", 0),
            "reviewed_count": counts.get("reviewed", 0),
            "failed_count": counts.get("failed", 0),
        }

    def _schedule_post_keyframe_collection(self, incident_id: str) -> None:
        if not self.settings.event_post_keyframe_collection_enabled:
            return
        existing = self._post_keyframe_timers.pop(incident_id, None)
        if existing is not None:
            existing.cancel()
        timer = threading.Timer(
            max(0.0, float(self.settings.event_post_keyframe_window_seconds)),
            self._collect_post_keyframes,
            args=(incident_id,),
        )
        timer.daemon = True
        self._post_keyframe_timers[incident_id] = timer
        timer.start()

    def _collect_post_keyframes(self, incident_id: str) -> None:
        self._post_keyframe_timers.pop(incident_id, None)
        if self._stop.is_set() or not self.settings.event_post_keyframe_collection_enabled:
            return
        record = self.outbox.get_event(incident_id)
        if record is None or record.evidence_package is None:
            return
        try:
            event = record.event
            selections = self.ring_buffer.extract_event_keyframes(
                event.camera_id, event.trigger_timestamp, self.settings.event_keyframe_offsets_ms,
            )
            metadata = event.metadata if isinstance(event.metadata, dict) else {}
            evidence = self.evidence_builder.build(
                event, selections,
                feature_json=_as_dict(metadata.get("features")),
                fusion_debug=_as_dict(metadata.get("fusion_debug")),
                pose_quality=_as_text(_as_dict(metadata.get("pose")).get("pose_quality_level")),
                decision_reason=_as_text(metadata.get("decision_reason")),
            )
            archive = self.archive.archive(evidence, selections, record.event_semantics, record.trusted_result)
            archived_evidence = archive.evidence if archive is not None else evidence
            self.outbox.mark_evidence_ready(incident_id, archived_evidence)
            missing = sum(1 for item in archived_evidence.keyframes if item.missing_reason)
            summary = dict(archive.summary if archive is not None else record.archive_summary)
            summary["evidence_status"] = "complete" if missing == 0 else "degraded"
            summary["keyframes_missing"] = missing
            if archive is not None:
                self.outbox.mark_archive(incident_id, archive.archive_path, summary)
            else:
                self.outbox.mark_archive(incident_id, record.archive_path or "", summary)
            self._schedule_qwen_keyframe_analysis(incident_id)
        except Exception:
            logger.exception("event_post_keyframe_collection_failed incident_id=%s", incident_id)

    def _build_qwen_keyframe_worker(self, analyzer: QwenKeyframeAnalyzer | None) -> QwenKeyframeWorker | None:
        if not self.settings.event_qwen_keyframe_analysis_enabled:
            return None
        local_analyzer = analyzer or QwenKeyframeAnalyzer(
            endpoint_url=self.settings.event_qwen_keyframe_endpoint,
            model_name=self.settings.event_qwen_keyframe_model,
            timeout_seconds=self.settings.event_qwen_keyframe_timeout_seconds,
        )
        return QwenKeyframeWorker(
            analyzer=local_analyzer,
            archive=self.archive,
            max_images=self.settings.event_qwen_keyframe_max_images,
            max_image_bytes=self.settings.event_qwen_keyframe_max_image_bytes,
            update=self.outbox.mark_qwen_advisory,
        )

    def _schedule_qwen_keyframe_analysis(self, incident_id: str) -> None:
        if self.qwen_keyframe_worker is None:
            return
        record = self.outbox.get_event(incident_id)
        if record is None:
            return
        if record.event.event_type != "fallen_confirmed" and not self.settings.event_qwen_keyframe_analyze_candidates:
            return
        self.qwen_keyframe_worker.schedule(record)

    def _recover_qwen_jobs(self) -> None:
        if self.qwen_keyframe_worker is None:
            return
        for record in self.outbox.records():
            advisory = record.qwen_advisory
            if advisory is not None and advisory.analysis_status in {"pending", "processing"}:
                self.qwen_keyframe_worker.schedule(record.model_copy(update={"qwen_advisory": None}))

    def _run(self) -> None:
        while not self._stop.wait(0.1):
            self.process_once()
        logger.info("event_pipeline_worker_stopped")


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _score(decision: dict[str, Any], obj) -> float | None:
    return _number(
        decision.get("fall_probability")
        or decision.get("fall_evidence_score")
        or (obj.alarm_preview or {}).get("fall_probability")
    )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None
