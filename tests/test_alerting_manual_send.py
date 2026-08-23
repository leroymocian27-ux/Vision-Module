from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import alerting_api
from app.core.config import Settings
from app.services.alert_simulator_service import AlertSimulatorService


class _FakeResponse:
    def __init__(self, status_code: int = 200, body: str = '{"accepted":true,"pushed":true}') -> None:
        self.status_code = status_code
        self.text = body


class _ReporterStub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def endpoint_url() -> str:
        return "http://unused.example/api/v1/video-bridge/fall-events"

    @staticmethod
    def request_timeout_seconds() -> float:
        return 2.5

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "endpoint_base_url": "http://unused.example/api/v1",
            "endpoint_path": "/video-bridge/fall-events",
            "dry_run": self.settings.main_system_report_dry_run,
            "token_header": self.settings.main_system_alert_token_header,
        }


class _RuntimeStub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.fall_event_reporter = _ReporterStub(settings)
        self.alert_simulator_service = AlertSimulatorService(reporter=self.fall_event_reporter)


class AlertingManualSendTest(unittest.TestCase):
    def test_send_once_posts_single_alert_with_configured_token_header(self) -> None:
        settings = self._settings()
        service = AlertSimulatorService(reporter=_ReporterStub(settings))
        calls: list[dict[str, Any]] = []

        def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
            calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return _FakeResponse(200, '{"ok":true,"accepted":true,"pushed":true}')

        import app.services.alert_simulator_service as simulator_module

        previous_post = simulator_module.requests.post
        simulator_module.requests.post = fake_post
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
            simulator_module.requests.post = previous_post

        self.assertTrue(first["ok"], first)
        self.assertEqual(first["status_code"], 200)
        self.assertEqual(first["target_url"], "http://192.168.8.254:8000/api/v1/video-bridge/fall-events")
        self.assertNotEqual(first["incident_id"], second["incident_id"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["headers"], {"X-Vision-Service-Token": "test-bridge-token"})
        self.assertEqual(calls[0]["json"]["camera_id"], "camera_01")
        self.assertEqual(calls[0]["json"]["track_id"], "manual-console-probe")
        self.assertEqual(calls[0]["json"]["event_type"], "fall_confirmed")
        self.assertIsInstance(calls[0]["json"]["metadata"].get("event"), dict)
        self.assertEqual(
            calls[0]["json"]["metadata"]["event"]["incident_id"],
            calls[0]["json"]["incident_id"],
        )

    def test_send_once_reports_non_2xx_as_failure(self) -> None:
        service = AlertSimulatorService(reporter=_ReporterStub(self._settings()))

        def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
            del url, json, headers, timeout
            return _FakeResponse(403, "forbidden")

        import app.services.alert_simulator_service as simulator_module

        previous_post = simulator_module.requests.post
        simulator_module.requests.post = fake_post
        try:
            result = service.send_once(
                target_ip="192.168.8.254",
                camera_id="camera_01",
                track_id="manual-console-probe",
                fall_prob=0.91,
            )
        finally:
            simulator_module.requests.post = previous_post

        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status_code"], 403)
        self.assertEqual(result["error"], "forbidden")

    def test_api_requires_target_ip(self) -> None:
        client = self._client()
        response = client.post("/alerting/simulation/send-once", json={})
        self.assertEqual(response.status_code, 422, response.text)

    def test_api_send_once_does_not_start_continuous_simulation(self) -> None:
        calls: list[str] = []

        def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResponse:
            del json, headers, timeout
            calls.append(url)
            return _FakeResponse(200, '{"accepted":true,"pushed":true}')

        import app.services.alert_simulator_service as simulator_module

        previous_post = simulator_module.requests.post
        simulator_module.requests.post = fake_post
        try:
            client = self._client()
            response = client.post(
                "/alerting/simulation/send-once",
                json={"target_ip": "192.168.8.254"},
            )
            status = client.get("/alerting/status")
        finally:
            simulator_module.requests.post = previous_post

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"], response.json())
        self.assertEqual(calls, ["http://192.168.8.254:8000/api/v1/video-bridge/fall-events"])
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
            main_system_base_prefix="/api/v1",
            main_system_fall_event_path="/video-bridge/fall-events",
        )

    def _client(self, settings: Settings | None = None) -> TestClient:
        runtime = _RuntimeStub(settings or self._settings())
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(alerting_api.router)
        return TestClient(app)


if __name__ == "__main__":
    unittest.main()
