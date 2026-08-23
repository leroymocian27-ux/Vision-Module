from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import ParseResult, quote, unquote, urlsplit, urlunsplit
from urllib.request import urlopen


@dataclass(frozen=True)
class LocalNetwork:
    local_ip: str
    subnet: str
    interface_name: str
    network: ipaddress.IPv4Network


@dataclass(frozen=True)
class DeviceProbeResult:
    ip: str
    device_type: str
    confidence: float
    status: str
    open_ports: list[int] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    error: str | None = None
    main_system_base_url: str | None = None
    rtsp_url: str | None = None
    rtsp_port: int | None = None


def resolve_local_network() -> LocalNetwork | None:
    """Resolve the most likely LAN IPv4 using stdlib-only Windows-safe logic."""

    candidates: list[tuple[str, str]] = []
    default_ip = _default_route_ip()
    if default_ip:
        candidates.append(("default-route", default_ip))
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM):
            ip = info[4][0]
            candidates.append(("hostname", ip))
    except OSError:
        pass

    seen: set[str] = set()
    for interface_name, ip in candidates:
        if ip in seen:
            continue
        seen.add(ip)
        if not _is_usable_lan_ip(ip):
            continue
        network = ipaddress.ip_network(f"{ip}/24", strict=False)
        return LocalNetwork(
            local_ip=ip,
            subnet=str(network),
            interface_name=interface_name,
            network=network,
        )
    return None


def candidate_hosts(
    network: ipaddress.IPv4Network,
    *,
    local_ip: str,
    host_start: int,
    host_end: int,
) -> list[str]:
    addresses: list[str] = []
    start = min(host_start, host_end)
    end = max(host_start, host_end)
    scan_network = network
    if network.num_addresses > 4096:
        scan_network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
    for address in scan_network:
        if address not in network:
            continue
        if address == network.network_address or address == network.broadcast_address:
            continue
        if address == scan_network.network_address or address == scan_network.broadcast_address:
            continue
        last_octet = int(str(address).rsplit(".", 1)[1])
        if last_octet < start or last_octet > end:
            continue
        text = str(address)
        if text == local_ip:
            continue
        addresses.append(text)
    return addresses


def replace_rtsp_host(source_url: str, host: str, *, port: int | None = None) -> str:
    parsed = urlsplit(source_url)
    username = parsed.username or ""
    password = parsed.password or ""
    target_port = port if port is not None else parsed.port
    userinfo = ""
    if username or password:
        userinfo = quote(unquote(username), safe="") if username else ""
        if password or ":" in parsed.netloc:
            userinfo += f":{quote(unquote(password), safe='')}"
        userinfo += "@"
    netloc = f"{userinfo}{host}"
    if target_port:
        netloc += f":{target_port}"
    return urlunsplit((parsed.scheme or "rtsp", netloc, parsed.path or "/", parsed.query, ""))


def build_rtsp_url(
    *,
    username: str,
    password: str,
    host: str,
    port: int,
    path: str,
    scheme: str = "rtsp",
) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    userinfo = quote(username, safe="")
    userinfo += f":{quote(password, safe='')}"
    return f"{scheme}://{userinfo}@{host}:{port}{normalized_path}"


def mask_url_secret(url: str | None) -> str | None:
    if not url:
        return url
    parsed = urlsplit(url)
    if parsed.password is None:
        return url
    username = quote(unquote(parsed.username or ""), safe="")
    netloc = f"{username}:***@{parsed.hostname or ''}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


class MainSystemProbe:
    def __init__(self, *, port: int, base_prefix: str, timeout_ms: int) -> None:
        self.port = int(port)
        self.base_prefix = base_prefix if base_prefix.startswith("/") else f"/{base_prefix}"
        self.timeout_sec = max(0.05, timeout_ms / 1000)

    def probe(self, ip: str) -> DeviceProbeResult:
        evidence: list[str] = []
        open_ports: list[int] = []
        if not _tcp_open(ip, self.port, self.timeout_sec):
            return DeviceProbeResult(
                ip=ip,
                device_type="unknown",
                confidence=0.0,
                status="unavailable",
                error="main_system_port_closed",
            )
        open_ports.append(self.port)
        evidence.append("tcp_port_open")
        origin = f"http://{ip}:{self.port}"
        health = _http_get(f"{origin}/healthz", timeout_sec=self.timeout_sec)
        if health is None:
            return DeviceProbeResult(
                ip=ip,
                device_type="unknown",
                confidence=0.25,
                status="unavailable",
                open_ports=open_ports,
                evidence=evidence + ["health_endpoint_failed"],
                main_system_base_url=f"{origin}{self.base_prefix}",
            )
        evidence.append("health_endpoint_success")
        signature = _main_system_signature_matched(health)
        if signature:
            evidence.append("response_signature_matched")
            return DeviceProbeResult(
                ip=ip,
                device_type="main_system",
                confidence=0.98,
                status="connected",
                open_ports=open_ports,
                evidence=evidence,
                main_system_base_url=f"{origin}{self.base_prefix}",
            )
        return DeviceProbeResult(
            ip=ip,
            device_type="unknown",
            confidence=0.45,
            status="unverified",
            open_ports=open_ports,
            evidence=evidence + ["response_signature_missing"],
            main_system_base_url=f"{origin}{self.base_prefix}",
        )


class CameraProbe:
    def __init__(
        self,
        *,
        rtsp_template: str,
        ports: Iterable[int],
        timeout_ms: int,
    ) -> None:
        self.rtsp_template = rtsp_template
        self.ports = list(dict.fromkeys(int(port) for port in ports if int(port) > 0))
        self.timeout_sec = max(0.05, timeout_ms / 1000)

    def probe(self, ip: str) -> DeviceProbeResult:
        evidence: list[str] = []
        open_ports: list[int] = []
        for port in self.ports:
            rtsp_url = replace_rtsp_host(self.rtsp_template, ip, port=port)
            if not _tcp_open(ip, port, self.timeout_sec):
                continue
            open_ports.append(port)
            evidence.append(f"tcp_port_{port}_open")
            if _rtsp_options_success(rtsp_url, timeout_sec=self.timeout_sec):
                return DeviceProbeResult(
                    ip=ip,
                    device_type="camera",
                    confidence=0.92,
                    status="connected",
                    open_ports=open_ports,
                    evidence=evidence + ["rtsp_options_success"],
                    rtsp_url=rtsp_url,
                    rtsp_port=port,
                )
            evidence.append(f"rtsp_options_{port}_failed")
        if open_ports:
            return DeviceProbeResult(
                ip=ip,
                device_type="unknown",
                confidence=0.35,
                status="unverified",
                open_ports=open_ports,
                evidence=evidence,
                error="rtsp_protocol_not_verified",
            )
        return DeviceProbeResult(
            ip=ip,
            device_type="unknown",
            confidence=0.0,
            status="unavailable",
            error="rtsp_ports_closed",
        )


def scan_candidates(
    candidates: list[str],
    *,
    main_probe: MainSystemProbe | None,
    camera_probe: CameraProbe | None,
    scan_timeout_ms: int,
    max_workers: int = 8,
) -> list[DeviceProbeResult]:
    started = time.monotonic()
    deadline = started + max(0.1, scan_timeout_ms / 1000)
    results: list[DeviceProbeResult] = []

    def probe_host(ip: str) -> list[DeviceProbeResult]:
        host_results: list[DeviceProbeResult] = []
        if main_probe is not None:
            host_results.append(main_probe.probe(ip))
        if camera_probe is not None:
            host_results.append(camera_probe.probe(ip))
        return host_results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(probe_host, ip): ip for ip in candidates}
        try:
            completed = concurrent.futures.as_completed(futures, timeout=max(0.1, scan_timeout_ms / 1000))
            for future in completed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    results.extend(future.result(timeout=max(0.01, remaining)))
                except Exception as exc:
                    results.append(
                        DeviceProbeResult(
                            ip=futures[future],
                            device_type="unknown",
                            confidence=0.0,
                            status="error",
                            error=str(exc),
                        )
                    )
        except concurrent.futures.TimeoutError:
            for future, ip in futures.items():
                if not future.done():
                    future.cancel()
                    results.append(
                        DeviceProbeResult(
                            ip=ip,
                            device_type="unknown",
                            confidence=0.0,
                            status="timeout",
                            error="scan_timeout",
                        )
                    )
    return results


def _default_route_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.2)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            return ip
    except OSError:
        return None


def _is_usable_lan_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return bool(
        address.version == 4
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
    )


def _tcp_open(host: str, port: int, timeout_sec: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _http_get(url: str, *, timeout_sec: float) -> str | None:
    try:
        with urlopen(url, timeout=timeout_sec) as response:
            return response.read(4096).decode("utf-8", errors="replace")
    except HTTPError as exc:
        try:
            return exc.read(4096).decode("utf-8", errors="replace")
        except Exception:
            return None
    except (OSError, URLError):
        return None


def _main_system_signature_matched(body: str) -> bool:
    text = body.strip()
    lowered = text.lower()
    if "aiot elder care monitoring system" in lowered:
        return True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    service_text = " ".join(
        str(payload.get(key, ""))
        for key in ("app", "service", "name", "role")
    ).lower()
    return (
        "aiot elder care monitoring system" in service_text
        or payload.get("role") == "main_system"
    )


def _rtsp_options_success(rtsp_url: str, *, timeout_sec: float) -> bool:
    parsed = urlsplit(rtsp_url)
    host = parsed.hostname
    port = parsed.port or 554
    if not host:
        return False
    request_url = _rtsp_request_url(parsed)
    payload = (
        f"OPTIONS {request_url} RTSP/1.0\r\n"
        "CSeq: 1\r\n"
        "User-Agent: VisionServiceDiscovery\r\n"
        "\r\n"
    ).encode("ascii", errors="ignore")
    try:
        with socket.create_connection((host, port), timeout=timeout_sec) as sock:
            sock.settimeout(timeout_sec)
            sock.sendall(payload)
            response = sock.recv(512)
    except OSError:
        return False
    return response.startswith(b"RTSP/")


def _rtsp_request_url(parsed: ParseResult) -> str:
    host = parsed.hostname or ""
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme or "rtsp", netloc, parsed.path or "/", parsed.query, ""))
