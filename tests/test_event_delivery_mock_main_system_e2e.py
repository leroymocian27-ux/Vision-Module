from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.delivery_worker import DeliveryWorker
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryMockMainSystemE2ETest(unittest.TestCase):
    def test_dry_run_does_not_call_main_system(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted("mock-dry"), self._evidence("mock-dry"), EventSemantics(incident_id="mock-dry"))
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("dry-run must not call main system")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(calls, [])
        self.assertEqual(delivered.delivery_status, "dry_run_sent")

    def test_post_200_sends_contract_payload_and_marks_sent(self) -> None:
        settings = self._post_settings()
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted("mock-ok"), self._evidence("mock-ok"), EventSemantics(incident_id="mock-ok"))

        class OkResponse:
            status_code = 200
            text = "ok"

        calls: list[dict] = []

        def fake_post(url: str, json: dict, timeout: float) -> OkResponse:
            calls.append({"url": url, "json": json, "timeout": timeout})
            return OkResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(delivered.delivery_status, "sent")
        self.assertEqual(delivered.attempt_count, 1)
        self.assertIsNotNone(delivered.delivered_at)
        payload = calls[0]["json"]
        self.assertEqual(payload["event_type"], "fall_confirmed")
        self.assertEqual(payload["state"], "fallen_confirmed")
        self.assertEqual(payload["status"], "confirmed_fall")
        self.assertEqual(payload["severity"], "L3")
        self.assertEqual(payload["injury"]["level"], "I3")
        self.assertEqual(payload["delivery_mode"], "post")
        self.assertFalse(payload["dry_run"])
        self.assertNotIn("D:\\", str(payload))

    def test_post_500_retries_then_fails_without_unhandled_exception(self) -> None:
        settings = self._post_settings(event_delivery_retry_limit=2)
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted("mock-500"), self._evidence("mock-500"), EventSemantics(incident_id="mock-500"))

        class FailResponse:
            status_code = 500
            text = "error"

        def fake_post(*args, **kwargs):
            return FailResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            retry = outbox.deliver(record.delivery_id)
            failed = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(retry.delivery_status, "retry")
        self.assertEqual(retry.last_http_status, 500)
        self.assertEqual(failed.delivery_status, "failed")
        self.assertEqual(failed.attempt_count, 2)

    def test_timeout_retries_then_fails_without_unhandled_exception(self) -> None:
        settings = self._post_settings(event_delivery_retry_limit=2)
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted("mock-timeout"), self._evidence("mock-timeout"), EventSemantics(incident_id="mock-timeout"))

        def fake_post(*args, **kwargs):
            raise delivery_module.requests.Timeout("timed out")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            retry = outbox.deliver(record.delivery_id)
            failed = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(retry.delivery_status, "retry")
        self.assertIn("timed out", retry.last_error)
        self.assertEqual(failed.delivery_status, "failed")

    def test_worker_drives_claim_and_delivery_to_sent(self) -> None:
        settings = self._post_settings(event_delivery_worker_enabled=True)
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted("mock-worker"), self._evidence("mock-worker"), EventSemantics(incident_id="mock-worker"))
        worker = DeliveryWorker(settings, outbox)

        class OkResponse:
            status_code = 204
            text = ""

        def fake_post(*args, **kwargs):
            return OkResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = worker.process_once("worker-a")
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(delivered.delivery_status, "sent")
        self.assertEqual(outbox.get(record.delivery_id).delivery_status, "sent")

    def test_same_incident_is_not_duplicated(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        outbox = DeliveryOutbox(settings)

        first = outbox.enqueue(self._trusted("mock-dedup"), self._evidence("mock-dedup"), EventSemantics(incident_id="mock-dedup"))
        second = outbox.enqueue(self._trusted("mock-dedup"), self._evidence("mock-dedup"), EventSemantics(incident_id="mock-dedup"))

        self.assertEqual(second.delivery_id, first.delivery_id)
        self.assertEqual(len(outbox.list_deliveries()), 1)

    @staticmethod
    def _post_settings(**overrides) -> Settings:
        return replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_mode="post",
            event_delivery_target_url="http://mock-main.example/video-bridge/fall-events",
            **overrides,
        )

    @staticmethod
    def _trusted(incident_id: str) -> TrustedEventResult:
        return TrustedEventResult(
            incident_id=incident_id,
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
    def _evidence(incident_id: str) -> EvidencePackage:
        return EvidencePackage(
            incident_id=incident_id,
            camera_id="camera_01",
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    bbox=[10.0, 20.0, 110.0, 220.0],
                    snapshot_url="http://testserver/fall-events/snapshots/mock.jpg",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
