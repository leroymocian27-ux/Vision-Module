from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.events.outbox import EventOutbox
from app.events.schemas import FallEventRecord


class EventOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)
        self.outbox = EventOutbox(now=lambda: self.now)
        self.event = FallEventRecord(
            incident_id="incident-1",
            camera_id="camera_01",
            track_id=3,
            event_type="fall_candidate",
            fall_state="fallen_candidate",
            risk_level="high",
            trigger_timestamp=self.now.isoformat(),
        )

    def test_only_one_worker_can_claim_event(self) -> None:
        self.outbox.add_event(self.event)

        first = self.outbox.claim_next("worker-a", 30)
        second = self.outbox.claim_next("worker-b", 30)

        self.assertIsNotNone(first)
        self.assertEqual(first.lock_owner, "worker-a")
        self.assertIsNone(second)

    def test_expired_processing_lock_can_be_reclaimed(self) -> None:
        self.outbox.add_event(self.event)
        first = self.outbox.claim_next("worker-a", 5)
        self.assertIsNotNone(first)
        self.now += timedelta(seconds=6)

        reclaimed = self.outbox.claim_next("worker-b", 30)

        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed.lock_owner, "worker-b")
        self.assertNotEqual(reclaimed.lock_token, first.lock_token)

    def test_retry_count_and_not_before_are_respected(self) -> None:
        self.outbox.add_event(self.event)
        future = (self.now + timedelta(seconds=30)).isoformat()
        retry = self.outbox.mark_retry("incident-1", "temporary failure", future)

        self.assertEqual(retry.retry_count, 1)
        self.assertIsNone(self.outbox.claim_next("worker-a", 30))
        self.now += timedelta(seconds=31)
        self.assertIsNotNone(self.outbox.claim_next("worker-a", 30))
