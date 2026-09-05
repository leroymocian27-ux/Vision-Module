from __future__ import annotations

import csv
import json
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.schemas import (
    BinaryAggregateDecision,
    BinaryFrameResult,
    FallEvent,
    KeyframePackage,
)


@dataclass(frozen=True)
class ArchiveStatus:
    running: bool
    test_session_id: str | None
    total_seconds: int
    remaining_seconds: int
    event_root: str
    binary_full_count: int
    binary_other_count: int
    qwen_confirm_count: int
    qwen_deny_count: int
    qwen_review_count: int
    qwen_unresolved_count: int
    tracked_binary_event_ids: list[str]
    state: str = "idle"
    started_at: str | None = None
    running_at: str | None = None
    stopped_at: str | None = None
    finalized_at: str | None = None
    session_dir: str | None = None
    camera_id: str | None = None
    manual_session: bool = False
    failure_stage: str | None = None
    failure_reason: str | None = None
    presentation_result: dict[str, Any] | None = None
    binary_fall_count: int = 0
    binary_non_fall_count: int = 0
    binary_unknown_count: int = 0
    candidate_count: int = 0
    rejection_reasons: dict[str, int] | None = None
    qwen_completed_count: int = 0
    qwen_failed_count: int = 0
    qwen_timeout_count: int = 0
    archive_failed_count: int = 0
    performance_samples_count: int = 0
    latest_performance: dict[str, Any] | None = None


class PostFallTestArchiveService:
    """Sidecar archive for timed PFV2 field tests.

    It observes the real binary and Qwen outputs; it never runs inference.
    """

    def __init__(
        self,
        event_root: str,
        *,
        performance_sample_interval_seconds: float = 1.0,
        drain_timeout_seconds: float = 120.0,
    ) -> None:
        self.event_root = Path(event_root).expanduser()
        self.binary_full_dir = self.event_root / "binary-classification" / "full"
        self.binary_other_dir = self.event_root / "binary-classification" / "other"
        self.qwen_confirm_dir = self.event_root / "qwen" / "confirm"
        self.qwen_deny_dir = self.event_root / "qwen" / "deny"
        self.qwen_review_dir = self.event_root / "qwen" / "review"
        self.test_sessions_dir = self.event_root / "test_sessions"
        self._performance_interval = max(0.5, float(performance_sample_interval_seconds))
        self._drain_timeout_seconds = max(1.0, float(drain_timeout_seconds))
        self._lock = threading.RLock()
        self._state = "idle"
        self._running = False
        self._session_id: str | None = None
        self._started_at: str | None = None
        self._running_at: str | None = None
        self._stopped_at: str | None = None
        self._finalized_at: str | None = None
        self._camera_id: str | None = None
        self._manual_session = False
        self._failure_stage: str | None = None
        self._failure_reason: str | None = None
        self._ends_at_monotonic: float | None = None
        self._drain_deadline_monotonic: float | None = None
        self._total_seconds = 0
        self._binary_full_ids: set[str] = set()
        self._binary_other_count = 0
        self._binary_fall_count = 0
        self._binary_non_fall_count = 0
        self._binary_unknown_count = 0
        self._candidate_count = 0
        self._rejection_reasons: dict[str, int] = {}
        self._qwen_completed_count = 0
        self._qwen_failed_count = 0
        self._qwen_timeout_count = 0
        self._archive_failed_count = 0
        self._qwen_confirm_ids: set[str] = set()
        self._qwen_deny_ids: set[str] = set()
        self._qwen_review_ids: set[str] = set()
        self._qwen_unresolved_ids: set[str] = set()
        self._qwen_requested_ids: set[str] = set()
        self._event_sessions: dict[str, str] = {}
        self._event_created_at: dict[str, str] = {}
        self._qwen_images: dict[str, list[QwenImageInput]] = {}
        self._event_records: dict[str, dict[str, Any]] = {}
        self._session_manifest: dict[str, Any] | None = None
        self._trace_records: list[dict[str, Any]] = []
        self._performance_samples_count = 0
        self._latest_performance: dict[str, Any] | None = None
        self._performance_summary: dict[str, Any] = {}
        self._performance_stop = threading.Event()
        self._performance_thread: threading.Thread | None = None
        self.ensure_directories()

    def ensure_directories(self) -> None:
        for directory in (
            self.binary_full_dir,
            self.binary_other_dir,
            self.qwen_confirm_dir,
            self.qwen_deny_dir,
            self.qwen_review_dir,
            self.test_sessions_dir,
            self.event_root / "system_e2e_tests",
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _session_manifest_path_locked(self) -> Path:
        return self._session_dir_locked() / "SESSION_MANIFEST.json"

    def _trace_path_locked(self) -> Path:
        return self._session_dir_locked() / "TRACE_TIMELINE.jsonl"

    def _summary_path_locked(self) -> Path:
        return self._session_dir_locked() / "SUMMARY.json"

    def _report_path_locked(self) -> Path:
        return self._session_dir_locked() / "TEST_REPORT.md"

    def _build_session_manifest(self, started_at: datetime, total_seconds: int) -> dict[str, Any]:
        session_id = self._session_id or f"test_{started_at.strftime('%Y%m%d_%H%M%S')}"
        session_dir = self.test_sessions_dir / session_id
        return {
            "schema_version": "post_fall_v2_test_session_manifest.v1",
            "test_session_id": session_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "total_seconds": int(total_seconds),
            "manual_session": bool(self._manual_session),
            "camera_id": self._camera_id,
            "event_root": str(self.event_root),
            "session_dir": str(session_dir),
            "paths": {
                "session_summary_json": str(session_dir / "session_summary.json"),
                "summary_json": str(session_dir / "SUMMARY.json"),
                "trace_timeline_jsonl": str(session_dir / "TRACE_TIMELINE.jsonl"),
                "test_report_md": str(session_dir / "TEST_REPORT.md"),
                "events_json": str(session_dir / "events.json"),
                "binary_predictions_csv": str(session_dir / "binary_predictions.csv"),
                "performance_csv": str(session_dir / "performance.csv"),
                "presentation_result_json": str(session_dir / "presentation_result.json"),
                "session_json": str(session_dir / "session.json"),
            },
            "timers": {
                "performance_sample_interval_seconds": self._performance_interval,
                "drain_timeout_seconds": self._drain_timeout_seconds,
            },
            "directories": {
                "binary_full": str(self.binary_full_dir),
                "binary_other": str(self.binary_other_dir),
                "qwen_confirm": str(self.qwen_confirm_dir),
                "qwen_deny": str(self.qwen_deny_dir),
                "qwen_review": str(self.qwen_review_dir),
            },
        }

    def start_test(self, total_seconds: int) -> ArchiveStatus:
        if total_seconds <= 0:
            raise ValueError("test duration must be greater than zero")
        return self._start_session(total_seconds=total_seconds, camera_id=None, manual_session=False)

    def start_manual_session(self, camera_id: str | None = None) -> ArchiveStatus:
        return self._start_session(total_seconds=0, camera_id=camera_id, manual_session=True)

    def mark_running(self) -> ArchiveStatus:
        with self._lock:
            if self._session_id and self._running_at is None:
                self._running_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._append_trace_locked(
                    "session_runtime_ready",
                    {
                        "test_session_id": self._session_id,
                        "running_at": self._running_at,
                    },
                )
                self._write_session_summary_locked()
        return self.status()

    def mark_failed(self, stage: str, reason: str) -> ArchiveStatus:
        with self._lock:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._running = False
            self._ends_at_monotonic = None
            self._stopped_at = self._stopped_at or now
            self._finalized_at = now
            self._state = "failed"
            self._failure_stage = str(stage or "unknown")
            self._failure_reason = str(reason or "unknown failure")
            self._drain_deadline_monotonic = None
            self._stop_performance_monitor_locked()
            self._append_log_locked(f"session_failed stage={self._failure_stage} reason={self._failure_reason}")
            self._append_trace_locked(
                "session_failed",
                {
                    "test_session_id": self._session_id,
                    "stage": self._failure_stage,
                    "reason": self._failure_reason,
                    "finalized_at": self._finalized_at,
                },
            )
            self._write_session_summary_locked()
        return self.status()

    def latest_presentation_result(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._session_id:
                return None
            return self._build_presentation_result_locked()

    def _start_session(
        self,
        *,
        total_seconds: int,
        camera_id: str | None,
        manual_session: bool,
    ) -> ArchiveStatus:
        now = datetime.now(timezone.utc)
        session_id = "test_" + now.strftime("%Y%m%d_%H%M%S")
        with self._lock:
            self._stop_performance_monitor_locked()
            self._state = "running"
            self._running = True
            self._session_id = session_id
            self._started_at = now.isoformat(timespec="seconds")
            self._running_at = None
            self._stopped_at = None
            self._finalized_at = None
            self._camera_id = camera_id
            self._manual_session = bool(manual_session)
            self._failure_stage = None
            self._failure_reason = None
            self._ends_at_monotonic = None if manual_session else time.monotonic() + int(total_seconds)
            self._drain_deadline_monotonic = None
            self._total_seconds = int(total_seconds)
            self._binary_full_ids.clear()
            self._binary_other_count = 0
            self._binary_fall_count = 0
            self._binary_non_fall_count = 0
            self._binary_unknown_count = 0
            self._candidate_count = 0
            self._rejection_reasons.clear()
            self._qwen_completed_count = 0
            self._qwen_failed_count = 0
            self._qwen_timeout_count = 0
            self._archive_failed_count = 0
            self._qwen_confirm_ids.clear()
            self._qwen_deny_ids.clear()
            self._qwen_review_ids.clear()
            self._qwen_unresolved_ids.clear()
            self._qwen_requested_ids.clear()
            self._event_sessions.clear()
            self._event_created_at.clear()
            self._qwen_images.clear()
            self._event_records.clear()
            self._trace_records.clear()
            self._session_manifest = self._build_session_manifest(now, total_seconds)
            self._performance_samples_count = 0
            self._latest_performance = None
            self._performance_summary = {}
            self._initialise_session_files_locked()
            self._start_performance_monitor_locked()
        self.ensure_directories()
        self._write_session_summary()
        self._append_trace_locked(
            "test_started",
            {
                "test_session_id": session_id,
                "started_at": self._started_at,
                "total_seconds": self._total_seconds,
                "manual_session": self._manual_session,
                "camera_id": self._camera_id,
            },
        )
        return self.status()

    def stop_test(self) -> ArchiveStatus:
        with self._lock:
            self._running = False
            self._ends_at_monotonic = None
            self._stopped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._state = "stop_requested"
            if self._qwen_unresolved_ids:
                self._state = "draining"
                self._drain_deadline_monotonic = time.monotonic() + self._drain_timeout_seconds
            else:
                self._state = "completed"
                self._finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._drain_deadline_monotonic = None
            if self._state == "completed":
                self._stop_performance_monitor_locked()
            self._append_log_locked("stop_test_requested")
            self._append_trace_locked(
                "test_stop_requested",
                {
                    "test_session_id": self._session_id,
                    "stopped_at": self._stopped_at,
                    "state": self._state,
                },
            )
        self._write_session_summary()
        return self.status()

    def status(self) -> ArchiveStatus:
        with self._lock:
            self._refresh_locked()
            return ArchiveStatus(
                running=self._running,
                test_session_id=self._session_id,
                total_seconds=self._total_seconds,
                remaining_seconds=self._remaining_seconds_locked(),
                event_root=str(self.event_root),
                state=self._state,
                started_at=self._started_at,
                running_at=self._running_at,
                stopped_at=self._stopped_at,
                finalized_at=self._finalized_at,
                session_dir=str(self._session_dir_locked()) if self._session_id else None,
                camera_id=self._camera_id,
                manual_session=self._manual_session,
                failure_stage=self._failure_stage,
                failure_reason=self._failure_reason,
                presentation_result=self._build_presentation_result_locked() if self._session_id else None,
                binary_full_count=len(self._binary_full_ids),
                binary_other_count=self._binary_other_count,
                qwen_confirm_count=len(self._qwen_confirm_ids),
                qwen_deny_count=len(self._qwen_deny_ids),
                qwen_review_count=len(self._qwen_review_ids),
                qwen_unresolved_count=len(self._qwen_unresolved_ids),
                tracked_binary_event_ids=sorted(self._binary_full_ids),
                binary_fall_count=self._binary_fall_count,
                binary_non_fall_count=self._binary_non_fall_count,
                binary_unknown_count=self._binary_unknown_count,
                candidate_count=self._candidate_count,
                rejection_reasons=dict(self._rejection_reasons),
                qwen_completed_count=self._qwen_completed_count,
                qwen_failed_count=self._qwen_failed_count,
                qwen_timeout_count=self._qwen_timeout_count,
                archive_failed_count=self._archive_failed_count,
                performance_samples_count=self._performance_samples_count,
                latest_performance=dict(self._latest_performance) if self._latest_performance is not None else None,
            )

    def archive_binary_frame(
        self,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
        raw: Any | None = None,
        sampled: Any | None = None,
    ) -> None:
        with self._lock:
            self._refresh_locked()
            if not self._running:
                return
            session_id = self._session_id
            self._observe_binary_prediction_locked(binary, decision)
            self._append_binary_prediction_locked(binary, decision, raw, sampled)
            performance = getattr(raw, "performance", None)
            captured_monotonic = getattr(sampled, "captured_monotonic", None)
            frame_age_ms = None
            if captured_monotonic is not None:
                try:
                    frame_age_ms = round((time.monotonic() - float(captured_monotonic)) * 1000, 2)
                except (TypeError, ValueError):
                    frame_age_ms = None
            self._append_trace_locked(
                "binary_frame",
                {
                    "incident_id": decision.incident_id,
                    "camera_id": binary.camera_id,
                    "frame_id": binary.frame_id,
                    "frame_seq": binary.frame_seq,
                    "decision_label": binary.decision_label,
                    "fall_probability": binary.fall_probability,
                    "aggregate_state": decision.state,
                    "frame_age_ms": frame_age_ms,
                    "queue_delay_ms": getattr(performance, "queue_delay_ms", None),
                    "inference_ms": getattr(performance, "inference_ms", None),
                    "total_ms": getattr(performance, "total_ms", None),
                    "provider": getattr(getattr(raw, "model", None), "provider", None),
                },
            )
            if binary.decision_label != "NON_FALL":
                return
            self._binary_other_count += 1
            index = self._binary_other_count
            self._write_session_events_locked()
            self._write_session_summary_locked()
        payload = {
            "schema_version": "post_fall_v2_test_binary_frame.v1",
            "test_session_id": session_id,
            "created_during_test": True,
            "stage": "binary_frame",
            "decision": "NON_FALL",
            "binary": binary.to_record(),
            "aggregate": decision.to_record(),
        }
        filename = f"{_safe_name(binary.camera_id)}_{index:06d}_frame_{binary.frame_seq}.json"
        _write_json(self.binary_other_dir / filename, payload)

    def archive_binary_event(
        self,
        event: FallEvent,
        package: KeyframePackage,
        images: list[QwenImageInput],
        missing_reasons: list[str] | None = None,
    ) -> bool:
        with self._lock:
            self._refresh_locked()
            if not self._running and event.incident_id not in self._event_sessions:
                return False
            session_id = self._event_sessions.setdefault(event.incident_id, self._session_id or "test_unknown")
            self._event_created_at.setdefault(event.incident_id, event.created_at)
            self._binary_full_ids.add(event.incident_id)
            if event.vlm_status != "disabled":
                self._qwen_requested_ids.add(event.incident_id)
            if event.vlm_status in {"collecting_keyframes", "pending", "running"}:
                self._qwen_unresolved_ids.add(event.incident_id)
            self._qwen_images[event.incident_id] = list(images)
            self._event_records[event.incident_id] = self._event_payload_locked(
                event,
                package,
                "binary_full",
                list(missing_reasons or []),
            )
            self._append_trace_locked(
                "binary_event",
                {
                    "incident_id": event.incident_id,
                    "camera_id": event.camera_id,
                    "event_created_at": event.created_at,
                    "confirmed_at": event.confirmed_at,
                    "vlm_status": event.vlm_status,
                    "candidate_duration_ms": event.binary_evidence.get("candidate_duration_ms") if isinstance(event.binary_evidence, dict) else None,
                    "window_size": event.binary_evidence.get("window_size") if isinstance(event.binary_evidence, dict) else None,
                    "positive_count": event.binary_evidence.get("positive_count") if isinstance(event.binary_evidence, dict) else None,
                    "consecutive_positive_count": event.binary_evidence.get("consecutive_positive_count") if isinstance(event.binary_evidence, dict) else None,
                    "reason": event.binary_evidence.get("reason") if isinstance(event.binary_evidence, dict) else None,
                },
            )
            self._append_log_locked(f"binary_event_archived incident_id={event.incident_id}")
            self._write_session_events_locked()
            self._write_session_summary_locked()
        event_dir = self.binary_full_dir / _safe_name(event.incident_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        image_files = _write_images(event_dir, images)
        payload = self._binary_event_payload(
            session_id=session_id,
            event=event,
            package=package,
            image_files=image_files,
            missing_reasons=list(missing_reasons or []),
        )
        _write_json(event_dir / "binary_event.json", payload)
        self._write_incident_event_json(event, payload)
        return True

    def archive_qwen_result(self, event: FallEvent) -> str | None:
        detail = event.vlm_analysis
        if detail is None:
            return None
        with self._lock:
            if event.incident_id not in self._event_sessions:
                return None
            session_id = self._event_sessions[event.incident_id]
            images = list(self._qwen_images.get(event.incident_id, []))
            self._qwen_unresolved_ids.discard(event.incident_id)
            first_qwen_result = (
                event.incident_id not in self._qwen_confirm_ids
                and event.incident_id not in self._qwen_deny_ids
                and event.incident_id not in self._qwen_review_ids
            )
            if first_qwen_result and detail.analysis_status == "completed":
                self._qwen_completed_count += 1
            elif first_qwen_result and detail.analysis_status == "timeout":
                self._qwen_timeout_count += 1
            elif first_qwen_result:
                self._qwen_failed_count += 1
        verdict = (detail.fall_verdict or "unclear").strip().lower()
        if detail.analysis_status == "completed" and verdict == "confirmed_fall":
            root = self.qwen_confirm_dir
            bucket = "confirm"
            with self._lock:
                self._qwen_confirm_ids.add(event.incident_id)
        elif detail.analysis_status == "completed" and verdict in {"normal_activity", "intentional_low_posture", "non_fall"}:
            root = self.qwen_deny_dir
            bucket = "deny"
            with self._lock:
                self._qwen_deny_ids.add(event.incident_id)
        else:
            root = self.qwen_review_dir
            bucket = "review"
            with self._lock:
                self._qwen_review_ids.add(event.incident_id)

        event_dir = root / _safe_name(event.incident_id)
        event_dir.mkdir(parents=True, exist_ok=True)
        image_files = _write_images(event_dir, images)
        completed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        qwen_review = _compact_qwen_review(detail)
        _write_json(event_dir / "qwen_review.json", qwen_review)
        payload = {
            "schema_version": "post_fall_v2_test_qwen_review.v1",
            "test_session_id": session_id,
            "created_during_test": True,
            "event_created_at": self._event_created_at.get(event.incident_id, event.created_at),
            "qwen_request_started_at": detail.request_started_at,
            "qwen_completed_at": completed_at,
            "qwen_elapsed_ms": detail.latency_ms,
            "stage": f"qwen_{bucket}",
            "incident_id": event.incident_id,
            "camera_id": event.camera_id,
            "fall_verdict": detail.fall_verdict,
            "analysis_status": detail.analysis_status,
            "confidence": detail.confidence,
            "high_risk_fall": detail.high_risk_fall,
            "error_message": detail.error_message,
            "qwen_start_frames_received": detail.qwen_start_frames_received,
            "qwen_end_frames_received": detail.qwen_end_frames_received,
            "frames_received_during_qwen": detail.frames_received_during_qwen,
            "safety_decision": event.safety_decision.to_record() if event.safety_decision is not None else None,
            "qwen_analysis": detail.to_record(),
            "keyframes": image_files,
            "qwen_review": qwen_review,
        }
        with self._lock:
            record = self._event_records.get(event.incident_id, {})
            record.update(
                {
                    "stage": f"qwen_{bucket}",
                    "qwen_bucket": bucket,
                    "qwen_request_started_at": detail.request_started_at,
                    "qwen_completed_at": payload["qwen_completed_at"],
                    "qwen_elapsed_ms": detail.latency_ms,
                    "qwen_analysis": detail.to_record(),
                    "event": event.to_record(),
                }
            )
            self._event_records[event.incident_id] = record
            if not self._running and not self._qwen_unresolved_ids:
                self._state = "completed"
                self._finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._drain_deadline_monotonic = None
                self._stop_performance_monitor_locked()
            self._append_log_locked(f"qwen_result_archived incident_id={event.incident_id} bucket={bucket}")
            self._append_trace_locked(
                "qwen_result",
                {
                    "incident_id": event.incident_id,
                    "camera_id": event.camera_id,
                    "bucket": bucket,
                    "analysis_status": detail.analysis_status,
                    "fall_verdict": detail.fall_verdict,
                    "request_started_at": detail.request_started_at,
                    "completed_at": completed_at,
                    "latency_ms": detail.latency_ms,
                    "request_to_complete_ms": _elapsed_ms_since(detail.request_started_at) if detail.request_started_at else None,
                    "qwen_start_frames_received": detail.qwen_start_frames_received,
                    "qwen_end_frames_received": detail.qwen_end_frames_received,
                    "frames_received_during_qwen": detail.frames_received_during_qwen,
                },
            )
            self._write_session_events_locked()
            self._write_session_summary_locked()
        self._write_incident_event_json(event, {**payload, "event": event.to_record()})
        return bucket

    def _refresh_locked(self) -> None:
        if self._state == "draining" and self._drain_deadline_monotonic is not None:
            if time.monotonic() >= self._drain_deadline_monotonic:
                self._complete_drain_timeouts_locked()
                return
        if not self._running:
            return
        if self._ends_at_monotonic is None:
            return
        if self._remaining_seconds_locked() > 0:
            return
        self._running = False
        self._ends_at_monotonic = None
        self._stopped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self._qwen_unresolved_ids:
            self._state = "draining"
            self._drain_deadline_monotonic = time.monotonic() + self._drain_timeout_seconds
        else:
            self._state = "completed"
            self._finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._drain_deadline_monotonic = None
        if self._state == "completed":
            self._stop_performance_monitor_locked()
        self._append_log_locked("test_duration_elapsed")
        self._write_session_summary_locked()

    def _remaining_seconds_locked(self) -> int:
        if not self._running or self._ends_at_monotonic is None:
            return 0
        return max(0, int(round(self._ends_at_monotonic - time.monotonic())))

    def _complete_drain_timeouts_locked(self) -> None:
        timed_out_ids = sorted(self._qwen_unresolved_ids)
        if not timed_out_ids:
            self._state = "completed"
            self._finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._drain_deadline_monotonic = None
            self._stop_performance_monitor_locked()
            self._write_session_summary_locked()
            return
        completed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        for incident_id in timed_out_ids:
            self._qwen_unresolved_ids.discard(incident_id)
            self._qwen_timeout_count += 1
            self._qwen_review_ids.add(incident_id)
            record = dict(self._event_records.get(incident_id, {}))
            event_record = record.get("event") if isinstance(record.get("event"), dict) else {}
            camera_id = str(record.get("camera_id") or event_record.get("camera_id") or "unknown")
            session_id = self._event_sessions.get(incident_id, self._session_id or "test_unknown")
            qwen_analysis = {
                "incident_id": incident_id,
                "analysis_status": "timeout",
                "fall_verdict": "unclear",
                "error_message": "test_drain_timeout",
            }
            qwen_review = {
                "occlusion": "unknown",
                "scene_risks": [],
                "possible_help_gesture": "unknown",
                "summary": "千问分析超时，建议人工复核事件关键帧。",
                "review_points": ["建议人工复核事件关键帧。"],
                "confidence": None,
            }
            payload = {
                "schema_version": "post_fall_v2_test_qwen_review.v1",
                "test_session_id": session_id,
                "created_during_test": True,
                "event_created_at": self._event_created_at.get(incident_id),
                "qwen_completed_at": completed_at,
                "stage": "qwen_timeout",
                "incident_id": incident_id,
                "camera_id": camera_id,
                "fall_verdict": "unclear",
                "analysis_status": "timeout",
                "qwen_analysis": qwen_analysis,
                "keyframes": [],
                "qwen_review": qwen_review,
            }
            qwen_dir = self.qwen_review_dir / _safe_name(incident_id)
            _write_json(qwen_dir / "qwen_review.json", qwen_review)
            record.update(
                {
                    "stage": "qwen_timeout",
                    "qwen_bucket": "review",
                    "qwen_completed_at": completed_at,
                    "qwen_analysis": qwen_analysis,
                }
            )
            self._event_records[incident_id] = record
            self._append_trace_locked(
                "qwen_timeout",
                {
                    "incident_id": incident_id,
                    "camera_id": camera_id,
                    "completed_at": completed_at,
                    "event_created_at": self._event_created_at.get(incident_id),
                },
            )
            self._write_incident_payload(camera_id, incident_id, {**payload, "event": event_record})
            self._append_log_locked(f"qwen_timeout incident_id={incident_id}")
        self._state = "completed"
        self._finalized_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._drain_deadline_monotonic = None
        self._stop_performance_monitor_locked()
        self._write_session_events_locked()
        self._write_session_summary_locked()

    def _session_dir_locked(self) -> Path:
        return self.test_sessions_dir / (self._session_id or "test_unknown")

    def _initialise_session_files_locked(self) -> None:
        session_dir = self._session_dir_locked()
        session_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self._session_manifest_path_locked(), self._session_manifest or {})
        _write_text_if_missing(
            session_dir / "binary_predictions.csv",
            "created_at,camera_id,frame_seq,frame_id,frame_age_ms,queue_delay_ms,decision_label,fall_probability,non_fall_probability,provider,inference_ms,total_ms,aggregate_state,window_size,positive_count,consecutive_positive_count,candidate_duration_ms,incident_id,event_created,reason,inference_at\n",
        )
        _write_text_if_missing(
            session_dir / "performance.csv",
            "created_at,cpu_percent,memory_percent,memory_used_mb,process_cpu_percent,process_rss_mb,gpu_util_percent,gpu_memory_used_mb,gpu_memory_total_mb,gpu_memory_percent\n",
        )
        _write_text_if_missing(self._trace_path_locked(), "")
        _write_json(session_dir / "events.json", [])
        _write_json(session_dir / "presentation_result.json", self._build_presentation_result_locked())
        self._write_session_summary_locked()
        self._append_log_locked("start_test")

    def _append_trace_locked(self, stage: str, payload: dict[str, Any]) -> None:
        if not self._session_id:
            return
        record: dict[str, Any] = {
            "seq": len(self._trace_records) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "stage": stage,
        }
        record.update({str(key): _jsonable(value) for key, value in payload.items()})
        self._trace_records.append(record)
        with self._trace_path_locked().open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")

    def _append_binary_prediction_locked(
        self,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
        raw: Any | None,
        sampled: Any | None,
    ) -> None:
        performance = getattr(raw, "performance", None)
        model = getattr(raw, "model", None)
        captured_monotonic = getattr(sampled, "captured_monotonic", None)
        frame_age_ms = None
        if captured_monotonic is not None:
            try:
                frame_age_ms = round((time.monotonic() - float(captured_monotonic)) * 1000, 2)
            except (TypeError, ValueError):
                frame_age_ms = None
        line = _csv_line(
            [
                datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                binary.camera_id,
                binary.frame_seq,
                binary.frame_id,
                frame_age_ms,
                getattr(performance, "queue_delay_ms", None),
                binary.decision_label,
                binary.fall_probability,
                binary.non_fall_probability,
                getattr(model, "provider", None),
                getattr(performance, "inference_ms", None),
                getattr(performance, "total_ms", None),
                decision.state,
                decision.evidence.window_size,
                decision.evidence.positive_count,
                decision.evidence.consecutive_positive_count,
                decision.evidence.candidate_duration_ms,
                decision.incident_id,
                decision.event_created,
                decision.reason,
                binary.inferred_at,
            ]
        )
        self._append_session_file_locked("binary_predictions.csv", line)

    def _observe_binary_prediction_locked(
        self,
        binary: BinaryFrameResult,
        decision: BinaryAggregateDecision,
    ) -> None:
        if binary.decision_label == "FALL":
            self._binary_fall_count += 1
        elif binary.decision_label == "NON_FALL":
            self._binary_non_fall_count += 1
        else:
            self._binary_unknown_count += 1
        if decision.reason == "fall_candidate_started":
            self._candidate_count += 1
        if not decision.event_created and decision.reason not in {"updated", "non_fall", "event_active_fall_persisting"}:
            bucket = self._rejection_bucket(decision)
            self._rejection_reasons[bucket] = self._rejection_reasons.get(bucket, 0) + 1

    def _rejection_bucket(self, decision: BinaryAggregateDecision) -> str:
        if decision.reason == "cooldown":
            return "cooldown"
        if decision.reason == "fall_candidate_cancelled":
            return "candidate_cancelled"
        if decision.reason in {"recovery_pending", "recovery_collecting", "recovery_confirmed"}:
            return "recovery"
        if decision.reason == "fall_candidate_collecting":
            if decision.evidence.candidate_duration_ms < 800:
                return "duration_too_short"
            if decision.evidence.positive_count < 4:
                return "not_enough_fall_frames"
            if decision.evidence.consecutive_positive_count < 3:
                return "tail_not_continuous"
        return decision.reason

    def _event_payload_locked(
        self,
        event: FallEvent,
        package: KeyframePackage,
        stage: str,
        missing_reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "test_session_id": self._event_sessions.get(event.incident_id, self._session_id),
            "stage": stage,
            "incident_id": event.incident_id,
            "camera_id": event.camera_id,
            "event_created_at": event.created_at,
            "event": event.to_record(),
            "keyframes": package.to_record(),
            "qwen_missing_reasons": missing_reasons,
        }

    def _binary_event_payload(
        self,
        *,
        session_id: str,
        event: FallEvent,
        package: KeyframePackage,
        image_files: list[str],
        missing_reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "schema_version": "post_fall_v2_test_binary_full.v1",
            "test_session_id": session_id,
            "created_during_test": True,
            "event_created_at": event.created_at,
            "stage": "binary_full",
            "decision": "FALL",
            "incident_id": event.incident_id,
            "camera_id": event.camera_id,
            "event": event.to_record(),
            "keyframes": package.to_record(),
            "qwen_input": {
                "image_files": image_files,
                "missing_reasons": missing_reasons,
            },
        }

    def _write_incident_event_json(self, event: FallEvent, payload: dict[str, Any]) -> None:
        self._write_incident_payload(event.camera_id, event.incident_id, payload)

    def _write_incident_payload(self, camera_id: str, incident_id: str, payload: dict[str, Any]) -> None:
        incident_dir = self.event_root / _safe_name(camera_id) / _safe_name(incident_id)
        _write_json(incident_dir / "event.json", payload)
        if self._session_id:
            session_incident_dir = self._session_dir_locked() / "incidents" / _safe_name(incident_id)
        else:
            session_incident_dir = None
        if session_incident_dir is not None:
            _write_json(session_incident_dir / "event.json", payload)

    def _write_session_events_locked(self) -> None:
        if not self._session_id:
            return
        records = [
            self._event_records[incident_id]
            for incident_id in sorted(self._event_records)
        ]
        _write_json(self._session_dir_locked() / "events.json", records)

    def _write_session_summary(self) -> None:
        with self._lock:
            self._write_session_summary_locked()

    def _write_session_summary_locked(self) -> None:
        if not self._session_id:
            return
        summary = {
            "schema_version": "post_fall_v2_test_session.v1",
            "test_session_id": self._session_id,
            "state": self._state,
            "running": self._running,
            "started_at": self._started_at,
            "running_at": self._running_at,
            "stopped_at": self._stopped_at,
            "finalized_at": self._finalized_at,
            "camera_id": self._camera_id,
            "manual_session": self._manual_session,
            "failure_stage": self._failure_stage,
            "failure_reason": self._failure_reason,
            "total_seconds": self._total_seconds,
            "remaining_seconds": self._remaining_seconds_locked(),
            "event_root": str(self.event_root),
            "binary_full_count": len(self._binary_full_ids),
            "binary_other_count": self._binary_other_count,
            "qwen_confirm_count": len(self._qwen_confirm_ids),
            "qwen_deny_count": len(self._qwen_deny_ids),
            "qwen_review_count": len(self._qwen_review_ids),
            "qwen_unresolved_count": len(self._qwen_unresolved_ids),
            "tracked_binary_event_ids": sorted(self._binary_full_ids),
            "frames_processed": self._binary_fall_count + self._binary_non_fall_count + self._binary_unknown_count,
            "binary_fall_count": self._binary_fall_count,
            "binary_non_fall_count": self._binary_non_fall_count,
            "binary_unknown_count": self._binary_unknown_count,
            "candidate_count": self._candidate_count,
            "confirmed_event_count": len(self._binary_full_ids),
            "rejection_reasons": dict(self._rejection_reasons),
            "qwen_requested": len(self._qwen_requested_ids),
            "qwen_completed": self._qwen_completed_count,
            "qwen_failed": self._qwen_failed_count,
            "qwen_timeout": self._qwen_timeout_count,
            "archive_created": len(self._binary_full_ids),
            "archive_failed": self._archive_failed_count,
            "performance_samples_count": self._performance_samples_count,
            "latest_performance": self._latest_performance,
            "trace_count": len(self._trace_records),
            "last_trace": self._trace_records[-1] if self._trace_records else None,
            "manifest": self._session_manifest,
            "artifacts": {
                "session_manifest": str(self._session_manifest_path_locked()),
                "trace_timeline": str(self._trace_path_locked()),
                "summary": str(self._summary_path_locked()),
                "report": str(self._report_path_locked()),
                "session_summary": str(self._session_dir_locked() / "session_summary.json"),
                "session_json": str(self._session_dir_locked() / "session.json"),
                "presentation_result": str(self._session_dir_locked() / "presentation_result.json"),
            },
            "performance": {
                key: value
                for key, value in self._performance_summary.items()
                if not key.startswith("_")
            },
        }
        report = self._build_session_report_locked(summary)
        session_json = {
            "schema_version": "post_fall_v2_detection_session.v1",
            "session_id": self._session_id,
            "test_session_id": self._session_id,
            "camera_id": self._camera_id,
            "started_at": self._started_at,
            "running_at": self._running_at,
            "stop_requested_at": self._stopped_at,
            "finalized_at": self._finalized_at,
            "duration_seconds": _elapsed_seconds(self._started_at, ended_at=self._finalized_at or self._stopped_at),
            "status": self._state,
            "manual_session": self._manual_session,
            "failure_stage": self._failure_stage,
            "failure_reason": self._failure_reason,
        }
        presentation = self._build_presentation_result_locked()
        _write_json(self._session_dir_locked() / "session_summary.json", summary)
        _write_json(self._session_dir_locked() / "session.json", session_json)
        _write_json(self._session_dir_locked() / "presentation_result.json", presentation)
        _write_json(self._summary_path_locked(), summary)
        self._report_path_locked().write_text(report, encoding="utf-8")
        _write_json(self._session_manifest_path_locked(), self._session_manifest or {})

    def _build_presentation_result_locked(self) -> dict[str, Any]:
        latest = self._latest_qwen_event_record_locked()
        if latest is None:
            return {
                "schema_version": "post_fall_v2_presentation_result.v1",
                "test_session_id": self._session_id,
                "session_id": self._session_id,
                "camera_id": self._camera_id,
                "analysis_status": "failed" if self._state == "failed" else "no_event",
                "event_id": None,
                "event_time": None,
                "time_description_zh": self._failure_reason if self._state == "failed" else "暂无跌倒事件，检测到候选事件后将在这里显示最终结构化结果。",
                "is_real_fall": None,
                "fall_verdict": None,
                "confidence": None,
                "source": "presentation_adapter",
            }
        qwen = latest.get("qwen_analysis") if isinstance(latest.get("qwen_analysis"), dict) else {}
        event = latest.get("event") if isinstance(latest.get("event"), dict) else {}
        incident_id = str(latest.get("incident_id") or event.get("incident_id") or qwen.get("incident_id") or "")
        event_time = (
            latest.get("event_created_at")
            or event.get("created_at")
            or event.get("confirmed_at")
            or event.get("started_at")
            or qwen.get("request_started_at")
        )
        verdict = str(qwen.get("fall_verdict") or latest.get("fall_verdict") or "unclear").strip().lower()
        analysis_status = str(qwen.get("analysis_status") or latest.get("analysis_status") or "completed").strip().lower()
        mapped = _map_verdict_for_presentation(verdict)
        summary = str(qwen.get("summary") or latest.get("summary") or "").strip()
        return {
            "schema_version": "post_fall_v2_presentation_result.v1",
            "test_session_id": self._session_id,
            "session_id": self._session_id,
            "camera_id": str(latest.get("camera_id") or event.get("camera_id") or self._camera_id or ""),
            "analysis_status": analysis_status,
            "event_id": incident_id or None,
            "event_time": event_time,
            "time_description_zh": _build_time_description_zh(event_time, mapped["label"], summary),
            "is_real_fall": mapped["is_real_fall"],
            "fall_verdict": verdict,
            "fall_label_zh": mapped["label"],
            "confidence": _as_float(qwen.get("confidence") if qwen else latest.get("confidence")),
            "source": "presentation_adapter",
        }

    def _latest_qwen_event_record_locked(self) -> dict[str, Any] | None:
        candidates = []
        for record in self._event_records.values():
            qwen = record.get("qwen_analysis") if isinstance(record.get("qwen_analysis"), dict) else None
            if qwen is None:
                continue
            order_key = str(record.get("qwen_completed_at") or record.get("event_created_at") or "")
            candidates.append((order_key, record))
        if not candidates:
            return None
        return dict(sorted(candidates, key=lambda item: item[0])[-1][1])

    def _build_session_report_locked(self, summary: dict[str, Any]) -> str:
        lines = [
            "# SYSTEM E2E TEST REPORT",
            "",
            f"- session_id: `{summary['test_session_id']}`",
            f"- state: `{summary['state']}`",
            f"- started_at: `{summary.get('started_at')}`",
            f"- stopped_at: `{summary.get('stopped_at')}`",
            f"- total_seconds: `{summary.get('total_seconds')}`",
            f"- remaining_seconds: `{summary.get('remaining_seconds')}`",
            "",
            "## Counts",
            f"- binary_full: `{summary.get('binary_full_count')}`",
            f"- binary_other: `{summary.get('binary_other_count')}`",
            f"- binary_fall: `{summary.get('binary_fall_count')}`",
            f"- binary_non_fall: `{summary.get('binary_non_fall_count')}`",
            f"- binary_unknown: `{summary.get('binary_unknown_count')}`",
            f"- candidate_count: `{summary.get('candidate_count')}`",
            f"- qwen_requested: `{summary.get('qwen_requested')}`",
            f"- qwen_completed: `{summary.get('qwen_completed')}`",
            f"- qwen_failed: `{summary.get('qwen_failed')}`",
            f"- qwen_timeout: `{summary.get('qwen_timeout')}`",
            f"- trace_count: `{summary.get('trace_count')}`",
            "",
            "## Performance",
            f"- latest_performance: `{summary.get('latest_performance')}`",
            f"- performance: `{summary.get('performance')}`",
            "",
            "## Trace",
        ]
        if self._trace_records:
            for record in self._trace_records[-20:]:
                payload = {k: v for k, v in record.items() if k not in {"timestamp", "stage", "seq"}}
                lines.append(
                    f"- {record.get('timestamp')} {record.get('stage')} "
                    f"{json.dumps(payload, ensure_ascii=False)}"
                )
        else:
            lines.append("- no trace records yet")
        lines.extend(
            [
                "",
                "## Artifacts",
                f"- SESSION_MANIFEST.json: `{summary['artifacts']['session_manifest']}`",
                f"- TRACE_TIMELINE.jsonl: `{summary['artifacts']['trace_timeline']}`",
                f"- SUMMARY.json: `{summary['artifacts']['summary']}`",
                f"- TEST_REPORT.md: `{summary['artifacts']['report']}`",
                f"- session_summary.json: `{summary['artifacts']['session_summary']}`",
            ]
        )
        return "\n".join(lines) + "\n"

    def _append_log_locked(self, message: str) -> None:
        self._append_session_file_locked(
            "test.log",
            f"{datetime.now(timezone.utc).isoformat(timespec='milliseconds')} {message}\n",
        )

    def _append_session_file_locked(self, filename: str, text: str) -> None:
        if not self._session_id:
            return
        path = self._session_dir_locked() / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def _start_performance_monitor_locked(self) -> None:
        stop_event = threading.Event()
        self._performance_stop = stop_event
        session_id = self._session_id
        thread = threading.Thread(
            target=self._performance_loop,
            args=(stop_event, session_id),
            name=f"post-fall-v2-test-performance-{self._session_id}",
            daemon=True,
        )
        self._performance_thread = thread
        thread.start()

    def _stop_performance_monitor_locked(self) -> None:
        self._performance_stop.set()
        self._performance_thread = None

    def _performance_loop(self, stop_event: threading.Event, session_id: str | None) -> None:
        sampler = _ProcessPerformanceSampler()
        while not stop_event.wait(self._performance_interval):
            sample = sampler.sample()
            with self._lock:
                if not self._session_id or self._session_id != session_id:
                    continue
                self._latest_performance = sample
                self._performance_samples_count += 1
                self._observe_performance_sample_locked(sample)
                self._append_session_file_locked(
                    "performance.csv",
                    _csv_line(
                        [
                            sample.get("created_at"),
                            sample.get("cpu_percent"),
                            sample.get("memory_percent"),
                            sample.get("memory_used_mb"),
                            sample.get("process_cpu_percent"),
                            sample.get("process_rss_mb"),
                            sample.get("gpu_util_percent"),
                            sample.get("gpu_memory_used_mb"),
                            sample.get("gpu_memory_total_mb"),
                            sample.get("gpu_memory_percent"),
                        ]
                    ),
                )
                self._write_session_summary_locked()

    def _observe_performance_sample_locked(self, sample: dict[str, Any]) -> None:
        definitions = {
            "cpu": "cpu_percent",
            "memory": "memory_percent",
            "memory_used_mb": "memory_used_mb",
            "process_cpu": "process_cpu_percent",
            "process_rss_mb": "process_rss_mb",
            "gpu": "gpu_util_percent",
            "gpu_memory_used_mb": "gpu_memory_used_mb",
            "gpu_memory_percent": "gpu_memory_percent",
        }
        for prefix, source_key in definitions.items():
            value = _as_float(sample.get(source_key))
            if value is None:
                continue
            sum_key = f"_{prefix}_sum"
            count_key = f"_{prefix}_count"
            avg_key = f"{prefix}_avg"
            peak_key = f"{prefix}_peak"
            total = float(self._performance_summary.get(sum_key, 0.0)) + value
            count = int(self._performance_summary.get(count_key, 0)) + 1
            self._performance_summary[sum_key] = total
            self._performance_summary[count_key] = count
            self._performance_summary[avg_key] = round(total / count, 2)
            previous_peak = _as_float(self._performance_summary.get(peak_key))
            self._performance_summary[peak_key] = value if previous_peak is None else max(previous_peak, value)


class _ProcessPerformanceSampler:
    def __init__(self) -> None:
        self._process = None
        self._psutil = None
        try:
            import psutil  # type: ignore

            self._psutil = psutil
            self._process = psutil.Process()
            self._process.cpu_percent(interval=None)
            psutil.cpu_percent(interval=None)
        except Exception:
            self._psutil = None
            self._process = None

    def sample(self) -> dict[str, Any]:
        sample: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "cpu_percent": None,
            "memory_percent": None,
            "memory_used_mb": None,
            "process_cpu_percent": None,
            "process_rss_mb": None,
            "gpu_util_percent": None,
            "gpu_memory_used_mb": None,
            "gpu_memory_total_mb": None,
            "gpu_memory_percent": None,
        }
        if self._psutil is not None and self._process is not None:
            try:
                memory = self._psutil.virtual_memory()
                sample["cpu_percent"] = round(float(self._psutil.cpu_percent(interval=None)), 2)
                sample["memory_percent"] = round(float(memory.percent), 2)
                sample["memory_used_mb"] = round(float(memory.used) / (1024 * 1024), 2)
                sample["process_cpu_percent"] = round(float(self._process.cpu_percent(interval=None)), 2)
                sample["process_rss_mb"] = round(float(self._process.memory_info().rss) / (1024 * 1024), 2)
            except Exception:
                pass
        sample.update(_nvidia_smi_sample())
        return sample


def _nvidia_smi_sample() -> dict[str, Any]:
    fallback = {
        "gpu_util_percent": None,
        "gpu_memory_used_mb": None,
        "gpu_memory_total_mb": None,
        "gpu_memory_percent": None,
    }
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=0.75,
            check=False,
        )
    except Exception:
        return fallback
    if completed.returncode != 0:
        return fallback
    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 3:
        return fallback
    try:
        return {
            "gpu_util_percent": float(parts[0]),
            "gpu_memory_used_mb": float(parts[1]),
            "gpu_memory_total_mb": float(parts[2]),
            "gpu_memory_percent": round(float(parts[1]) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else None,
        }
    except ValueError:
        return fallback


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _elapsed_ms_since(started_at: str | None, *, ended_at: str | None = None) -> float | None:
    if not started_at:
        return None
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(ended_at).replace("Z", "+00:00")) if ended_at else datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return round((end - start).total_seconds() * 1000.0, 3)
    except (TypeError, ValueError):
        return None


def _elapsed_seconds(started_at: str | None, *, ended_at: str | None = None) -> float | None:
    elapsed_ms = _elapsed_ms_since(started_at, ended_at=ended_at)
    if elapsed_ms is None:
        return None
    return round(elapsed_ms / 1000.0, 3)


def _map_verdict_for_presentation(verdict: str) -> dict[str, Any]:
    normalized = str(verdict or "unclear").strip().lower()
    if normalized == "confirmed_fall":
        return {"label": "真实跌倒", "is_real_fall": True}
    if normalized in {"normal_activity", "intentional_low_posture", "non_fall"}:
        return {"label": "非真实跌倒", "is_real_fall": False}
    if normalized == "insufficient_visual_evidence":
        return {"label": "视觉证据不足", "is_real_fall": None}
    return {"label": "无法明确判断", "is_real_fall": None}


def _build_time_description_zh(event_time: Any, fall_label: str, summary: str | None = None) -> str:
    time_text = _format_china_time(event_time)
    summary_text = (summary or "").strip(" 。\r\n\t")
    if fall_label == "真实跌倒":
        conclusion = "经视觉复核判断为真实跌倒。"
    elif fall_label == "非真实跌倒":
        conclusion = "经视觉复核判断为非真实跌倒。"
    elif fall_label == "视觉证据不足":
        conclusion = "当前关键帧视觉证据不足，建议人工复核。"
    else:
        conclusion = "当前结果无法明确判断，建议人工复核。"
    if summary_text:
        return f"{time_text}，{summary_text}，{conclusion}"
    return f"{time_text}，检测到候选跌倒事件，{conclusion}"


def _format_china_time(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return "时间未明确"
    china = timezone(timedelta(hours=8))
    parsed = parsed.astimezone(china)
    return f"{parsed.year}年{parsed.month}月{parsed.day}日{parsed.hour}时{parsed.minute:02d}分"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "unknown"


def _compact_qwen_review(detail: Any) -> dict[str, Any]:
    source = detail.to_record() if hasattr(detail, "to_record") else {}
    scene_risks = source.get("scene_risks")
    review_points = source.get("review_points")
    return {
        "occlusion": str(source.get("occlusion") or "unknown"),
        "scene_risks": [str(item) for item in scene_risks[:4]]
        if isinstance(scene_risks, list) else [],
        "possible_help_gesture": str(source.get("possible_help_gesture") or "unknown"),
        "summary": str(source.get("summary") or ""),
        "review_points": [str(item) for item in review_points[:3]]
        if isinstance(review_points, list) else [],
        "confidence": _as_float(source.get("confidence")),
        "analysis_status": source.get("analysis_status"),
        "fall_verdict": source.get("fall_verdict"),
        "high_risk_fall": source.get("high_risk_fall"),
        "latency_ms": source.get("latency_ms"),
        "qwen_profile": source.get("qwen_profile"),
        "qwen_model": source.get("model_name"),
        "prompt_version": source.get("prompt_version"),
        "schema_version": source.get("schema_version"),
        "fusion_version": source.get("fusion_version"),
        "request_started_at": source.get("request_started_at"),
        "completed_at": source.get("completed_at"),
        "error_message": source.get("error_message"),
        "qwen_start_frames_received": source.get("qwen_start_frames_received"),
        "qwen_end_frames_received": source.get("qwen_end_frames_received"),
        "frames_received_during_qwen": source.get("frames_received_during_qwen"),
    }


def _write_images(output_dir: Path, images: list[QwenImageInput]) -> list[str]:
    saved: list[str] = []
    for index, image in enumerate(images, start=1):
        role = _safe_name(image.role or "keyframe")
        name = f"{index:02d}_{image.offset_ms:+05d}ms_{role}.jpg"
        path = output_dir / name
        if not path.exists():
            path.write_bytes(image.image_bytes)
        saved.append(name)
    return saved


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text_if_missing(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, encoding="utf-8")


def _csv_line(values: list[Any]) -> str:
    return ",".join(_csv_cell(value) for value in values) + "\n"


def _csv_cell(value: Any) -> str:
    if value is None:
        text = ""
    else:
        text = str(value)
    if any(character in text for character in [",", "\"", "\r", "\n"]):
        text = "\"" + text.replace("\"", "\"\"") + "\""
    return text


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_record"):
        return value.to_record()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value
