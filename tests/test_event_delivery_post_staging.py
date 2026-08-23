from __future__ import annotations

import unittest
from dataclasses import replace

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryPostStagingTest(unittest.TestCase):
    def test_disabled_and_dry_run_never_post(self) -> None:
        for settings in (
            replace(Settings(), event_delivery_enabled=False, event_delivery_mode="post", event_delivery_target_url="http://main.example/events"),
            replace(Settings(), event_delivery_enabled=True, event_delivery_mode="dry_run", event_delivery_target_url="http://main.example/events"),
        ):
            with self.subTest(enabled=settings.event_delivery_enabled, mode=settings.event_delivery_mode):
                outbox = DeliveryOutbox(settings)
                record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="post-stage"))
                calls = []

                def fake_post(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise AssertionError("must not post")

                previous = delivery_module.requests.post
                delivery_module.requests.post = fake_post
                try:
                    delivered = outbox.deliver(record.delivery_id)
                finally:
                    delivery_module.requests.post = previous

                self.assertEqual(calls, [])
                self.assertIn(delivered.delivery_status, {"pending", "dry_run_sent"})

    def test_post_2xx_marks_sent_and_non_2xx_retries(self) -> None:
        for code, expected in ((200, "sent"), (201, "sent"), (204, "sent"), (400, "retry"), (500, "retry")):
            with self.subTest(code=code):
                outbox = DeliveryOutbox(self._settings(event_delivery_retry_limit=3))
                record = outbox.enqueue(self._trusted(f"post-stage-{code}"), self._evidence(f"post-stage-{code}"), EventSemantics(incident_id=f"post-stage-{code}"))

                class Response:
                    status_code = code

                previous = delivery_module.requests.post
                delivery_module.requests.post = lambda *args, **kwargs: Response()
                try:
                    delivered = outbox.deliver(record.delivery_id)
                finally:
                    delivery_module.requests.post = previous

                self.assertEqual(delivered.delivery_status, expected)
                if expected == "retry":
                    self.assertEqual(delivered.last_http_status, code)
                    self.assertIsNotNone(delivered.next_retry_at)

    def test_timeout_retries_then_retry_limit_fails(self) -> None:
        outbox = DeliveryOutbox(self._settings(event_delivery_retry_limit=2))
        record = outbox.enqueue(self._trusted("post-stage-timeout"), self._evidence("post-stage-timeout"), EventSemantics(incident_id="post-stage-timeout"))

        def timeout(*args, **kwargs):
            raise delivery_module.requests.Timeout("request timed out")

        previous = delivery_module.requests.post
        delivery_module.requests.post = timeout
        try:
            retry = outbox.deliver(record.delivery_id)
            failed = outbox.deliver(record.delivery_id)
        finally:
            delivery_module.requests.post = previous

        self.assertEqual(retry.delivery_status, "retry")
        self.assertIn("timed out", retry.last_error)
        self.assertEqual(failed.delivery_status, "failed")

    def test_missing_target_does_not_post_and_keeps_retry_record(self) -> None:
        outbox = DeliveryOutbox(replace(Settings(), event_delivery_enabled=True, event_delivery_mode="post", event_delivery_target_url=""))
        record = outbox.enqueue(self._trusted("post-stage-missing-target"), self._evidence("post-stage-missing-target"), EventSemantics(incident_id="post-stage-missing-target"))

        delivered = outbox.deliver(record.delivery_id)

        self.assertEqual(delivered.delivery_status, "retry")
        self.assertEqual(delivered.last_error, "missing_event_delivery_target_url")

    @staticmethod
    def _settings(**overrides) -> Settings:
        return replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_mode="post",
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
            **overrides,
        )

    @staticmethod
    def _trusted(incident_id: str = "post-stage") -> TrustedEventResult:
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
    def _evidence(incident_id: str = "post-stage") -> EvidencePackage:
        return EvidencePackage(incident_id=incident_id, camera_id="camera_01", trigger_timestamp="2026-07-18T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
