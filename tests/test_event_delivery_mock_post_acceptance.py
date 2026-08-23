from __future__ import annotations

import json
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.config import Settings
from app.events.delivery import DeliveryOutbox
from app.events.delivery_worker import DeliveryWorker
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryMockPostAcceptanceTest(unittest.TestCase):
    def test_loopback_mock_post_state_transitions_and_failure_modes(self) -> None:
        with TemporaryDirectory() as temp_dir, _LoopbackMockMainSystem() as mock:
            db_path = Path(temp_dir) / "event_delivery_outbox.sqlite3"
            settings = replace(
                Settings(),
                event_delivery_enabled=True,
                event_delivery_mode="post",
                event_delivery_backend="sqlite",
                event_delivery_sqlite_path=str(db_path),
                event_delivery_worker_enabled=True,
                event_delivery_retry_limit=2,
                event_delivery_retry_backoff_seconds=30.0,
                event_delivery_claim_ttl_seconds=15.0,
                main_system_alert_enabled=False,
                main_system_alert_timeout_ms=200,
            )
            outbox = DeliveryOutbox(settings)
            worker = DeliveryWorker(settings, outbox)
            snapshots: list[dict[str, Any]] = []

            def capture(path: str, payload: dict[str, Any]) -> None:
                record = outbox.for_incident(payload["incident_id"])
                snapshots.append({
                    "path": path,
                    "incident_id": payload["incident_id"],
                    "delivery_status": record.delivery_status if record else None,
                    "lock_owner": record.lock_owner if record else None,
                    "lock_token": record.lock_token if record else None,
                    "lock_until": record.lock_until if record else None,
                })

            mock.capture = capture
            success = self._enqueue(outbox, "mock-post-success", mock.url("/success"))

            self.assertEqual(success.delivery_status, "pending")
            sent = worker.process_once("mock-worker-success")
            self.assertEqual(sent.delivery_id, success.delivery_id)
            self.assertEqual(sent.delivery_status, "sent")
            self.assertEqual(sent.attempt_count, 1)
            self.assertIsNone(sent.lock_owner)
            self.assertIsNone(sent.lock_token)
            self.assertIsNone(sent.lock_until)

            server_error = self._enqueue(outbox, "mock-post-500", mock.url("/server-error"))
            retry = worker.process_once("mock-worker-500")
            self.assertEqual(retry.delivery_id, server_error.delivery_id)
            self.assertEqual(retry.delivery_status, "retry")
            self.assertEqual(retry.attempt_count, 1)
            self.assertEqual(retry.last_http_status, 500)
            self.assertIsNotNone(retry.next_retry_at)
            self.assertGreater(self._parse_time(retry.next_retry_at), datetime.now(timezone.utc))
            self.assertIsNone(retry.lock_owner)
            self.assertIsNone(worker.process_once("mock-worker-before-backoff"))

            self._make_retry_due(outbox, retry.delivery_id)
            failed = worker.process_once("mock-worker-500-retry")
            self.assertEqual(failed.delivery_id, server_error.delivery_id)
            self.assertEqual(failed.delivery_status, "failed")
            self.assertEqual(failed.attempt_count, 2)
            self.assertEqual(failed.last_http_status, 500)
            self.assertIsNone(failed.lock_owner)
            self.assertIsNone(failed.lock_token)
            self.assertIsNone(failed.lock_until)

            timeout = self._enqueue(outbox, "mock-post-timeout", mock.url("/timeout"))
            timeout_retry = worker.process_once("mock-worker-timeout")
            self.assertEqual(timeout_retry.delivery_id, timeout.delivery_id)
            self.assertEqual(timeout_retry.delivery_status, "retry")
            self.assertIn("timed out", (timeout_retry.last_error or "").lower())
            self.assertIsNone(timeout_retry.last_http_status)
            self.assertIsNotNone(timeout_retry.next_retry_at)

            invalid_body = self._enqueue(outbox, "mock-post-invalid-body", mock.url("/invalid-body"))
            invalid_sent = worker.process_once("mock-worker-invalid-body")
            self.assertEqual(invalid_sent.delivery_id, invalid_body.delivery_id)
            self.assertEqual(invalid_sent.delivery_status, "sent")
            self.assertEqual(invalid_sent.last_http_status, 200)
            self.assertEqual(mock.requests_by_path["/success"], 1)
            self.assertEqual(mock.requests_by_path["/server-error"], 2)
            self.assertEqual(mock.requests_by_path["/timeout"], 1)
            self.assertEqual(mock.requests_by_path["/invalid-body"], 1)

            sending_snapshots = [item for item in snapshots if item["delivery_status"] == "sending"]
            self.assertEqual(len(sending_snapshots), 5)
            for snapshot in sending_snapshots:
                self.assertTrue(snapshot["lock_owner"])
                self.assertTrue(snapshot["lock_token"])
                self.assertIsNotNone(snapshot["lock_until"])
                self.assertGreater(self._parse_time(snapshot["lock_until"]), datetime.now(timezone.utc) - timedelta(seconds=1))

    @staticmethod
    def _enqueue(outbox: DeliveryOutbox, incident_id: str, target_url: str):
        outbox.settings = replace(outbox.settings, event_delivery_target_url=target_url)
        return outbox.enqueue(
            TrustedEventResult(
                incident_id=incident_id,
                support_fall_alarm=True,
                final_event_type="fallen_confirmed",
                final_risk_level="critical",
                confidence=0.94,
                explanation="mock post acceptance",
                alarm_title="fall",
                alarm_body="fall confirmed",
                recommended_action="inspect immediately",
            ),
            EvidencePackage(
                incident_id=incident_id,
                camera_id="camera_01",
                track_id=73,
                trigger_timestamp="2026-07-18T10:15:00+00:00",
                fall_probability=0.94,
                keyframes=[EvidenceKeyframe(
                    role="trigger",
                    offset_ms=0,
                    bbox=[100.0, 120.0, 310.0, 340.0],
                    snapshot_url=f"http://testserver/fall-events/snapshots/{incident_id}.jpg",
                )],
            ),
            EventSemantics(incident_id=incident_id),
        )

    @staticmethod
    def _make_retry_due(outbox: DeliveryOutbox, delivery_id: str) -> None:
        retry = outbox.get(delivery_id)
        assert retry is not None
        outbox._sqlite_store(retry.model_copy(update={  # type: ignore[attr-defined]
            "next_retry_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="milliseconds"),
            "lock_owner": None,
            "lock_token": None,
            "lock_until": None,
        }))

    @staticmethod
    def _parse_time(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


class _LoopbackMockMainSystem:
    def __init__(self) -> None:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests_by_path[self.path] = outer.requests_by_path.get(self.path, 0) + 1
                if outer.capture is not None:
                    outer.capture(self.path, payload)
                if self.path == "/timeout":
                    time.sleep(0.5)
                self.send_response(500 if self.path == "/server-error" else 200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                body = b"{not-json" if self.path == "/invalid-body" else b'{"accepted":true}'
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def log_message(self, format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="mock-main-system", daemon=True)
        self.requests_by_path: dict[str, int] = {}
        self.capture = None

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def url(self, path: str) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}{path}"
