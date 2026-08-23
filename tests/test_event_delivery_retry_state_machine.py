from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.events.delivery import DeliveryOutbox
from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryRetryStateMachineTest(unittest.TestCase):
    def test_retry_claim_waits_for_next_retry_and_lock_expiry(self) -> None:
        outbox = DeliveryOutbox(replace(Settings(), event_delivery_enabled=True, event_delivery_mode="post"))
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="retry-sm"))

        first_claim = outbox.claim_next("worker-a", 30)
        self.assertIsNotNone(first_claim)
        self.assertEqual(first_claim.delivery_id, record.delivery_id)
        self.assertIsNone(outbox.claim_next("worker-b", 30))

        expired = first_claim.model_copy(update={"lock_until": self._seconds_from_now(-1)})
        outbox._records[record.delivery_id] = expired  # type: ignore[attr-defined]
        self.assertEqual(outbox.claim_next("worker-b", 30).delivery_id, record.delivery_id)

        outbox.mark_retry(record.delivery_id, "http_500", 500, self._seconds_from_now(3600))
        self.assertIsNone(outbox.claim_next("worker-c", 30))

        outbox.mark_retry(record.delivery_id, "http_500", 500, self._seconds_from_now(-1))
        due = outbox.claim_next("worker-c", 30)
        self.assertIsNotNone(due)
        self.assertEqual(due.delivery_status, "retry")

    @staticmethod
    def _seconds_from_now(seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="retry-sm",
            support_fall_alarm=True,
            final_event_type="fallen_confirmed",
            final_risk_level="high",
            confidence=0.8,
            explanation="confirmed",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="check",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(incident_id="retry-sm", camera_id="camera_01", trigger_timestamp="2026-07-18T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
