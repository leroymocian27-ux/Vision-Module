from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.delivery_worker import DeliveryWorker
from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryWorkerTest(unittest.TestCase):
    def test_worker_is_disabled_by_default(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=False)
        outbox = DeliveryOutbox(settings)
        worker = DeliveryWorker(settings, outbox)

        self.assertFalse(worker.enabled)
        self.assertIsNone(worker.process_once())

    def test_worker_claims_and_delivers_one_record(self) -> None:
        settings = replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_worker_enabled=True,
            event_delivery_mode="post",
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
        )
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="worker-1"))
        worker = DeliveryWorker(settings, outbox)

        class OkResponse:
            status_code = 200
            text = "ok"

        def fake_post(*args, **kwargs):
            return OkResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = worker.process_once("worker-a")
        finally:
            delivery_module.requests.post = previous_post

        self.assertIsNotNone(delivered)
        self.assertEqual(delivered.delivery_status, "sent")
        self.assertEqual(outbox.get(record.delivery_id).delivery_status, "sent")

    def test_worker_catches_delivery_exceptions(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_worker_enabled=True)
        outbox = DeliveryOutbox(settings)
        worker = DeliveryWorker(settings, outbox)
        outbox.claim_next = lambda worker_id, lock_ttl_seconds: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]

        self.assertIsNone(worker.process_once("worker-a"))

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="worker-1",
            support_fall_alarm=True,
            final_event_type="fallen_confirmed",
            final_risk_level="critical",
            confidence=0.9,
            explanation="confirmed",
            alarm_title="fall",
            alarm_body="fall",
            recommended_action="check",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(
            incident_id="worker-1",
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
        )


if __name__ == "__main__":
    unittest.main()
