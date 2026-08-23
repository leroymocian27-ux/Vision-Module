from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox, build_main_system_payload
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryOutboxTest(unittest.TestCase):
    def _trusted(self) -> TrustedEventResult:
        return TrustedEventResult(incident_id="delivery-1", support_fall_alarm=True, final_event_type="fallen_confirmed", final_risk_level="critical", confidence=0.9, explanation="confirmed", alarm_title="fall", alarm_body="fall", recommended_action="check")

    def _evidence(self) -> EvidencePackage:
        return EvidencePackage(
            incident_id="delivery-1",
            camera_id="camera_01",
            track_id=7,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
            fall_evidence_score=0.92,
            keyframes=[
                EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    bbox=[10.0, 20.0, 110.0, 220.0],
                    snapshot_url="http://testserver/fall-events/snapshots/delivery-1.jpg",
                )
            ],
        )

    def test_disabled_delivery_does_not_post_even_if_deliver_is_called(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=False, event_delivery_mode="post")
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("disabled delivery must not call HTTP POST")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(calls, [])
        self.assertIsNotNone(delivered)
        self.assertEqual(delivered.delivery_status, "pending")

    def test_dry_run_generates_compatible_payload_without_posting(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        outbox = DeliveryOutbox(settings)
        calls: list[dict] = []

        def fake_post(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            raise AssertionError("dry-run must not call HTTP POST")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(calls, [])
        self.assertIsNotNone(delivered)
        self.assertEqual(delivered.delivery_status, "dry_run_sent")
        self.assertEqual(delivered.delivery_mode, "dry_run")
        self.assertTrue(delivered.dry_run)
        self.assertIsNone(delivered.delivered_at)
        payload = build_main_system_payload(self._trusted(), self._evidence())
        self.assertTrue(
            {
                "incident_id",
                "camera_id",
                "event_type",
                "state",
                "status",
                "risk",
                "risk_level",
                "severity",
                "fall_detected",
                "fall_prob",
                "fall_score",
                "track_id",
                "bbox",
                "snapshot_url",
                "timestamp",
                "injury",
                "explanation",
                "recommended_action",
                "delivery_mode",
                "dry_run",
                "degradation_used",
                "review_result",
            }.issubset(payload)
        )

    def test_post_success_marks_sent(self) -> None:
        settings = replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_mode="post",
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
        )
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

        class FakeResponse:
            status_code = 204
            text = ""

        calls: list[dict] = []

        def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(len(calls), 1)
        self.assertIsNotNone(delivered)
        self.assertEqual(delivered.delivery_status, "sent")
        self.assertEqual(delivered.delivery_mode, "post")
        self.assertFalse(delivered.dry_run)
        self.assertEqual(delivered.attempt_count, 1)
        self.assertEqual(delivered.last_http_status, 204)
        self.assertIsNotNone(delivered.delivered_at)

    def test_post_failure_records_retry_then_failed_without_dropping_record(self) -> None:
        settings = replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_mode="post",
            event_delivery_retry_limit=2,
            event_delivery_retry_backoff_seconds=1.0,
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
        )
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

        class FakeResponse:
            status_code = 503
            text = "unavailable"

        calls: list[dict] = []

        def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            first = outbox.deliver(record.delivery_id)
            second = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(first)
        self.assertEqual(first.delivery_status, "retry")
        self.assertEqual(first.attempt_count, 1)
        self.assertEqual(first.last_http_status, 503)
        self.assertIsNotNone(first.next_retry_at)
        self.assertIsNotNone(second)
        self.assertEqual(second.delivery_status, "failed")
        self.assertEqual(second.attempt_count, 2)
        self.assertEqual(outbox.for_incident("delivery-1").delivery_status, "failed")

    def test_request_exception_records_retry(self) -> None:
        settings = replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_mode="post",
            event_delivery_retry_limit=3,
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
        )
        outbox = DeliveryOutbox(settings)
        record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

        def fake_post(*args, **kwargs):
            raise delivery_module.requests.RequestException("network down")

        previous_post = delivery_module.requests.post
        delivery_module.requests.post = fake_post
        try:
            delivered = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous_post

        self.assertIsNotNone(delivered)
        self.assertEqual(delivered.delivery_status, "retry")
        self.assertEqual(delivered.attempt_count, 1)
        self.assertIsNone(delivered.last_http_status)
        self.assertEqual(delivered.last_error, "network down")
        self.assertIsNotNone(delivered.next_retry_at)

    def test_same_incident_reuses_existing_delivery_record(self) -> None:
        settings = replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run")
        outbox = DeliveryOutbox(settings)

        first = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))
        second = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

        self.assertEqual(second.delivery_id, first.delivery_id)
        self.assertEqual(len(outbox._records), 1)  # type: ignore[attr-defined]
