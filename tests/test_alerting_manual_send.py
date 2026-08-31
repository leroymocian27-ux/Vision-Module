from __future__ import annotations

import unittest
from dataclasses import replace
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerting_api
from app.core.config import Settings
from app.services.alert_outbox_service import AlertOutboxService
from app.services.alert_simulator_service import AlertSimulatorService
from app.services.fall_event_reporter_service import FallEventReporterService

import app.services.fall_event_reporter_service as reporter_module


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: str = '{"accepted":true,"pushed":true}') -> None:
        self.status_code = status_code
        self.text = body


class _SourceManagerStub:
    pass


class _RuntimeStub:
    def __init__(self, settings: Settings) -> None:
        self._temp_dir = TemporaryDirectory()
        self.settings = replace(
            settings,
            test_event_root=self._temp_dir.name,
            alert_outbox_enabled=True,
            alert_outbox_path=f"{self._temp_dir.name}/alert_outbox.sqlite3",
        )
        self.fall_event_reporter = FallEventReporterService(
            settings=self.settings,
            source_manager=_SourceManagerStub(),
            alert_outbox=AlertOutboxService(self.settings),
        )
        self.alert_simulator_service = AlertSimulatorService(reporter=self.fall_event_reporter)


class AlertingManualSendTest(unittest.TestCase):
    def test_send_once_posts_single_alert_with_configured_token_header(self) -> None:
        settings = self._settings()
        with TemporaryDirectory() as temp_dir:
            settings = replace(settings, test_event_root=temp_dir, alert_outbox_enabled=True, alert_outbox_path=f"{temp_dir}/alert_outbox.sqlite3")
            reporter = FallEventReporterService(settings=settings, source_manager=_SourceManagerStub(), alert_outbox=AlertOutboxService(settings))
            service = AlertSimulatorService(reporter=reporter)
            calls: list[dict[str, Any]] = []

            def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
                calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
                return _FakeResponse(200, '{"ok":true,"accepted":true,"pushed":true}')

            previous_post = reporter_module.requests.post
            reporter_module.requests.post = fake_post
            try:
                first = service.send_once(
                    target_ip="192.168.8.254",
                    camera_id="camera_01",
                    track_id="manual-console-probe",
                    fall_prob=0.91,
                )
                second = service.send_once(
                    target_ip="192.168.8.254",
                    camera_id="camera_01",
                    track_id="manual-console-probe",
                    fall_prob=0.91,
                )
            finally:
                reporter_module.requests.post = previous_post

            self.assertTrue(first["ok"], first)
            self.assertEqual(first["status_code"], 200)
            self.assertEqual(first["target_url"], "http://192.168.8.254:8000/api/integrations/fall-detection/alerts")
            self.assertNotEqual(first["incident_id"], second["incident_id"])
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]["headers"], {"X-Vision-Service-Token": "test-bridge-token"})
            self.assertEqual(calls[0]["json"]["camera_id"], "camera_01")
            self.assertEqual(calls[0]["json"]["track_id"], "manual-console-probe")
            self.assertEqual(calls[0]["json"]["schema_version"], "1.0")
            self.assertEqual(calls[0]["json"]["safety_outcome"], "alert")
            self.assertTrue(calls[0]["json"]["test_event"])
            self.assertIsInstance(calls[0]["json"]["legacy_payload"]["metadata"].get("event"), dict)
            self.assertEqual(
                calls[0]["json"]["legacy_payload"]["metadata"]["event"]["incident_id"],
                calls[0]["json"]["incident_id"],
            )

    def test_send_once_does_not_prequeue_pending_before_sync_post(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(
                self._settings(),
                test_event_root=temp_dir,
                alert_outbox_enabled=True,
                alert_outbox_path=f"{temp_dir}/alert_outbox.sqlite3",
            )
            outbox = AlertOutboxService(settings)
            reporter = FallEventReporterService(
                settings=settings,
                source_manager=_SourceManagerStub(),
                alert_outbox=outbox,
            )
            service = AlertSimulatorService(reporter=reporter)
            pending_counts_seen_at_post: list[int] = []
            calls: list[dict[str, Any]] = []

            def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
                del headers, timeout
                pending_counts_seen_at_post.append(outbox.status().pending_count)
                calls.append({"url": url, "json": json})
                return _FakeResponse(200, f'{{"ok":true,"event_id":"{json["event_id"]}","duplicate":false}}')

            previous_post = reporter_module.requests.post
            reporter_module.requests.post = fake_post
            try:
                result = service.send_once(
                    target_ip="192.168.8.254",
                    event_id="manual-single-post-001",
                    camera_id="camera_01",
                    track_id="manual-console-probe",
                    fall_prob=0.91,
                )
            finally:
                reporter_module.requests.post = previous_post

            self.assertTrue(result["ok"], result)
            self.assertEqual(len(calls), 1)
            self.assertEqual(pending_counts_seen_at_post, [0])
            self.assertEqual(outbox.status().delivered_count, 1)
            delivery = reporter._delivery_record(calls[0]["json"])  # type: ignore[attr-defined]
            self.assertEqual(delivery["status"], "delivered")
            self.assertEqual(delivery["attempts"], 1)

    def test_send_once_reports_non_2xx_as_failure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(self._settings(), test_event_root=temp_dir, alert_outbox_enabled=True, alert_outbox_path=f"{temp_dir}/alert_outbox.sqlite3")
            reporter = FallEventReporterService(settings=settings, source_manager=_SourceManagerStub(), alert_outbox=AlertOutboxService(settings))
            service = AlertSimulatorService(reporter=reporter)

            def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
                del url, json, headers, timeout
                return _FakeResponse(403, "forbidden")

            previous_post = reporter_module.requests.post
            reporter_module.requests.post = fake_post
            try:
                result = service.send_once(
                    target_ip="192.168.8.254",
                    camera_id="camera_01",
                    track_id="manual-console-probe",
                    fall_prob=0.91,
                )
            finally:
                reporter_module.requests.post = previous_post

            self.assertFalse(result["ok"], result)
            self.assertEqual(result["status_code"], 403)
            self.assertEqual(result["error"], "forbidden")

    def test_send_once_can_reuse_event_id_for_duplicate_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            settings = replace(self._settings(), test_event_root=temp_dir, alert_outbox_enabled=True, alert_outbox_path=f"{temp_dir}/alert_outbox.sqlite3")
            reporter = FallEventReporterService(settings=settings, source_manager=_SourceManagerStub(), alert_outbox=AlertOutboxService(settings))
            service = AlertSimulatorService(reporter=reporter)

            def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
                del url, headers, timeout
                return _FakeResponse(200, f'{{"ok":true,"event_id":"{json["event_id"]}","duplicate":true}}')

            previous_post = reporter_module.requests.post
            reporter_module.requests.post = fake_post
            try:
                result = service.send_once(
                    target_ip="192.168.8.254",
                    event_id="manual-duplicate-001",
                    camera_id="camera_01",
                    track_id="manual-console-probe",
                    fall_prob=0.91,
                )
            finally:
                reporter_module.requests.post = previous_post

            self.assertTrue(result["ok"], result)
            self.assertEqual(result["incident_id"], "manual-duplicate-001")
            self.assertIn('"duplicate": true', result["response_body"])

    def test_api_can_use_configured_endpoint_without_target_ip(self) -> None:
        calls: list[str] = []

        def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
            del json, headers, timeout
            calls.append(url)
            return _FakeResponse(200, '{"ok":true}')

        previous_post = reporter_module.requests.post
        reporter_module.requests.post = fake_post
        try:
            client = self._client()
            response = client.post("/alerting/simulation/send-once", json={})
        finally:
            reporter_module.requests.post = previous_post

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"], response.json())
        self.assertEqual(calls, ["http://unused.example/api/integrations/fall-detection/alerts"])

    def test_api_send_once_does_not_start_continuous_simulation(self) -> None:
        calls: list[str] = []

        def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
            del json, headers, timeout
            calls.append(url)
            return _FakeResponse(200, '{"accepted":true,"pushed":true}')

        previous_post = reporter_module.requests.post
        reporter_module.requests.post = fake_post
        try:
            client = self._client()
            response = client.post(
                "/alerting/simulation/send-once",
                json={"target_ip": "192.168.8.254"},
            )
            status = client.get("/alerting/status")
        finally:
            reporter_module.requests.post = previous_post

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"], response.json())
        self.assertEqual(calls, ["http://192.168.8.254:8000/api/integrations/fall-detection/alerts"])
        self.assertFalse(status.json()["simulation"]["running"], status.text)

    def test_status_exposes_dry_run_and_header_without_token_value(self) -> None:
        client = self._client(
            replace(
                self._settings(),
                main_system_report_dry_run=True,
                main_system_alert_token="secret-token-that-must-not-leak",
            )
        )

        response = client.get("/alerting/status")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["endpoint"]["dry_run"])
        self.assertEqual(body["endpoint"]["token_header"], "X-Vision-Service-Token")
        self.assertNotIn("secret-token-that-must-not-leak", response.text)

    @staticmethod
    def _settings() -> Settings:
        return replace(
            Settings(),
            main_system_alert_token="test-bridge-token",
            main_system_alert_token_header="X-Vision-Service-Token",
            main_system_default_port=8000,
            main_system_base_prefix="",
            main_system_alert_enabled=True,
            main_system_report_dry_run=False,
            main_system_base_url="http://unused.example",
            main_system_alert_path="/api/integrations/fall-detection/alerts",
            main_system_fall_event_path="/api/integrations/fall-detection/alerts",
        )

    def _client(self, settings: Settings | None = None) -> TestClient:
        runtime = _RuntimeStub(settings or self._settings())
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(alerting_api.router)
        return TestClient(app)


if __name__ == "__main__":
    unittest.main()
