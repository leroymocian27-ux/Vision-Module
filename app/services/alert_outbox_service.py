from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from app.core.config import Settings
from app.schemas.common import utc_now_iso


@dataclass
class AlertOutboxStatus:
    enabled: bool
    path: str
    pending_count: int = 0
    retry_wait_count: int = 0
    failed_count: int = 0
    delivered_count: int = 0
    last_status: str | None = None
    last_error: str | None = None


class AlertOutboxService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.enabled = bool(settings.alert_outbox_enabled)
        self.path = Path(settings.alert_outbox_path)
        self._lock = threading.Lock()
        self._last_status: str | None = None
        self._last_error: str | None = None
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    def record_pending(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        incident_id = _event_id(payload)
        if not incident_id:
            return
        now = utc_now_iso()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_outbox (
                    incident_id, camera_id, track_id, created_at, updated_at,
                    payload_json, delivery_state, retry_count, last_error,
                    next_attempt_at, last_http_status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, NULL)
                ON CONFLICT(incident_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json,
                    delivery_state=CASE
                        WHEN alert_outbox.delivery_state='delivered' THEN 'delivered'
                        ELSE 'pending'
                    END,
                    next_attempt_at=CASE
                        WHEN alert_outbox.delivery_state='delivered' THEN alert_outbox.next_attempt_at
                        ELSE excluded.next_attempt_at
                    END
                """,
                (
                    incident_id,
                    str(payload.get("camera_id") or ""),
                    str(payload.get("track_id") or ""),
                    now,
                    now,
                    body,
                    now,
                ),
            )
            self._last_status = "pending"
            self._last_error = None

    def record_result(self, payload: dict[str, Any], status: str, error: str | None, *, http_status: int | None = None) -> None:
        if not self.enabled:
            return
        incident_id = _event_id(payload)
        if not incident_id:
            return
        now = utc_now_iso()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        delivered = status in {"delivered", "duplicate_ack"} or status.startswith("http_2")
        dry_run = status == "dry_run_skipped"
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT retry_count FROM alert_outbox WHERE incident_id=?", (incident_id,)).fetchone()
            previous_retries = int(row[0]) if row is not None else 0
            retry_count = previous_retries if delivered or dry_run else previous_retries + 1
            retry_limit = max(0, int(self.settings.alert_outbox_retry_limit))
            if delivered:
                state = "delivered"
                next_attempt_at = None
            elif dry_run:
                state = "dry_run"
                next_attempt_at = None
            elif retry_limit > 0 and retry_count >= retry_limit:
                state = "failed"
                next_attempt_at = None
            else:
                state = "retry_wait"
                next_attempt_at = _future_attempt_iso(_backoff_seconds(self.settings, retry_count))
            conn.execute(
                """
                INSERT INTO alert_outbox (
                    incident_id, camera_id, track_id, created_at, updated_at,
                    payload_json, delivery_state, retry_count, last_error,
                    next_attempt_at, last_http_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json,
                    delivery_state=excluded.delivery_state,
                    retry_count=excluded.retry_count,
                    last_error=excluded.last_error,
                    next_attempt_at=excluded.next_attempt_at,
                    last_http_status=excluded.last_http_status
                """,
                (
                    incident_id,
                    str(payload.get("camera_id") or ""),
                    str(payload.get("track_id") or ""),
                    now,
                    now,
                    body,
                    state,
                    retry_count,
                    error,
                    next_attempt_at,
                    http_status,
                ),
            )
            self._last_status = state
            self._last_error = error

    def pending_payloads(self, limit: int = 8, *, include_failed: bool = False) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        retry_limit = max(0, int(self.settings.alert_outbox_retry_limit))
        if retry_limit <= 0:
            return []
        states = ("pending", "retry_wait", "failed") if include_failed else ("pending", "retry_wait")
        retry_clause = "(retry_count < ? OR delivery_state='failed')" if include_failed else "retry_count < ?"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload_json
                FROM alert_outbox
                WHERE delivery_state IN ({",".join("?" for _ in states)})
                  AND {retry_clause}
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ? OR delivery_state='failed')
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (*states, retry_limit, utc_now_iso(), max(1, int(limit))),
            ).fetchall()
        payloads: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(str(row[0]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        return payloads

    def status(self) -> AlertOutboxStatus:
        if not self.enabled:
            return AlertOutboxStatus(enabled=False, path=str(self.path))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT delivery_state, COUNT(*)
                FROM alert_outbox
                GROUP BY delivery_state
                """
            ).fetchall()
        counts = {str(row[0]): int(row[1]) for row in rows}
        return AlertOutboxStatus(
            enabled=True,
            path=str(self.path),
            pending_count=counts.get("pending", 0),
            retry_wait_count=counts.get("retry_wait", 0),
            failed_count=counts.get("failed", 0),
            delivered_count=counts.get("delivered", 0),
            last_status=self._last_status,
            last_error=self._last_error,
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_outbox (
                    incident_id TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    track_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    delivery_state TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    next_attempt_at TEXT,
                    last_http_status INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_outbox_state ON alert_outbox(delivery_state)"
            )
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(alert_outbox)").fetchall()}
            if "next_attempt_at" not in columns:
                conn.execute("ALTER TABLE alert_outbox ADD COLUMN next_attempt_at TEXT")
            if "last_http_status" not in columns:
                conn.execute("ALTER TABLE alert_outbox ADD COLUMN last_http_status INTEGER")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _event_id(payload: dict[str, Any]) -> str:
    return str(payload.get("event_id") or payload.get("incident_id") or "").strip()


def _backoff_seconds(settings: Settings, retry_count: int) -> float:
    raw = str(getattr(settings, "main_system_retry_backoff_seconds", "1,2,5") or "")
    values: list[float] = []
    for part in raw.split(","):
        try:
            value = float(part.strip())
        except ValueError:
            continue
        if value >= 0:
            values.append(value)
    if not values:
        values = [1.0, 2.0, 5.0]
    index = max(0, min(len(values) - 1, retry_count - 1))
    return values[index]


def _future_attempt_iso(delay_seconds: float) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(delay_seconds)))).isoformat(timespec="milliseconds")
