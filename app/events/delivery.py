from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.contracts.integration_v1 import QwenKeyframeAdvisorySummary, VisionEventMetadataExtension
from urllib.parse import urlsplit

import requests

from app.core.config import Settings
from app.core.logger import get_logger
from app.events.schemas import DeliveryRecord, EvidencePackage, EventSemantics, QwenKeyframeAdvisory, TrustedEventResult, event_now_iso

logger = get_logger(__name__)

_SEVERITY_BY_RISK = {
    "critical": "L3",
    "high": "L2",
    "medium": "L1",
    "low": "L0",
}
_INJURY_LEVEL_BY_RISK = {
    "critical": "I3",
    "high": "I2",
    "medium": "I1",
    "low": "I0",
}


def build_main_system_payload(
    trusted_result: TrustedEventResult,
    evidence: EvidencePackage,
    semantics: EventSemantics | None = None,
    *,
    delivery_mode: str = "dry_run",
    dry_run: bool = True,
    qwen_advisory: QwenKeyframeAdvisory | None = None,
) -> dict[str, Any]:
    risk_level = _normalize_risk(trusted_result.final_risk_level, evidence, semantics)
    event_type = _main_event_type(trusted_result.final_event_type)
    state = _main_state(trusted_result.final_event_type)
    status = _main_status(trusted_result.final_event_type)
    fall_prob = evidence.fall_probability if evidence.fall_probability is not None else trusted_result.confidence
    fall_score = evidence.fall_evidence_score
    if fall_score is None:
        fall_score = evidence.fall_probability if evidence.fall_probability is not None else trusted_result.confidence
    scores = {key: value for key, value in {"hybrid": fall_score, "detector": fall_prob}.items() if value is not None}
    snapshot_url = _snapshot_url(evidence)
    bbox = _bbox(evidence)
    injury = {
        "level": _INJURY_LEVEL_BY_RISK[risk_level],
        "reason": evidence.decision_reason or _injury_reason(status),
        "advice": trusted_result.recommended_action,
    }
    degradation_used = list({*evidence.degradation_used, *trusted_result.degradation_used, *(semantics.degradation_used if semantics else [])})
    extension = _vision_event_extension(trusted_result, evidence, degradation_used, qwen_advisory=qwen_advisory)
    return {
        "incident_id": trusted_result.incident_id,
        "camera_id": evidence.camera_id,
        "stream_name": "primary",
        "source": "vision_service",
        "event_type": event_type,
        "state": state,
        "status": status,
        "service_state": "running",
        "severity": _SEVERITY_BY_RISK[risk_level],
        "risk": risk_level,
        "risk_level": risk_level,
        "fall_detected": bool(trusted_result.support_fall_alarm),
        "fall_prob": fall_prob,
        "fall_score": fall_score,
        "track_id": str(evidence.track_id) if evidence.track_id is not None else None,
        "bbox": bbox,
        "snapshot_url": snapshot_url,
        "timestamp": evidence.trigger_timestamp,
        "injury": injury,
        "explanation": trusted_result.explanation,
        "recommended_action": trusted_result.recommended_action,
        "advice": trusted_result.recommended_action,
        "delivery_mode": delivery_mode,
        "dry_run": bool(dry_run),
        "degradation_used": degradation_used,
        "review_result": trusted_result.review_result,
        "scores": scores,
        "metadata": {
            **extension,
            "event": {
                "incident_id": trusted_result.incident_id,
                "camera_id": evidence.camera_id,
                "stream_name": "primary",
                "event_type": event_type,
                "state": state,
                "status": status,
                "severity": _SEVERITY_BY_RISK[risk_level],
                "risk": risk_level,
                "risk_level": risk_level,
                "fall_score": fall_score,
                "fall_prob": fall_prob,
                "track_id": str(evidence.track_id) if evidence.track_id is not None else None,
                "snapshot_url": snapshot_url,
                "injury": injury,
            },
            "review_result": trusted_result.review_result,
            "confidence": trusted_result.confidence,
            "degradation_used": degradation_used,
        },
        "semantics": {"uncertainty": (semantics.uncertainty if semantics else [])},
    }


def _vision_event_extension(
    trusted_result: TrustedEventResult,
    evidence: EvidencePackage,
    degradation_used: list[str],
    *,
    qwen_advisory: QwenKeyframeAdvisory | None = None,
) -> dict[str, Any]:
    missing_reasons = [item.missing_reason for item in evidence.keyframes if item.missing_reason]
    evidence_status = "complete" if not missing_reasons and len(evidence.keyframes) >= 6 else "degraded"
    # Do not export archive paths or direct media URLs through this contract.
    # The receiver can request approved event details through its own integration.
    extension = VisionEventMetadataExtension(
        evidence={
            "evidence_status": evidence_status,
            "keyframe_count": sum(1 for item in evidence.keyframes if not item.missing_reason),
            "keyframe_urls": [],
            "missing_reasons": list(dict.fromkeys(missing_reasons + degradation_used)),
        },
        semantic_analysis={
            "support_fall_alarm": trusted_result.support_fall_alarm,
            "final_event_type": trusted_result.final_event_type,
            "final_risk_level": trusted_result.final_risk_level,
            "explanation": trusted_result.explanation,
            "uncertainty": trusted_result.uncertainty,
            "qwen_keyframe_advisory": _qwen_advisory_summary(qwen_advisory),
        },
    )
    # Do not serialize optional fields owned by other systems. In particular,
    # Vision must not advertise or imply a robot-control capability.
    return extension.model_dump(mode="json", exclude_none=True)


def _qwen_advisory_summary(advisory: QwenKeyframeAdvisory | None) -> dict[str, Any] | None:
    if advisory is None or advisory.analysis_status not in {"completed", "degraded", "failed"}:
        return None
    return QwenKeyframeAdvisorySummary(
        analysis_status=advisory.analysis_status,
        model_name=advisory.model_name,
        image_count=advisory.image_count,
        scene_summary=advisory.scene_summary,
        posture_description=advisory.posture_description,
        movement_description=advisory.movement_description,
        possible_false_positive_reasons=advisory.possible_false_positive_reasons,
        care_advice=advisory.care_advice,
        confidence_explanation=advisory.confidence_explanation,
        advisory_confidence=advisory.advisory_confidence,
        latency_ms=advisory.latency_ms,
        error_code=advisory.error_code,
    ).model_dump(mode="json")


class DeliveryOutbox:
    """Opt-in delivery queue. It never replaces FallEventReporterService."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.event_delivery_enabled)
        self.backend = str(getattr(settings, "event_delivery_backend", "memory") or "memory")
        self._records: dict[str, DeliveryRecord] = {}
        self._lock = threading.Lock()
        self._sqlite_path = Path(getattr(settings, "event_delivery_sqlite_path", "data/event_delivery_outbox.sqlite3"))
        if self.backend == "sqlite":
            try:
                self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                self._init_sqlite()
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_init_failed path=%s error=%s", self._sqlite_path, exc)

    def enqueue(
        self,
        trusted_result: TrustedEventResult,
        evidence: EvidencePackage,
        semantics: EventSemantics | None,
    ) -> DeliveryRecord:
        record = self._new_record(trusted_result, evidence, semantics)
        if self.backend == "sqlite":
            try:
                existing = self.for_incident(record.incident_id)
                if existing is not None:
                    return existing
                self._sqlite_store(record)
                return record.model_copy(deep=True)
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_enqueue_failed incident_id=%s error=%s", record.incident_id, exc)
                return record.model_copy(deep=True)
        with self._lock:
            existing = next((item for item in self._records.values() if item.incident_id == record.incident_id), None)
            if existing is not None:
                return existing.model_copy(deep=True)
            self._records[record.delivery_id] = record
        return record.model_copy(deep=True)

    def get(self, delivery_id: str) -> DeliveryRecord | None:
        if self.backend == "sqlite":
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM event_delivery_outbox WHERE delivery_id=?",
                        (delivery_id,),
                    ).fetchone()
                return self._decode_row(row) if row else None
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_get_failed delivery_id=%s error=%s", delivery_id, exc)
                return None
        with self._lock:
            record = self._records.get(delivery_id)
            return record.model_copy(deep=True) if record else None

    def deliver(self, delivery_id: str) -> DeliveryRecord | None:
        record = self.get(delivery_id)
        if record is None:
            return None
        if not self.enabled:
            return record
        if self.settings.event_delivery_mode == "dry_run":
            return self._update(
                delivery_id,
                delivery_mode="dry_run",
                dry_run=True,
                delivery_status="dry_run_sent",
                lock_owner=None,
                lock_token=None,
                lock_until=None,
            )
        sending = self.mark_sending(delivery_id)
        if sending is None:
            return None
        if not str(sending.target_url or "").strip():
            return self._retry_or_fail(delivery_id, "missing_event_delivery_target_url", None)
        try:
            request_kwargs = {
                "json": sending.payload_json,
                "timeout": max(
                    0.2,
                    min(
                        float(self.settings.event_delivery_timeout_seconds),
                        float(self.settings.main_system_alert_timeout_ms) / 1000,
                    ),
                ),
            }
            headers = self._auth_headers()
            if headers:
                request_kwargs["headers"] = headers
            response = requests.post(sending.target_url, **request_kwargs)
            if 200 <= response.status_code < 300:
                return self.mark_sent(delivery_id, http_status=response.status_code)
            return self._retry_or_fail(delivery_id, f"http_{response.status_code}", response.status_code)
        except requests.RequestException as exc:
            return self._retry_or_fail(delivery_id, str(exc), None)

    def _auth_headers(self) -> dict[str, str]:
        token = str(self.settings.main_system_alert_token or "").strip()
        header_name = str(self.settings.main_system_alert_token_header or "").strip()
        return {header_name: token} if token and header_name else {}

    def latest_for_camera(self, camera_id: str) -> DeliveryRecord | None:
        if self.backend == "sqlite":
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM event_delivery_outbox WHERE camera_id=? ORDER BY updated_at DESC LIMIT 1",
                        (camera_id,),
                    ).fetchone()
                return self._decode_row(row) if row else None
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_latest_failed camera_id=%s error=%s", camera_id, exc)
                return None
        with self._lock:
            matches = [item for item in self._records.values() if item.camera_id == camera_id]
            return max(matches, key=lambda item: item.updated_at).model_copy(deep=True) if matches else None

    def for_incident(self, incident_id: str) -> DeliveryRecord | None:
        if self.backend == "sqlite":
            try:
                with self._connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM event_delivery_outbox WHERE incident_id=? ORDER BY created_at ASC LIMIT 1",
                        (incident_id,),
                    ).fetchone()
                return self._decode_row(row) if row else None
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_for_incident_failed incident_id=%s error=%s", incident_id, exc)
                return None
        with self._lock:
            record = next((item for item in self._records.values() if item.incident_id == incident_id), None)
            return record.model_copy(deep=True) if record else None

    def list_deliveries(
        self,
        *,
        status: str | None = None,
        camera_id: str | None = None,
        limit: int | None = None,
    ) -> list[DeliveryRecord]:
        if self.backend == "sqlite":
            clauses, values = [], []
            if status:
                clauses.append("delivery_status=?")
                values.append(status)
            if camera_id:
                clauses.append("camera_id=?")
                values.append(camera_id)
            query = "SELECT * FROM event_delivery_outbox"
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY created_at DESC"
            if limit is not None:
                query += " LIMIT ?"
                values.append(max(0, int(limit)))
            try:
                with self._connect() as conn:
                    rows = conn.execute(query, values).fetchall()
                return [record for row in rows if (record := self._decode_row(row)) is not None]
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_list_failed error=%s", exc)
                return []
        with self._lock:
            records = list(self._records.values())
            if status:
                records = [record for record in records if record.delivery_status == status]
            if camera_id:
                records = [record for record in records if record.camera_id == camera_id]
            records.sort(key=lambda item: item.created_at, reverse=True)
            if limit is not None:
                records = records[: max(0, int(limit))]
            return [record.model_copy(deep=True) for record in records]

    def claim_next(self, worker_id: str, lock_ttl_seconds: float) -> DeliveryRecord | None:
        now = datetime.now(timezone.utc)
        lock_until = datetime.fromtimestamp(
            now.timestamp() + max(0.0, float(lock_ttl_seconds)),
            timezone.utc,
        ).isoformat(timespec="milliseconds")
        if self.backend == "sqlite":
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    rows = conn.execute(
                        "SELECT * FROM event_delivery_outbox ORDER BY created_at ASC"
                    ).fetchall()
                    for row in rows:
                        record = self._decode_row(row)
                        if record is None or not _claimable(record, now):
                            continue
                        claimed = record.model_copy(
                            update={
                                "lock_owner": worker_id,
                                "lock_token": secrets.token_urlsafe(12),
                                "lock_until": lock_until,
                                "updated_at": event_now_iso(),
                            }
                        )
                        self._sqlite_store(claimed, conn=conn)
                        return claimed.model_copy(deep=True)
                return None
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_claim_failed error=%s", exc)
                return None
        with self._lock:
            for delivery_id, record in self._records.items():
                if not _claimable(record, now):
                    continue
                claimed = record.model_copy(
                    update={
                        "lock_owner": worker_id,
                        "lock_token": secrets.token_urlsafe(12),
                        "lock_until": lock_until,
                        "updated_at": event_now_iso(),
                    }
                )
                self._records[delivery_id] = claimed
                return claimed.model_copy(deep=True)
        return None

    def mark_sending(self, delivery_id: str) -> DeliveryRecord | None:
        record = self.get(delivery_id)
        if record is None:
            return None
        return self._update(
            delivery_id,
            delivery_status="sending",
            attempt_count=record.attempt_count + 1,
            delivery_mode="dry_run" if self.settings.event_delivery_mode == "dry_run" else "post",
            dry_run=self.settings.event_delivery_mode == "dry_run",
        )

    def mark_sent(self, delivery_id: str, http_status: int | None = None) -> DeliveryRecord | None:
        return self._update(
            delivery_id,
            delivery_status="sent",
            last_http_status=http_status,
            delivered_at=event_now_iso(),
            last_error=None,
            next_retry_at=None,
            lock_owner=None,
            lock_token=None,
            lock_until=None,
        )

    def mark_retry(
        self,
        delivery_id: str,
        error: str,
        http_status: int | None = None,
        next_retry_at: str | None = None,
    ) -> DeliveryRecord | None:
        return self._update(
            delivery_id,
            delivery_status="retry",
            last_error=error,
            last_http_status=http_status,
            next_retry_at=next_retry_at,
            lock_owner=None,
            lock_token=None,
            lock_until=None,
        )

    def mark_failed(
        self,
        delivery_id: str,
        error: str,
        http_status: int | None = None,
    ) -> DeliveryRecord | None:
        return self._update(
            delivery_id,
            delivery_status="failed",
            last_error=error,
            last_http_status=http_status,
            lock_owner=None,
            lock_token=None,
            lock_until=None,
        )

    def _retry_or_fail(self, delivery_id: str, error: str, status: int | None) -> DeliveryRecord:
        record = self.get(delivery_id)
        if record is None:
            raise KeyError(f"delivery record not found: {delivery_id}")
        if record.attempt_count >= self.settings.event_delivery_retry_limit:
            return self.mark_failed(delivery_id, error, status)
        retry_at = (datetime.now(timezone.utc) + timedelta(seconds=self.settings.event_delivery_retry_backoff_seconds)).isoformat(timespec="milliseconds")
        return self.mark_retry(delivery_id, error, status, retry_at)

    def _update(self, delivery_id: str, **updates) -> DeliveryRecord:
        if self.backend == "sqlite":
            current = self.get(delivery_id)
            if current is None:
                raise KeyError(f"delivery record not found: {delivery_id}")
            updated = current.model_copy(update={**updates, "updated_at": event_now_iso()})
            try:
                self._sqlite_store(updated)
            except sqlite3.Error as exc:
                logger.warning("event_delivery_sqlite_update_failed delivery_id=%s error=%s", delivery_id, exc)
            return updated.model_copy(deep=True)
        with self._lock:
            current = self._records[delivery_id]
            updated = current.model_copy(update={**updates, "updated_at": event_now_iso()})
            self._records[delivery_id] = updated
            return updated.model_copy(deep=True)

    def _new_record(
        self,
        trusted_result: TrustedEventResult,
        evidence: EvidencePackage,
        semantics: EventSemantics | None,
    ) -> DeliveryRecord:
        delivery_mode = "dry_run" if self.settings.event_delivery_mode == "dry_run" else "post"
        payload = build_main_system_payload(
            trusted_result,
            evidence,
            semantics,
            delivery_mode=delivery_mode,
            dry_run=delivery_mode == "dry_run",
        )
        target = self.settings.event_delivery_target_url
        return DeliveryRecord(
            delivery_id=str(uuid.uuid4()),
            incident_id=trusted_result.incident_id,
            camera_id=evidence.camera_id,
            target_url=target,
            payload_json=payload,
            delivery_mode=delivery_mode,
            dry_run=delivery_mode == "dry_run",
        )

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS event_delivery_outbox (
                    delivery_id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL UNIQUE,
                    camera_id TEXT NOT NULL,
                    target_url TEXT,
                    payload_json TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    delivery_mode TEXT NOT NULL,
                    dry_run INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_http_status INTEGER,
                    last_error TEXT,
                    next_retry_at TEXT,
                    lock_owner TEXT,
                    lock_token TEXT,
                    lock_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_delivery_incident ON event_delivery_outbox(incident_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_delivery_camera ON event_delivery_outbox(camera_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_delivery_status ON event_delivery_outbox(delivery_status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_delivery_retry ON event_delivery_outbox(next_retry_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_delivery_created ON event_delivery_outbox(created_at)")

    def _sqlite_store(self, record: DeliveryRecord, conn: sqlite3.Connection | None = None) -> None:
        def write(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO event_delivery_outbox (
                    delivery_id, incident_id, camera_id, target_url, payload_json, delivery_status,
                    delivery_mode, dry_run, attempt_count, last_http_status, last_error, next_retry_at,
                    lock_owner, lock_token, lock_until, created_at, updated_at, delivered_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    target_url=excluded.target_url,
                    payload_json=excluded.payload_json,
                    delivery_status=excluded.delivery_status,
                    delivery_mode=excluded.delivery_mode,
                    dry_run=excluded.dry_run,
                    attempt_count=excluded.attempt_count,
                    last_http_status=excluded.last_http_status,
                    last_error=excluded.last_error,
                    next_retry_at=excluded.next_retry_at,
                    lock_owner=excluded.lock_owner,
                    lock_token=excluded.lock_token,
                    lock_until=excluded.lock_until,
                    updated_at=excluded.updated_at,
                    delivered_at=excluded.delivered_at
                """
                ,
                (
                    record.delivery_id,
                    record.incident_id,
                    record.camera_id,
                    record.target_url,
                    json.dumps(record.payload_json, ensure_ascii=False, sort_keys=True),
                    record.delivery_status,
                    record.delivery_mode,
                    1 if record.dry_run else 0,
                    record.attempt_count,
                    record.last_http_status,
                    record.last_error,
                    record.next_retry_at,
                    record.lock_owner,
                    record.lock_token,
                    record.lock_until,
                    record.created_at,
                    record.updated_at,
                    record.delivered_at,
                ),
            )

        if conn is not None:
            write(conn)
            return
        with self._connect() as connection:
            write(connection)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._sqlite_path), timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return _CommitConnection(conn)

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> DeliveryRecord | None:
        if row is None:
            return None
        return DeliveryRecord(
            delivery_id=row["delivery_id"],
            incident_id=row["incident_id"],
            camera_id=row["camera_id"],
            target_url=row["target_url"] or "",
            payload_json=json.loads(row["payload_json"]),
            delivery_status=row["delivery_status"],
            delivery_mode=row["delivery_mode"],
            dry_run=bool(row["dry_run"]),
            attempt_count=int(row["attempt_count"] or 0),
            last_http_status=row["last_http_status"],
            last_error=row["last_error"],
            next_retry_at=row["next_retry_at"],
            lock_owner=row["lock_owner"],
            lock_token=row["lock_token"],
            lock_until=row["lock_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            delivered_at=row["delivered_at"],
        )


class SQLiteDeliveryOutbox(DeliveryOutbox):
    """Explicit SQLite delivery outbox entrypoint for tests and future wiring."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(replace(settings, event_delivery_backend="sqlite"))


class MemoryDeliveryOutbox(DeliveryOutbox):
    """Explicit in-memory delivery outbox entrypoint."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(replace(settings, event_delivery_backend="memory"))


def _normalize_risk(
    value: Any,
    evidence: EvidencePackage | None = None,
    semantics: EventSemantics | None = None,
) -> str:
    candidates = [
        value,
        (semantics.risk or {}).get("risk_level") if semantics is not None else None,
        (semantics.risk or {}).get("risk") if semantics is not None else None,
        (evidence.fusion_debug or {}).get("risk_level") if evidence is not None else None,
        (evidence.fusion_debug or {}).get("risk") if evidence is not None else None,
    ]
    for candidate in candidates:
        risk = str(candidate or "").strip().lower()
        if risk in _SEVERITY_BY_RISK:
            return risk
    return "medium"


def _main_event_type(value: Any) -> str:
    event_type = str(value or "").strip().lower()
    if event_type in {"confirmed", "fallen_confirmed", "confirmed_fall", "fall_confirmed"}:
        return "fall_confirmed"
    if event_type in {"need_review", "review_required", "fall_review_required"}:
        return "fall_review_required"
    return "fall_candidate"


def _main_state(value: Any) -> str:
    event_type = str(value or "").strip().lower()
    if event_type in {"confirmed", "fallen_confirmed", "confirmed_fall", "fall_confirmed"}:
        return "fallen_confirmed"
    if event_type in {"need_review", "review_required", "fall_review_required"}:
        return "need_review"
    return "fallen_candidate"


def _main_status(value: Any) -> str:
    event_type = str(value or "").strip().lower()
    if event_type in {"confirmed", "fallen_confirmed", "confirmed_fall", "fall_confirmed"}:
        return "confirmed_fall"
    if event_type in {"need_review", "review_required", "fall_review_required"}:
        return "review_required"
    return "fall_candidate"


def _injury_reason(status: str) -> str:
    if status == "confirmed_fall":
        return "vision_service_fallen_confirmed"
    return "vision_service_fall_candidate"


def _snapshot_url(evidence: EvidencePackage) -> str | None:
    candidates = [
        item.snapshot_url
        for item in evidence.keyframes
        if item.snapshot_url and (item.role == "trigger" or item.offset_ms == 0)
    ]
    candidates.extend(item.snapshot_url for item in evidence.keyframes if item.snapshot_url)
    return next((_safe_snapshot_url(candidate) for candidate in candidates if _safe_snapshot_url(candidate)), None)


def _safe_snapshot_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    if "\\" in text or (len(text) >= 3 and text[1] == ":" and text[2] in {"/", "\\"}):
        return None
    if text.startswith("//"):
        return None
    if text.startswith("/"):
        return text
    if ":" in text.split("/", 1)[0]:
        return None
    return text


def _bbox(evidence: EvidencePackage) -> list[float] | None:
    trigger = next((item for item in evidence.keyframes if item.role == "trigger" and item.bbox), None)
    if trigger is not None and trigger.bbox is not None:
        return [float(value) for value in trigger.bbox]
    keyframe = next((item for item in evidence.keyframes if item.bbox), None)
    if keyframe is not None and keyframe.bbox is not None:
        return [float(value) for value in keyframe.bbox]
    if evidence.bbox_sequence:
        return [float(value) for value in evidence.bbox_sequence[-1]]
    return None


def _join_url(base_url: str, path: str) -> str:
    normalized_path = str(path or "").strip() or "/api/integrations/fall-detection/alerts"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    return f"{str(base_url or '').rstrip('/')}{normalized_path}"


def _claimable(record: DeliveryRecord, now: datetime) -> bool:
    if record.delivery_status not in {"pending", "retry"}:
        return False
    if record.delivery_status == "retry" and record.next_retry_at and _parse_time(record.next_retry_at) > now:
        return False
    if record.lock_until is None:
        return True
    return _parse_time(record.lock_until) <= now


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class _CommitConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()
