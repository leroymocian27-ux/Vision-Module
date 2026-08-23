from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliverySQLiteOutboxTest(unittest.TestCase):
    def test_sqlite_records_survive_outbox_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "delivery.sqlite3", event_delivery_mode="dry_run")
            first_outbox = DeliveryOutbox(settings)
            record = first_outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

            second_outbox = DeliveryOutbox(settings)
            by_id = second_outbox.get(record.delivery_id)
            by_incident = second_outbox.for_incident("delivery-1")
            latest = second_outbox.latest_for_camera("camera_01")

            self.assertIsNotNone(by_id)
            self.assertEqual(by_id.incident_id, "delivery-1")
            self.assertIsNotNone(by_incident)
            self.assertEqual(by_incident.delivery_id, record.delivery_id)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.delivery_id, record.delivery_id)

    def test_same_incident_enqueue_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = DeliveryOutbox(self._settings(Path(temp_dir) / "delivery.sqlite3"))

            first = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))
            second = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

            self.assertEqual(second.delivery_id, first.delivery_id)
            self.assertEqual(len(outbox.list_deliveries()), 1)
            self.assertEqual(second.payload_json, first.payload_json)

    def test_claim_respects_retry_due_time_and_lock_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = DeliveryOutbox(self._settings(Path(temp_dir) / "delivery.sqlite3"))
            pending = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))

            claimed = outbox.claim_next("worker-a", 30)
            self.assertIsNotNone(claimed)
            self.assertEqual(claimed.delivery_id, pending.delivery_id)
            self.assertIsNone(outbox.claim_next("worker-b", 30))

            expired = claimed.model_copy(
                update={
                    "lock_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="milliseconds")
                }
            )
            outbox._sqlite_store(expired)  # type: ignore[attr-defined]
            reclaimed = outbox.claim_next("worker-b", 30)
            self.assertIsNotNone(reclaimed)
            self.assertEqual(reclaimed.delivery_id, pending.delivery_id)

            future_retry = reclaimed.model_copy(
                update={
                    "delivery_status": "retry",
                    "lock_owner": None,
                    "lock_token": None,
                    "lock_until": None,
                    "next_retry_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="milliseconds"),
                }
            )
            outbox._sqlite_store(future_retry)  # type: ignore[attr-defined]
            self.assertIsNone(outbox.claim_next("worker-c", 30))

            due_retry = future_retry.model_copy(
                update={"next_retry_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="milliseconds")}
            )
            outbox._sqlite_store(due_retry)  # type: ignore[attr-defined]
            self.assertIsNotNone(outbox.claim_next("worker-c", 30))

    def test_sqlite_dry_run_does_not_post(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = DeliveryOutbox(self._settings(Path(temp_dir) / "delivery.sqlite3", event_delivery_mode="dry_run"))
            record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="delivery-1"))
            calls: list[dict] = []

            def fake_post(*args, **kwargs):
                calls.append({"args": args, "kwargs": kwargs})
                raise AssertionError("dry-run must not call HTTP POST")

            previous_post = delivery_module.requests.post
            delivery_module.requests.post = fake_post
            try:
                delivered = outbox.deliver(record.delivery_id)
            finally:
                delivery_module.requests.post = previous_post

            self.assertEqual(calls, [])
            self.assertIsNotNone(delivered)
            self.assertEqual(delivered.delivery_status, "dry_run_sent")
            self.assertTrue(delivered.dry_run)
            self.assertEqual(delivered.delivery_mode, "dry_run")
            self.assertEqual(outbox.get(record.delivery_id).delivery_status, "dry_run_sent")

    def test_sqlite_post_success_and_failure_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "delivery.sqlite3"
            success_outbox = DeliveryOutbox(self._settings(path, event_delivery_mode="post", event_delivery_retry_limit=2))
            success_record = success_outbox.enqueue(self._trusted("delivery-ok"), self._evidence("delivery-ok"), EventSemantics(incident_id="delivery-ok"))

            class OkResponse:
                status_code = 200
                text = "ok"

            def ok_post(*args, **kwargs):
                return OkResponse()

            previous_post = delivery_module.requests.post
            delivery_module.requests.post = ok_post
            try:
                sent = success_outbox.deliver(success_record.delivery_id)
            finally:
                delivery_module.requests.post = previous_post

            self.assertIsNotNone(sent)
            self.assertEqual(sent.delivery_status, "sent")
            self.assertEqual(sent.attempt_count, 1)
            self.assertIsNotNone(sent.delivered_at)

            fail_outbox = DeliveryOutbox(self._settings(path, event_delivery_mode="post", event_delivery_retry_limit=2))
            fail_record = fail_outbox.enqueue(self._trusted("delivery-fail"), self._evidence("delivery-fail"), EventSemantics(incident_id="delivery-fail"))

            class FailResponse:
                status_code = 500
                text = "error"

            def fail_post(*args, **kwargs):
                return FailResponse()

            previous_post = delivery_module.requests.post
            delivery_module.requests.post = fail_post
            try:
                retry = fail_outbox.deliver(fail_record.delivery_id)
                failed = fail_outbox.deliver(fail_record.delivery_id)
            finally:
                delivery_module.requests.post = previous_post

            self.assertEqual(retry.delivery_status, "retry")
            self.assertEqual(retry.last_http_status, 500)
            self.assertEqual(failed.delivery_status, "failed")
            self.assertEqual(failed.last_http_status, 500)
            self.assertEqual(failed.attempt_count, 2)

    def test_sqlite_request_exception_records_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outbox = DeliveryOutbox(self._settings(Path(temp_dir) / "delivery.sqlite3", event_delivery_mode="post"))
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
            self.assertEqual(delivered.last_error, "network down")
            self.assertIsNone(delivered.last_http_status)

    @staticmethod
    def _settings(path: Path, **overrides) -> Settings:
        return replace(
            Settings(),
            event_delivery_enabled=True,
            event_delivery_backend="sqlite",
            event_delivery_sqlite_path=str(path),
            event_delivery_target_url="http://main.example/video-bridge/fall-events",
            **overrides,
        )

    @staticmethod
    def _trusted(incident_id: str = "delivery-1") -> TrustedEventResult:
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
    def _evidence(incident_id: str = "delivery-1") -> EvidencePackage:
        return EvidencePackage(
            incident_id=incident_id,
            camera_id="camera_01",
            track_id=7,
            trigger_timestamp="2026-07-17T09:30:00+00:00",
            fall_probability=0.9,
            keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, snapshot_url="http://testserver/event.jpg")],
        )


if __name__ == "__main__":
    unittest.main()
