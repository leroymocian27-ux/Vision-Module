from __future__ import annotations

import ipaddress
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import device_discovery_api
from app.core.config import Settings
from app.network import device_discovery as discovery_module
from app.network.device_discovery import DeviceProbeResult, LocalNetwork, candidate_hosts
from app.network.runtime_config_store import RuntimeDeviceConfigStore
from app.services import device_connection_service as resolver_module
from app.services.device_connection_service import DeviceConnectionService
from app.services.device_connection_service import DeviceResolutionResult


def _settings(config_path: str) -> Settings:
    return replace(
        Settings(),
        device_discovery_config_path=config_path,
        device_discovery_enabled=True,
        main_system_default_port=8000,
        main_system_base_prefix="/api/v1",
        camera_rtsp_username="admin",
        camera_rtsp_password="secret",
        camera_rtsp_port=10554,
        camera_rtsp_path="/tcp/av0_1",
        default_rtsp_url="rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1",
        mock_camera_enabled=False,
    )


def _network() -> LocalNetwork:
    network = ipaddress.ip_network("192.168.8.0/24")
    return LocalNetwork(
        local_ip="192.168.8.100",
        subnet=str(network),
        interface_name="test",
        network=network,
    )


def _main(ip: str = "192.168.8.254") -> DeviceProbeResult:
    return DeviceProbeResult(
        ip=ip,
        device_type="main_system",
        confidence=0.98,
        status="connected",
        open_ports=[8000],
        evidence=["tcp_port_open", "health_endpoint_success", "response_signature_matched"],
        main_system_base_url=f"http://{ip}:8000/api/v1",
    )


def _camera(ip: str = "192.168.8.250") -> DeviceProbeResult:
    return DeviceProbeResult(
        ip=ip,
        device_type="camera",
        confidence=0.92,
        status="connected",
        open_ports=[10554],
        evidence=["tcp_port_10554_open", "rtsp_options_success"],
        rtsp_url=f"rtsp://admin:secret@{ip}:10554/tcp/av0_1",
        rtsp_port=10554,
    )


class DeviceConnectionDiscoveryTest(unittest.TestCase):
    def test_cached_devices_valid_skips_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with (
                patch.object(service, "_validate_cached_main", return_value=_main()),
                patch.object(service, "_validate_cached_camera", return_value=_camera()),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", side_effect=AssertionError("scan should not run")),
            ):
                result = service.resolve(force_scan=False, scan_main=True, scan_camera=True)

            self.assertEqual(result.settings.main_system_base_url, "http://192.168.8.254:8000/api/v1")
            self.assertEqual(result.settings.default_rtsp_url, "rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1")
            self.assertEqual(result.status["main_system"]["status"], "connected")
            self.assertEqual(result.status["camera"]["status"], "connected")

    def test_main_invalid_camera_valid_scans_only_main_system(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            calls: list[dict] = []

            def fake_scan(candidates, *, main_probe, camera_probe, scan_timeout_ms, max_workers):
                calls.append({"main": main_probe is not None, "camera": camera_probe is not None})
                return [_main("192.168.8.253")]

            with (
                patch.object(service, "_validate_cached_main", return_value=DeviceProbeResult("192.168.8.254", "unknown", 0.0, "unavailable")),
                patch.object(service, "_validate_cached_camera", return_value=_camera("192.168.8.250")),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", side_effect=fake_scan),
            ):
                result = service.resolve(force_scan=False, scan_main=True, scan_camera=True)

            self.assertEqual(calls, [{"main": True, "camera": False}])
            self.assertEqual(result.settings.main_system_base_url, "http://192.168.8.253:8000/api/v1")
            self.assertEqual(result.settings.default_rtsp_url, "rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1")

    def test_both_invalid_scans_both_and_saves_new_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)

            def fake_scan(candidates, *, main_probe, camera_probe, scan_timeout_ms, max_workers):
                self.assertIsNotNone(main_probe)
                self.assertIsNotNone(camera_probe)
                return [_main("192.168.8.252"), _camera("192.168.8.251")]

            with (
                patch.object(service, "_validate_cached_main", return_value=None),
                patch.object(service, "_validate_cached_camera", return_value=None),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", side_effect=fake_scan),
            ):
                result = service.resolve(force_scan=False, scan_main=True, scan_camera=True)

            self.assertEqual(result.status["main_system"]["ip"], "192.168.8.252")
            self.assertEqual(result.status["camera"]["ip"], "192.168.8.251")
            saved = service.store.load()
            self.assertEqual(saved["main_system"]["ip"], "192.168.8.252")
            self.assertEqual(saved["camera"]["ip"], "192.168.8.251")

    def test_no_devices_found_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            with (
                patch.object(service, "_validate_cached_main", return_value=None),
                patch.object(service, "_validate_cached_camera", return_value=None),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", return_value=[]),
            ):
                result = service.resolve(force_scan=False, scan_main=True, scan_camera=True)
            self.assertEqual(result.status["main_system"]["status"], "not_found")
            self.assertEqual(result.status["camera"]["status"], "not_found")
            self.assertEqual(result.status["camera"]["ip"], "192.168.8.250")
            self.assertEqual(result.status["camera"]["rtsp_url_masked"], "rtsp://admin:***@192.168.8.250:10554/tcp/av0_1")

    def test_connect_main_system_preserves_existing_camera_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            config = service.store.load()
            config["camera"].update(
                {
                    "ip": "192.168.8.250",
                    "rtsp_port": 10554,
                    "rtsp_url": "rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1",
                    "status": "connected",
                }
            )
            service.store.update(config)
            with (
                patch.object(service, "_validate_cached_main", return_value=None),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", return_value=[_main("192.168.8.252")]),
            ):
                result = service.connect_main_system()

            self.assertEqual(result.status["main_system"]["ip"], "192.168.8.252")
            self.assertEqual(result.status["camera"]["status"], "connected")
            self.assertEqual(result.status["camera"]["ip"], "192.168.8.250")

    def test_manual_rescan_runs_when_automatic_discovery_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service.settings = replace(service.settings, device_discovery_enabled=False)
            with (
                patch.object(service, "_validate_cached_main", return_value=None),
                patch.object(service, "_validate_cached_camera", return_value=None),
                patch.object(resolver_module, "resolve_local_network", return_value=_network()),
                patch.object(resolver_module, "scan_candidates", return_value=[]) as scan,
            ):
                result = service.manual_rescan()

            scan.assert_called_once()
            self.assertTrue(result.status["discovery"]["last_scan_at"])

    def test_missing_camera_cache_does_not_probe_local_template_host(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = self._service(tmp)
            service.settings = replace(service.settings, default_rtsp_url="", mock_camera_enabled=True)
            config = service.store.load()
            with patch.object(resolver_module.CameraProbe, "probe", side_effect=AssertionError("unexpected probe")):
                result = service._validate_cached_camera(config, timeout_ms=100)

            self.assertIsNone(result)

    def test_config_missing_and_corrupt_are_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "device_config.json"
            store = RuntimeDeviceConfigStore(path)
            self.assertEqual(store.load()["discovery"]["status"], "unknown")
            path.write_text("{broken", encoding="utf-8")
            recovered = store.load()
            self.assertEqual(recovered["discovery"]["status"], "recovered_default")
            self.assertTrue(list(path.parent.glob("device_config.json.corrupt-*")))

    def test_candidate_hosts_excludes_broadcast_address(self) -> None:
        hosts = candidate_hosts(
            ipaddress.ip_network("192.168.8.0/24"),
            local_ip="192.168.8.100",
            host_start=248,
            host_end=255,
        )
        self.assertIn("192.168.8.254", hosts)
        self.assertNotIn("192.168.8.255", hosts)

    def test_candidate_hosts_handles_non_24_subnet_by_last_octet(self) -> None:
        hosts = candidate_hosts(
            ipaddress.ip_network("192.168.8.0/23"),
            local_ip="192.168.8.100",
            host_start=248,
            host_end=255,
        )
        self.assertIn("192.168.8.248", hosts)
        self.assertIn("192.168.9.254", hosts)
        self.assertNotIn("192.168.9.255", hosts)

    def test_camera_probe_does_not_accept_open_port_without_rtsp_response(self) -> None:
        probe = discovery_module.CameraProbe(
            rtsp_template="rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1",
            ports=[10554],
            timeout_ms=100,
        )
        with (
            patch.object(discovery_module, "_tcp_open", return_value=True),
            patch.object(discovery_module, "_rtsp_options_success", return_value=False),
        ):
            result = probe.probe("192.168.8.250")
        self.assertNotEqual(result.device_type, "camera")
        self.assertEqual(result.status, "unverified")

    def _service(self, tmp: str) -> DeviceConnectionService:
        path = str(Path(tmp) / "device_config.json")
        return DeviceConnectionService(
            settings=_settings(path),
            store=RuntimeDeviceConfigStore(path),
        )


class DeviceDiscoveryApiTest(unittest.TestCase):
    def test_status_endpoint_returns_discovery_status(self) -> None:
        runtime = _RuntimeStub()
        client = self._client(runtime)

        response = client.get("/device-discovery/status")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["main_system"]["ip"], "192.168.8.254")

    def test_rescan_endpoint_applies_runtime_settings_and_restarts_stream(self) -> None:
        runtime = _RuntimeStub()
        client = self._client(runtime)

        response = client.post("/device-discovery/rescan")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(runtime.settings.main_system_base_url, "http://192.168.8.254:8000/api/v1")
        self.assertEqual(runtime.stream_service.started, [("camera_01", "rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1")])
        self.assertEqual(runtime.fall_event_reporter.endpoint_updates, ["http://192.168.8.254:8000/api/v1"])

    def test_connect_main_system_endpoint_does_not_restart_stream(self) -> None:
        runtime = _RuntimeStub()
        client = self._client(runtime)

        response = client.post("/device-discovery/connect-main-system")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(runtime.settings.main_system_base_url, "http://192.168.8.252:8000/api/v1")
        self.assertEqual(runtime.stream_service.started, [])
        self.assertEqual(runtime.fall_event_reporter.endpoint_updates, ["http://192.168.8.252:8000/api/v1"])

    @staticmethod
    def _client(runtime) -> TestClient:
        app = FastAPI()
        app.state.runtime = runtime
        app.include_router(device_discovery_api.router)
        return TestClient(app)


class _RuntimeStub:
    def __init__(self) -> None:
        self.settings = _settings("unused")
        self.stream_service = _StreamServiceStub()
        self.status_service = _SettingsStub(self.settings)
        self.fall_event_reporter = _ReporterStub(self.settings)
        self.device_connection_service = _DeviceConnectionServiceStub(self.settings)


class _SettingsStub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


class _StreamServiceStub(_SettingsStub):
    def __init__(self) -> None:
        super().__init__(_settings("unused"))
        self.started: list[tuple[str, str]] = []

    def start(self, camera_id: str, url: str):
        self.started.append((camera_id, url))
        return True, "stream restarted"


class _ReporterStub(_SettingsStub):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.endpoint_updates: list[str] = []

    def update_main_system_base_url(self, base_url: str) -> None:
        self.endpoint_updates.append(base_url)


class _DeviceConnectionServiceStub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def status(self) -> dict:
        return _status_payload()

    def manual_rescan(self) -> DeviceResolutionResult:
        settings = replace(
            self.settings,
            main_system_base_url="http://192.168.8.254:8000/api/v1",
            default_rtsp_url="rtsp://admin:secret@192.168.8.250:10554/tcp/av0_1",
            mock_camera_enabled=False,
        )
        self.settings = settings
        return DeviceResolutionResult(settings=settings, status=_status_payload(), scan_results=[_main(), _camera()])

    def connect_main_system(self) -> DeviceResolutionResult:
        settings = replace(
            self.settings,
            main_system_base_url="http://192.168.8.252:8000/api/v1",
        )
        self.settings = settings
        status = _status_payload()
        status["main_system"] = {"ip": "192.168.8.252", "status": "connected"}
        return DeviceResolutionResult(settings=settings, status=status, scan_results=[_main("192.168.8.252")])

    def connect_camera(self) -> DeviceResolutionResult:
        return self.manual_rescan()


def _status_payload() -> dict:
    return {
        "local_network": {"local_ip": "192.168.8.100", "subnet": "192.168.8.0/24", "interface": "test"},
        "main_system": {"ip": "192.168.8.254", "status": "connected"},
        "camera": {"ip": "192.168.8.250", "status": "connected", "rtsp_url_masked": "rtsp://admin:***@192.168.8.250:10554/tcp/av0_1"},
        "discovery": {"status": "idle", "last_scan_at": "2026-07-15T00:00:00Z", "last_error": None},
    }


if __name__ == "__main__":
    unittest.main()
