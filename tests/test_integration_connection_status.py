from __future__ import annotations

import unittest
from dataclasses import replace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import integration_api
from app.core.config import Settings


class _RuntimeStub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.source_manager = _SourceManagerStub(settings.default_camera_id)


class _SourceRuntimeStub:
    def __init__(self, camera_id: str) -> None:
        self.config = type("Config", (), {"camera_id": camera_id})()


class _WorkerStatusStub:
    def __init__(self, *, running: bool) -> None:
        self.running = running


class _SourceManagerStub:
    def __init__(self, camera_id: str) -> None:
        self._camera_id = camera_id

    def list_runtimes(self):
        return [_SourceRuntimeStub(self._camera_id)]

    def worker_status(self, camera_id: str):
        if camera_id != self._camera_id:
            return None
        return _WorkerStatusStub(running=True)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class IntegrationConnectionStatusTest(unittest.TestCase):
    def test_connection_status_returns_structured_online_payload(self) -> None:
        settings = replace(
            Settings(),
            default_camera_id="camera_01",
            vision_service_public_base_url="http://192.168.8.254:8000",
            main_system_base_url="http://192.168.8.253:8000/api/v1",
            main_system_alert_timeout_ms=2500,
        )

        def fake_get(url: str, timeout: float):
            self.assertEqual(url, "http://192.168.8.253:8000/healthz")
            self.assertGreater(timeout, 0)
            return _FakeResponse(200)

        import app.api.integration_api as module

        previous_get = module.requests.get
        module.requests.get = fake_get
        try:
            client = self._client(settings)
            response = client.get("/integration/connection-status")
        finally:
            module.requests.get = previous_get

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["vision_service"]["base_url"], "http://192.168.8.254:8000")
        self.assertEqual(payload["vision_service"]["status"], "online")
        self.assertEqual(payload["main_system"]["base_url"], "http://192.168.8.253:8000")
        self.assertEqual(payload["main_system"]["status"], "online")
        self.assertEqual(payload["camera"]["camera_id"], "camera_01")
        self.assertIsInstance(payload["timestamp"], str)

    def test_connection_status_returns_timeout_without_raising(self) -> None:
        settings = replace(
            Settings(),
            default_camera_id="camera_01",
            vision_service_public_base_url="http://192.168.8.254:8000",
            main_system_base_url="http://192.168.8.253:8000/api/v1",
            main_system_alert_timeout_ms=2500,
        )

        import app.api.integration_api as module
        import requests

        def fake_get(url: str, timeout: float):
            del url, timeout
            raise requests.Timeout("timeout")

        previous_get = module.requests.get
        module.requests.get = fake_get
        try:
            client = self._client(settings)
            response = client.get("/integration/connection-status")
        finally:
            module.requests.get = previous_get

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["main_system"]["status"], "timeout")

    def test_connection_status_returns_connection_error_without_raising(self) -> None:
        settings = replace(
            Settings(),
            default_camera_id="camera_01",
            vision_service_public_base_url="http://192.168.8.254:8000",
            main_system_base_url="http://192.168.8.253:8000/api/v1",
            main_system_alert_timeout_ms=2500,
        )

        import app.api.integration_api as module
        import requests

        def fake_get(url: str, timeout: float):
            del url, timeout
            raise requests.ConnectionError("connection failed")

        previous_get = module.requests.get
        module.requests.get = fake_get
        try:
            client = self._client(settings)
            response = client.get("/integration/connection-status")
        finally:
            module.requests.get = previous_get

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["main_system"]["status"], "connection_error")

    def test_connection_status_returns_unavailable_for_http_error(self) -> None:
        settings = replace(
            Settings(),
            default_camera_id="camera_01",
            vision_service_public_base_url="http://192.168.8.254:8000",
            main_system_base_url="http://192.168.8.253:8000/api/v1",
            main_system_alert_timeout_ms=2500,
        )

        def fake_get(url: str, timeout: float):
            del url, timeout
            return _FakeResponse(503)

        import app.api.integration_api as module

        previous_get = module.requests.get
        module.requests.get = fake_get
        try:
            client = self._client(settings)
            response = client.get("/integration/connection-status")
        finally:
            module.requests.get = previous_get

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["main_system"]["status"], "unavailable")

    @staticmethod
    def _client(settings: Settings) -> TestClient:
        runtime = _RuntimeStub(settings)
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(integration_api.router)
        return TestClient(app)


if __name__ == "__main__":
    unittest.main()
