from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlsplit

from app.camera.source_models import is_mock_source
from app.core.config import Settings
from app.core.logger import get_logger
from app.network.device_discovery import (
    CameraProbe,
    DeviceProbeResult,
    MainSystemProbe,
    build_rtsp_url,
    candidate_hosts,
    mask_url_secret,
    replace_rtsp_host,
    resolve_local_network,
    scan_candidates,
)
from app.network.runtime_config_store import RuntimeDeviceConfigStore, utc_now_iso

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeviceResolutionResult:
    settings: Settings
    status: dict[str, Any]
    scan_results: list[DeviceProbeResult]


class DeviceConnectionService:
    """Resolve main-system and camera addresses with cached config first."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: RuntimeDeviceConfigStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store or RuntimeDeviceConfigStore(settings.device_config_path)
        self._last_status: dict[str, Any] | None = None

    def startup_resolve(self) -> DeviceResolutionResult:
        return self.resolve(force_scan=False, scan_main=True, scan_camera=False)

    def manual_rescan(self) -> DeviceResolutionResult:
        return self.resolve(force_scan=True, scan_main=True, scan_camera=False)

    def connect_camera(self) -> DeviceResolutionResult:
        return self.resolve(force_scan=False, scan_main=False, scan_camera=False)

    def connect_main_system(self) -> DeviceResolutionResult:
        return self.resolve(force_scan=True, scan_main=True, scan_camera=False)

    def status(self) -> dict[str, Any]:
        if self._last_status is not None:
            return self._last_status
        config = self.store.load()
        return self._status_from_config(config, discovery_status=config["discovery"].get("status", "idle"))

    def resolve(
        self,
        *,
        force_scan: bool,
        scan_main: bool,
        scan_camera: bool,
    ) -> DeviceResolutionResult:
        config = self.store.load()
        now = utc_now_iso()
        local_network = resolve_local_network()
        if local_network is None:
            config["discovery"].update(
                {
                    "status": "degraded",
                    "last_error": "no_usable_lan_ipv4",
                    "last_scan_at": now if force_scan else config["discovery"].get("last_scan_at", ""),
                }
            )
            self.store.update(config)
            status = self._status_from_config(config, discovery_status="degraded")
            self._last_status = status
            logger.warning("device_discovery_no_usable_lan_ipv4")
            return DeviceResolutionResult(self.settings, status, [])

        config["network"].update(
            {
                "local_ip": local_network.local_ip,
                "subnet": local_network.subnet,
                "interface_name": local_network.interface_name,
            }
        )
        host_start = self.settings.device_discovery_candidate_host_start
        host_end = self.settings.device_discovery_candidate_host_end
        connect_timeout_ms = self.settings.device_discovery_connect_timeout_ms
        scan_timeout_ms = self.settings.device_discovery_scan_timeout_ms
        config["discovery"].update(
            {
                "candidate_host_start": host_start,
                "candidate_host_end": host_end,
                "connect_timeout_ms": connect_timeout_ms,
                "scan_timeout_ms": scan_timeout_ms,
                "last_error": None,
            }
        )

        main_result = self._validate_cached_main(config, timeout_ms=connect_timeout_ms) if scan_main else None
        camera_result = self._validate_cached_camera(config, timeout_ms=connect_timeout_ms) if scan_camera else None
        main_ok = bool(main_result and main_result.device_type == "main_system" and main_result.status == "connected")
        camera_ok = bool(camera_result and camera_result.device_type == "camera" and camera_result.status == "connected")

        scan_for_main = bool(scan_main and (force_scan or not main_ok))
        scan_for_camera = bool(scan_camera and (force_scan or not camera_ok))
        scan_results: list[DeviceProbeResult] = []
        # A disabled setting suppresses startup discovery, but an operator's manual
        # rescan must still be able to recover connectivity.
        should_scan = (self.settings.device_discovery_enabled or force_scan) and (
            scan_for_main or scan_for_camera
        )
        if should_scan:
            candidates = self._prioritized_candidates(
                candidate_hosts(
                    local_network.network,
                    local_ip=local_network.local_ip,
                    host_start=host_start,
                    host_end=host_end,
                ),
                config=config,
            )
            logger.info(
                "device_discovery_scan_start subnet=%s candidates=%s scan_main=%s scan_camera=%s",
                local_network.subnet,
                len(candidates),
                scan_for_main,
                scan_for_camera,
            )
            scan_results = scan_candidates(
                candidates,
                main_probe=self._main_probe(connect_timeout_ms) if scan_for_main else None,
                camera_probe=self._camera_probe(connect_timeout_ms) if scan_for_camera else None,
                scan_timeout_ms=scan_timeout_ms,
                max_workers=max(1, self.settings.device_discovery_max_workers),
            )
            config["discovery"]["last_scan_at"] = now
            main_result = self._best_result(scan_results, "main_system") or (main_result if main_ok else None)
            camera_result = self._best_result(scan_results, "camera") or (camera_result if camera_ok else None)
        elif main_ok and camera_ok:
            logger.info("device_discovery_cached_config_valid main=%s camera=%s", main_result.ip, camera_result.ip)

        new_settings = self._settings_from_results(self.settings, main_result, camera_result)
        self._write_results(
            config,
            main_result,
            camera_result,
            discovery_status="idle",
            scan_main=scan_main,
            scan_camera=scan_camera,
        )
        saved = self.store.update(config)
        status = self._status_from_config(saved, discovery_status="idle")
        self.settings = new_settings
        self._last_status = status
        return DeviceResolutionResult(settings=new_settings, status=status, scan_results=scan_results)

    def _validate_cached_main(self, config: dict[str, Any], *, timeout_ms: int) -> DeviceProbeResult | None:
        ip = str(config.get("main_system", {}).get("ip") or "").strip() or _host_from_url(self.settings.main_system_base_url)
        if not ip or _is_localhost(ip):
            return None
        logger.info("device_resolver_validate_cached_main ip=%s", ip)
        result = MainSystemProbe(
            port=self.settings.main_system_default_port,
            base_prefix=self.settings.main_system_base_prefix,
            timeout_ms=timeout_ms,
        ).probe(ip)
        return result

    def _validate_cached_camera(self, config: dict[str, Any], *, timeout_ms: int) -> DeviceProbeResult | None:
        rtsp_url = str(config.get("camera", {}).get("rtsp_url") or "").strip()
        if not rtsp_url and self.settings.default_rtsp_url and not is_mock_source(self.settings.default_rtsp_url):
            rtsp_url = self.settings.default_rtsp_url
        if not rtsp_url:
            return None
        ip = str(config.get("camera", {}).get("ip") or "").strip() or _host_from_url(rtsp_url)
        if not ip or is_mock_source(rtsp_url):
            return None
        logger.info("device_resolver_validate_cached_camera ip=%s", ip)
        template = replace_rtsp_host(rtsp_url, ip)
        ports = self._camera_ports(template)
        return CameraProbe(rtsp_template=template, ports=ports, timeout_ms=timeout_ms).probe(ip)

    def _main_probe(self, timeout_ms: int) -> MainSystemProbe:
        return MainSystemProbe(
            port=self.settings.main_system_default_port,
            base_prefix=self.settings.main_system_base_prefix,
            timeout_ms=timeout_ms,
        )

    def _camera_probe(self, timeout_ms: int) -> CameraProbe:
        template = self._rtsp_template()
        return CameraProbe(
            rtsp_template=template,
            ports=self._camera_ports(template),
            timeout_ms=timeout_ms,
        )

    def _rtsp_template(self) -> str:
        if self.settings.default_rtsp_url and not is_mock_source(self.settings.default_rtsp_url):
            return self.settings.default_rtsp_url
        return build_rtsp_url(
            username=self.settings.camera_rtsp_username,
            password=self.settings.camera_rtsp_password,
            host="127.0.0.1",
            port=self.settings.camera_rtsp_port,
            path=self.settings.camera_rtsp_path,
        )

    def _camera_ports(self, rtsp_url: str) -> list[int]:
        parsed = urlsplit(rtsp_url)
        ports = [
            parsed.port,
            self.settings.camera_rtsp_port,
            10554,
            554,
        ]
        return [int(port) for port in dict.fromkeys(port for port in ports if port)]

    @staticmethod
    def _best_result(results: list[DeviceProbeResult], device_type: str) -> DeviceProbeResult | None:
        matches = [item for item in results if item.device_type == device_type and item.status == "connected"]
        if not matches:
            return None
        return max(matches, key=lambda item: item.confidence)

    def _prioritized_candidates(self, candidates: list[str], *, config: dict[str, Any]) -> list[str]:
        priority = [
            _host_from_url(self.settings.main_system_base_url),
            str(config.get("main_system", {}).get("ip") or "").strip(),
        ]
        ordered: list[str] = []
        seen: set[str] = set()
        for ip in priority + candidates:
            if not ip or ip in seen:
                continue
            seen.add(ip)
            ordered.append(ip)
        return ordered

    def _settings_from_results(
        self,
        settings: Settings,
        main_result: DeviceProbeResult | None,
        camera_result: DeviceProbeResult | None,
    ) -> Settings:
        updates: dict[str, Any] = {}
        if main_result and main_result.device_type == "main_system" and main_result.main_system_base_url:
            updates["main_system_base_url"] = main_result.main_system_base_url
        if camera_result and camera_result.device_type == "camera" and camera_result.rtsp_url:
            updates["default_rtsp_url"] = camera_result.rtsp_url
            updates["mock_camera_enabled"] = False
        return replace(settings, **updates) if updates else settings

    def _write_results(
        self,
        config: dict[str, Any],
        main_result: DeviceProbeResult | None,
        camera_result: DeviceProbeResult | None,
        *,
        discovery_status: str,
        scan_main: bool,
        scan_camera: bool,
    ) -> None:
        now = utc_now_iso()
        if not scan_main:
            pass
        elif main_result and main_result.device_type == "main_system":
            config["main_system"].update(
                {
                    "ip": main_result.ip,
                    "port": self.settings.main_system_default_port,
                    "base_url": main_result.main_system_base_url or "",
                    "websocket_url": "",
                    "last_success_at": now if main_result.status == "connected" else config["main_system"].get("last_success_at", ""),
                    "status": main_result.status,
                }
            )
            logger.info("device_resolver_main_system_resolved ip=%s status=%s", main_result.ip, main_result.status)
        elif main_result is not None:
            config["main_system"]["status"] = main_result.status
        else:
            config["main_system"]["status"] = "not_found"

        if not scan_camera:
            pass
        elif camera_result and camera_result.device_type == "camera":
            config["camera"].update(
                {
                    "ip": camera_result.ip,
                    "rtsp_port": camera_result.rtsp_port,
                    "rtsp_url": camera_result.rtsp_url or "",
                    "last_success_at": now if camera_result.status == "connected" else config["camera"].get("last_success_at", ""),
                    "status": camera_result.status,
                }
            )
            logger.info(
                "device_resolver_camera_resolved ip=%s rtsp=%s status=%s",
                camera_result.ip,
                mask_url_secret(camera_result.rtsp_url),
                camera_result.status,
            )
        elif camera_result is not None:
            config["camera"]["status"] = camera_result.status
        else:
            fallback_url = self.settings.default_rtsp_url if self.settings.default_rtsp_url and not is_mock_source(self.settings.default_rtsp_url) else ""
            fallback_ip = _host_from_url(fallback_url)
            if fallback_url:
                parsed = urlsplit(fallback_url)
                config["camera"].update(
                    {
                        "ip": fallback_ip,
                        "rtsp_port": parsed.port or self.settings.camera_rtsp_port,
                        "rtsp_url": fallback_url,
                    }
                )
            config["camera"]["status"] = "not_found"

        config["discovery"]["status"] = discovery_status

    @staticmethod
    def _status_from_config(config: dict[str, Any], *, discovery_status: str) -> dict[str, Any]:
        camera = dict(config.get("camera") or {})
        camera["rtsp_url_masked"] = mask_url_secret(camera.get("rtsp_url"))
        camera.pop("rtsp_url", None)
        return {
            "local_network": {
                "local_ip": config.get("network", {}).get("local_ip", ""),
                "subnet": config.get("network", {}).get("subnet", ""),
                "interface": config.get("network", {}).get("interface_name", ""),
            },
            "main_system": dict(config.get("main_system") or {}),
            "camera": camera,
            "discovery": {
                "status": discovery_status,
                "last_scan_at": config.get("discovery", {}).get("last_scan_at", ""),
                "last_error": config.get("discovery", {}).get("last_error"),
                "candidate_host_start": config.get("discovery", {}).get("candidate_host_start"),
                "candidate_host_end": config.get("discovery", {}).get("candidate_host_end"),
            },
        }


def apply_resolved_settings_to_runtime(runtime, settings: Settings) -> None:
    runtime.settings = settings
    for attr in (
        "source_manager",
        "stream_service",
        "status_service",
        "fall_event_reporter",
        "detection_service",
        "tracking_service",
        "tracking_worker_service",
        "identity_service",
        "identity_binding_service",
        "identity_binding_worker_service",
        "pose_service",
        "pose_worker_service",
        "behavior_service",
        "temporal_service",
        "result_publisher_service",
        "fall_hint_worker_service",
        "temporal_worker_service",
        "fusion_worker_service",
        "fall_fusion_service",
    ):
        service = getattr(runtime, attr, None)
        if service is not None and hasattr(service, "settings"):
            service.settings = settings
    if getattr(runtime, "fall_event_reporter", None) is not None:
        runtime.fall_event_reporter.update_main_system_base_url(settings.main_system_base_url)
    if getattr(runtime, "device_connection_service", None) is not None:
        runtime.device_connection_service.settings = settings


def _host_from_url(url: str | None) -> str:
    if not url:
        return ""
    return urlsplit(url).hostname or ""


def _is_localhost(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}
