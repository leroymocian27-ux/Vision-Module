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
        incident_id = str(payload.get("incident_id") or "")
        if not incident_id:
            return
        now = utc_now_iso()
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_outbox (
                    incident_id, camera_id, track_id, created_at, updated_at,
                    payload_json, delivery_state, retry_count, last_error
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, NULL)
                ON CONFLICT(incident_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json,
                    delivery_state=CASE
                        WHEN alert_outbox.delivery_state='delivered' THEN 'delivered'
                        ELSE 'pending'
                    END
                """,
                (
                    incident_id,
                    str(payload.get("camera_id") or ""),
                    str(payload.get("track_id") or ""),
                    now,
                    now,
                    body,
                ),
            )
            self._last_status = "pending"
            self._last_error = None

    def record_result(self, payload: dict[str, Any], status: str, error: str | None) -> None:
        if not self.enabled:
            return
        incident_id = str(payload.get("incident_id") or "")
        if not incident_id:
            return
        state = "delivered" if status.startswith("http_2") else ("dry_run" if status == "dry_run_skipped" else "failed")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE alert_outbox
                SET updated_at=?, delivery_state=?, retry_count=retry_count + ?,
                    last_error=?
                WHERE incident_id=?
                """,
                (
                    utc_now_iso(),
                    state,
                    0 if state in {"delivered", "dry_run"} else 1,
                    error,
                    incident_id,
                ),
            )
            self._last_status = state
            self._last_error = error

    def pending_payloads(self, limit: int = 8) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        retry_limit = max(0, int(self.settings.alert_outbox_retry_limit))
        if retry_limit <= 0:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM alert_outbox
                WHERE delivery_state IN ('pending', 'failed')
                  AND retry_count < ?
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (retry_limit, max(1, int(limit))),
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
                    last_error TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_outbox_state ON alert_outbox(delivery_state)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path))
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
