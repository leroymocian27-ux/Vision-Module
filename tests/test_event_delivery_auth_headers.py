from __future__ import annotations

import unittest
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from app.core.config import Settings
import app.events.delivery as delivery_module
from app.events.delivery import DeliveryOutbox
from app.events.schemas import EvidencePackage, EventSemantics, TrustedEventResult


class EventDeliveryAuthHeadersTest(unittest.TestCase):
    def test_loopback_mock_server_receives_configured_header(self) -> None:
        received: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                content_length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(content_length)
                received["token"] = self.headers.get("X-Vision-Service-Token")
                self.send_response(200)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            settings = replace(
                Settings(), event_delivery_enabled=True, event_delivery_mode="post",
                event_delivery_target_url=f"http://{host}:{port}/mock-only",
                main_system_alert_token_header="X-Vision-Service-Token",
                main_system_alert_token="loopback-secret",
            )
            outbox = DeliveryOutbox(settings)
            record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="auth-header"))
            self.assertEqual(outbox.deliver(record.delivery_id).delivery_status, "sent")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(received["token"], "loopback-secret")

    def test_post_sends_token_header_only_when_both_values_are_configured(self) -> None:
        cases = [
            ("", "", None),
            ("X-Test-Token", "", None),
            ("", "secret", None),
            ("X-Test-Token", "secret", {"X-Test-Token": "secret"}),
        ]
        for header_name, token, expected_headers in cases:
            with self.subTest(header_name=header_name, has_token=bool(token)):
                settings = replace(
                    Settings(),
                    event_delivery_enabled=True,
                    event_delivery_mode="post",
                    event_delivery_target_url="http://127.0.0.1:9/mock-only",
                    main_system_alert_token_header=header_name,
                    main_system_alert_token=token,
                )
                outbox = DeliveryOutbox(settings)
                record = outbox.enqueue(self._trusted(), self._evidence(), EventSemantics(incident_id="auth-header"))
                calls = []

                class Response:
                    status_code = 200

                previous = delivery_module.requests.post
                delivery_module.requests.post = lambda *args, **kwargs: calls.append((args, kwargs)) or Response()
                try:
                    delivered = outbox.deliver(record.delivery_id)
                finally:
                    delivery_module.requests.post = previous

                self.assertEqual(delivered.delivery_status, "sent")
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][1].get("headers"), expected_headers)

    @staticmethod
    def _trusted() -> TrustedEventResult:
        return TrustedEventResult(
            incident_id="auth-header", support_fall_alarm=True,
            final_event_type="fallen_confirmed", final_risk_level="critical",
            confidence=0.9, explanation="confirmed", alarm_title="fall",
            alarm_body="fall", recommended_action="check",
        )

    @staticmethod
    def _evidence() -> EvidencePackage:
        return EvidencePackage(incident_id="auth-header", camera_id="camera_01", trigger_timestamp="2026-07-18T10:00:00+00:00")
