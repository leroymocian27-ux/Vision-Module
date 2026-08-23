from __future__ import annotations

import secrets
import json
import sqlite3
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable
from pathlib import Path

from app.events.schemas import (
    EvidencePackage,
    EventSemantics,
    EventOutboxRecord,
    FallEventRecord,
    QwenKeyframeAdvisory,
    TrustedEventResult,
    event_now_iso,
)


class EventOutbox:
    """Thread-safe in-memory event work queue with lease-based claiming.

    The public methods mirror the durable backend planned for a later SQLite or
    Redis implementation. Callers therefore do not depend on in-memory state.
    """

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._records: OrderedDict[str, EventOutboxRecord] = OrderedDict()

    def add_event(self, record: FallEventRecord) -> EventOutboxRecord:
        with self._lock:
            existing = self._records.get(record.incident_id)
            if existing is not None:
                updated = _event_update(existing, record)
                self._records[record.incident_id] = updated
                return updated.model_copy(deep=True)
            outbox_record = EventOutboxRecord(event=record)
            self._records[record.incident_id] = outbox_record
            return outbox_record.model_copy(deep=True)

    def get_event(self, incident_id: str) -> EventOutboxRecord | None:
        with self._lock:
            record = self._records.get(incident_id)
            return record.model_copy(deep=True) if record is not None else None

    def claim_next(self, worker_id: str, lock_ttl_seconds: float) -> EventOutboxRecord | None:
        now = self._now()
        with self._lock:
            for incident_id, record in self._records.items():
                if not self._claimable(record, now):
                    continue
                lock_until = datetime.fromtimestamp(
                    now.timestamp() + max(0.0, float(lock_ttl_seconds)), timezone.utc
                ).isoformat(timespec="milliseconds")
                claimed = record.model_copy(
                    update={
                        "status": "processing",
                        "lock_owner": worker_id,
                        "lock_token": secrets.token_urlsafe(12),
                        "lock_until": lock_until,
                        "updated_at": event_now_iso(),
                    }
                )
                self._records[incident_id] = claimed
                return claimed.model_copy(deep=True)
        return None

    def mark_evidence_ready(self, incident_id: str, evidence_package: EvidencePackage) -> EventOutboxRecord:
        return self._update(incident_id, status="evidence_ready", evidence_package=evidence_package)

    def mark_reviewed(self, incident_id: str, trusted_result: TrustedEventResult) -> EventOutboxRecord:
        return self._update(incident_id, status="reviewed", trusted_result=trusted_result)

    def mark_semantic_ready(self, incident_id: str, semantics: EventSemantics) -> EventOutboxRecord:
        return self._update(incident_id, status="semantic_ready", event_semantics=semantics)

    def mark_delivery_pending(self, incident_id: str) -> EventOutboxRecord:
        return self._update(incident_id, status="delivery_pending")

    def mark_qwen_advisory(self, incident_id: str, advisory: QwenKeyframeAdvisory) -> EventOutboxRecord:
        return self._update(incident_id, qwen_advisory=advisory)

    def mark_sent(self, incident_id: str) -> EventOutboxRecord:
        return self._update(incident_id, status="sent", lock_owner=None, lock_token=None, lock_until=None)

    def mark_retry(self, incident_id: str, error: str, next_retry_at: str | None = None) -> EventOutboxRecord:
        with self._lock:
            record = self._require(incident_id)
            updated = record.model_copy(
                update={
                    "status": "retry",
                    "retry_count": record.retry_count + 1,
                    "next_retry_at": next_retry_at,
                    "last_error": error,
                    "lock_owner": None,
                    "lock_token": None,
                    "lock_until": None,
                    "updated_at": event_now_iso(),
                }
            )
            self._records[incident_id] = updated
            return updated.model_copy(deep=True)

    def mark_failed(self, incident_id: str, error: str) -> EventOutboxRecord:
        return self._update(
            incident_id,
            status="failed",
            last_error=error,
            lock_owner=None,
            lock_token=None,
            lock_until=None,
        )

    def records(self) -> list[EventOutboxRecord]:
        return self.list_events()

    def list_events(
        self,
        *,
        status: str | None = None,
        camera_id: str | None = None,
        limit: int | None = None,
    ) -> list[EventOutboxRecord]:
        with self._lock:
            records = list(self._records.values())
            if status:
                records = [record for record in records if record.status == status]
            if camera_id:
                records = [record for record in records if record.event.camera_id == camera_id]
            if limit is not None:
                records = records[-max(0, int(limit)):]
            return [record.model_copy(deep=True) for record in records]

    def stats(self) -> dict[str, int]:
        counts = {"pending": 0, "processing": 0, "reviewed": 0, "failed": 0}
        for record in self.records():
            counts[record.status] = counts.get(record.status, 0) + 1
        return counts

    def mark_archive(self, incident_id: str, archive_path: str, archive_summary: dict) -> EventOutboxRecord:
        return self._update(incident_id, archive_path=archive_path, archive_summary=archive_summary)

    def _update(self, incident_id: str, **updates) -> EventOutboxRecord:
        with self._lock:
            record = self._require(incident_id)
            updated = record.model_copy(update={**updates, "updated_at": event_now_iso()})
            self._records[incident_id] = updated
            return updated.model_copy(deep=True)

    def _require(self, incident_id: str) -> EventOutboxRecord:
        record = self._records.get(incident_id)
        if record is None:
            raise KeyError(f"event outbox record not found: {incident_id}")
        return record

    @staticmethod
    def _claimable(record: EventOutboxRecord, now: datetime) -> bool:
        if record.status not in {"pending", "retry", "processing"}:
            return False
        if record.status == "retry" and record.next_retry_at and _parse_time(record.next_retry_at) > now:
            return False
        if record.lock_until is None:
            return record.status != "processing"
        return _parse_time(record.lock_until) <= now


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _event_update(existing: EventOutboxRecord, record: FallEventRecord) -> EventOutboxRecord:
    """Requeue an incident when Fusion upgrades candidate to confirmed."""
    upgraded = existing.event.event_type != "fallen_confirmed" and record.event_type == "fallen_confirmed"
    updates = {"event": record, "updated_at": event_now_iso()}
    if upgraded:
        updates.update({
            "status": "pending",
            "lock_owner": None,
            "lock_token": None,
            "lock_until": None,
            "retry_count": 0,
            "next_retry_at": None,
            "last_error": None,
            "evidence_package": None,
            "event_semantics": None,
            "trusted_result": None,
            "qwen_advisory": None,
            "archive_path": None,
            "archive_summary": {},
        })
    return existing.model_copy(update=updates)


class SQLiteEventOutbox:
    """Durable EventOutbox implementation with lease claims guarded by SQLite CAS."""

    def __init__(self, path: str | Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.path = Path(path)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def add_event(self, record: FallEventRecord) -> EventOutboxRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM event_outbox WHERE incident_id=?", (record.incident_id,)).fetchone()
            existing = self._decode(row[0]) if row else None
            updated = _event_update(existing, record) if existing is not None else EventOutboxRecord(event=record)
            self._store(conn, updated)
            return updated.model_copy(deep=True)

    def get_event(self, incident_id: str) -> EventOutboxRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM event_outbox WHERE incident_id=?", (incident_id,)).fetchone()
        return self._decode(row[0]) if row else None

    def claim_next(self, worker_id: str, lock_ttl_seconds: float) -> EventOutboxRecord | None:
        now = self._now()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT incident_id, payload_json, updated_at FROM event_outbox ORDER BY created_at ASC"
            ).fetchall()
            for incident_id, payload_json, expected_updated_at in rows:
                record = self._decode(payload_json)
                if not EventOutbox._claimable(record, now):
                    continue
                lock_until = datetime.fromtimestamp(now.timestamp() + max(0.0, float(lock_ttl_seconds)), timezone.utc).isoformat(timespec="milliseconds")
                claimed = record.model_copy(update={
                    "status": "processing", "lock_owner": worker_id, "lock_token": secrets.token_urlsafe(12),
                    "lock_until": lock_until, "updated_at": event_now_iso(),
                })
                cursor = conn.execute(
                    "UPDATE event_outbox SET status=?, lock_owner=?, lock_token=?, lock_until=?, updated_at=?, payload_json=? "
                    "WHERE incident_id=? AND updated_at=?",
                    (
                        claimed.status,
                        claimed.lock_owner,
                        claimed.lock_token,
                        claimed.lock_until,
                        claimed.updated_at,
                        json.dumps(claimed.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                        incident_id,
                        expected_updated_at,
                    ),
                )
                if cursor.rowcount == 1:
                    return claimed.model_copy(deep=True)
            return None

    def mark_evidence_ready(self, incident_id: str, evidence_package: EvidencePackage) -> EventOutboxRecord:
        return self._update(incident_id, status="evidence_ready", evidence_package=evidence_package)

    def mark_semantic_ready(self, incident_id: str, semantics: EventSemantics) -> EventOutboxRecord:
        return self._update(incident_id, status="semantic_ready", event_semantics=semantics)

    def mark_reviewed(self, incident_id: str, trusted_result: TrustedEventResult) -> EventOutboxRecord:
        return self._update(incident_id, status="reviewed", trusted_result=trusted_result)

    def mark_delivery_pending(self, incident_id: str) -> EventOutboxRecord:
        return self._update(incident_id, status="delivery_pending")

    def mark_qwen_advisory(self, incident_id: str, advisory: QwenKeyframeAdvisory) -> EventOutboxRecord:
        return self._update(incident_id, qwen_advisory=advisory)

    def mark_sent(self, incident_id: str) -> EventOutboxRecord:
        return self._update(incident_id, status="sent", lock_owner=None, lock_token=None, lock_until=None)

    def mark_retry(self, incident_id: str, error: str, next_retry_at: str | None = None) -> EventOutboxRecord:
        record = self._require(incident_id)
        return self._update(incident_id, status="retry", retry_count=record.retry_count + 1, next_retry_at=next_retry_at,
                            last_error=error, lock_owner=None, lock_token=None, lock_until=None)

    def mark_failed(self, incident_id: str, error: str) -> EventOutboxRecord:
        return self._update(incident_id, status="failed", last_error=error, lock_owner=None, lock_token=None, lock_until=None)

    def mark_archive(self, incident_id: str, archive_path: str, archive_summary: dict) -> EventOutboxRecord:
        return self._update(incident_id, archive_path=archive_path, archive_summary=archive_summary)

    def records(self) -> list[EventOutboxRecord]:
        return self.list_events()

    def list_events(self, *, status: str | None = None, camera_id: str | None = None, limit: int | None = None) -> list[EventOutboxRecord]:
        clauses, values = [], []
        if status:
            clauses.append("status=?"); values.append(status)
        if camera_id:
            clauses.append("camera_id=?"); values.append(camera_id)
        query = "SELECT payload_json FROM event_outbox"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        if limit is not None:
            query += " LIMIT ?"; values.append(max(0, int(limit)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        return [self._decode(row[0]) for row in rows]

    def stats(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) FROM event_outbox GROUP BY status").fetchall()
        counts = {"pending": 0, "processing": 0, "reviewed": 0, "failed": 0}
        counts.update({str(status): int(count) for status, count in rows})
        return counts

    def _require(self, incident_id: str) -> EventOutboxRecord:
        record = self.get_event(incident_id)
        if record is None:
            raise KeyError(f"event outbox record not found: {incident_id}")
        return record

    def _update(self, incident_id: str, **updates) -> EventOutboxRecord:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM event_outbox WHERE incident_id=?", (incident_id,)).fetchone()
            if row is None:
                raise KeyError(f"event outbox record not found: {incident_id}")
            record = self._decode(row[0])
            updated = record.model_copy(update={**updates, "updated_at": event_now_iso()})
            self._store(conn, updated)
            return updated.model_copy(deep=True)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS event_outbox (
                    incident_id TEXT PRIMARY KEY, camera_id TEXT NOT NULL, track_id TEXT, event_type TEXT,
                    fall_state TEXT, risk_level TEXT, status TEXT NOT NULL, payload_json TEXT NOT NULL,
                    evidence_json TEXT, semantics_json TEXT, trusted_result_json TEXT, lock_owner TEXT,
                    lock_token TEXT, lock_until TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_outbox_claim ON event_outbox(status, next_retry_at, created_at)")

    def _store(self, conn: sqlite3.Connection, record: EventOutboxRecord) -> None:
        event = record.event
        conn.execute("""
            INSERT INTO event_outbox (incident_id,camera_id,track_id,event_type,fall_state,risk_level,status,payload_json,
                evidence_json,semantics_json,trusted_result_json,lock_owner,lock_token,lock_until,retry_count,next_retry_at,
                last_error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(incident_id) DO UPDATE SET camera_id=excluded.camera_id,track_id=excluded.track_id,
                event_type=excluded.event_type,fall_state=excluded.fall_state,risk_level=excluded.risk_level,status=excluded.status,
                payload_json=excluded.payload_json,evidence_json=excluded.evidence_json,semantics_json=excluded.semantics_json,
                trusted_result_json=excluded.trusted_result_json,lock_owner=excluded.lock_owner,lock_token=excluded.lock_token,
                lock_until=excluded.lock_until,retry_count=excluded.retry_count,next_retry_at=excluded.next_retry_at,
                last_error=excluded.last_error,updated_at=excluded.updated_at
        """, (event.incident_id, event.camera_id, str(event.track_id or ""), event.event_type, event.fall_state, event.risk_level,
              *self._columns(record), record.created_at))

    @staticmethod
    def _columns(record: EventOutboxRecord) -> tuple:
        return (record.status, json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                json.dumps(record.evidence_package.model_dump(mode="json"), ensure_ascii=False) if record.evidence_package else None,
                json.dumps(record.event_semantics.model_dump(mode="json"), ensure_ascii=False) if record.event_semantics else None,
                json.dumps(record.trusted_result.model_dump(mode="json"), ensure_ascii=False) if record.trusted_result else None,
                record.lock_owner, record.lock_token, record.lock_until, record.retry_count, record.next_retry_at,
                record.last_error, record.updated_at)

    @staticmethod
    def _decode(payload_json: str) -> EventOutboxRecord:
        return EventOutboxRecord.model_validate(json.loads(payload_json))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return _CommitConnection(conn)


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
