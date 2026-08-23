from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.core.config import Settings
from app.events.delivery import DeliveryOutbox
from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryIdempotencyTest(unittest.TestCase):
    def test_memory_reuses_same_incident_record(self) -> None:
        outbox = DeliveryOutbox(replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run"))

        first = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="idem-1"))
        second = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="idem-1"))

        self.assertEqual(second.delivery_id, first.delivery_id)
        self.assertEqual(len(outbox.list_deliveries()), 1)

    def test_sqlite_reuses_same_incident_record_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = replace(
                Settings(),
                event_delivery_enabled=True,
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=str(Path(temp_dir) / "delivery.sqlite3"),
            )
            first_outbox = DeliveryOutbox(settings)
            first = first_outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="idem-1"))

            reopened = DeliveryOutbox(settings)
            second = reopened.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="idem-1"))

            self.assertEqual(second.delivery_id, first.delivery_id)
            self.assertEqual(len(reopened.list_deliveries()), 1)

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="idem-1",
            support_fall_alarm=True,
            final_event_type="fallen_confirmed",
            final_risk_level="medium",
            confidence=0.8,
            explanation="confirmed",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="check",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(incident_id="idem-1", camera_id="camera_01", trigger_timestamp="2026-07-18T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
