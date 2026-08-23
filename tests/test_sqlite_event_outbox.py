from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app.events.outbox import SQLiteEventOutbox
from app.events.schemas import FallEventRecord


class SQLiteEventOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        self.temp = TemporaryDirectory()
        self.path = Path(self.temp.name) / "event_outbox.sqlite3"
        self.outbox = SQLiteEventOutbox(self.path, now=lambda: self.now)
        self.event = FallEventRecord(
            incident_id="incident-sqlite", camera_id="camera_01", track_id=3,
            event_type="fall_candidate", fall_state="fallen_candidate", risk_level="high",
            trigger_timestamp=self.now.isoformat(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_add_get_and_reconstruct(self) -> None:
        self.outbox.add_event(self.event)
        self.assertEqual(self.outbox.get_event(self.event.incident_id).event.camera_id, "camera_01")
        rebuilt = SQLiteEventOutbox(self.path, now=lambda: self.now)
        self.assertEqual(rebuilt.get_event(self.event.incident_id).event.track_id, 3)

    def test_claim_is_exclusive_and_expired_lease_is_reclaimed(self) -> None:
        self.outbox.add_event(self.event)
        first = self.outbox.claim_next("worker-a", 5)
        self.assertIsNotNone(first)
        self.assertIsNone(self.outbox.claim_next("worker-b", 5))
        self.now += timedelta(seconds=6)
        second = self.outbox.claim_next("worker-b", 5)
        self.assertIsNotNone(second)
        self.assertEqual(second.lock_owner, "worker-b")
        self.assertNotEqual(first.lock_token, second.lock_token)

    def test_retry_count_and_not_before_are_persisted(self) -> None:
        self.outbox.add_event(self.event)
        retry_at = (self.now + timedelta(seconds=15)).isoformat()
        retry = self.outbox.mark_retry(self.event.incident_id, "temporary", retry_at)
        self.assertEqual(retry.retry_count, 1)
        self.assertIsNone(self.outbox.claim_next("worker", 5))
        self.now += timedelta(seconds=16)
        self.assertIsNotNone(self.outbox.claim_next("worker", 5))
