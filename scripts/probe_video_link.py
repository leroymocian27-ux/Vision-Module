from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def main() -> int:
    configure_stdout()
    parser = argparse.ArgumentParser(description="Probe camera-service video link freshness and FPS.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="go2_front_camera")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--source-url", default="", help="Optional direct MJPEG source URL to probe in addition to camera-service status.")
    parser.add_argument("--source-tcp-url", default="", help="Optional source URL for TCP-only reachability checks.")
    parser.add_argument("--probe-source-tcp", action="store_true", help="Check source host:port TCP reachability without pulling the MJPEG stream.")
    parser.add_argument(
        "--list-source-connections",
        action="store_true",
        help="List local TCP connections to the source host:port to catch accidental multi-client pulls.",
    )
    parser.add_argument("--probe-display-stream", action="store_true", help="Also read camera-service /stream/display.mjpg and count displayed frames.")
    parser.add_argument("--display-fps", type=float, default=0.0, help="Optional display stream target FPS. Set 0 to use server DISPLAY_MJPEG_FPS.")
    parser.add_argument("--output-dir", default="artifacts/video_link_probe")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    display_probe: dict[str, Any] = {}
    display_thread: threading.Thread | None = None
    if args.probe_display_stream:
        display_thread = threading.Thread(
            target=lambda: display_probe.update(
                probe_mjpeg_source(
                    display_stream_url(args.base_url.rstrip("/"), args.camera_id, args.display_fps),
                    duration=max(1.0, args.duration),
                )
            ),
            name="display-stream-probe",
            daemon=True,
        )
        display_thread.start()
    samples = collect_samples(
        base_url=args.base_url.rstrip("/"),
        camera_id=args.camera_id,
        duration=max(1.0, args.duration),
        interval=max(0.2, args.interval),
    )
    if display_thread is not None:
        display_thread.join(timeout=max(2.0, args.duration + 3.0))
    source_summary = None
    if args.source_url:
        source_summary = probe_mjpeg_source(args.source_url, duration=max(1.0, args.duration))
    summary = summarize(samples)
    if display_probe:
        summary["display_stream_probe"] = display_probe
    if source_summary is not None:
        summary["source_direct"] = source_summary
    tcp_url = args.source_tcp_url or args.source_url or str((summary.get("last_sample") or {}).get("source_url_masked") or "")
    if args.probe_source_tcp and tcp_url:
        summary["source_tcp"] = probe_tcp_url(tcp_url)
    if args.list_source_connections and tcp_url:
        summary["source_connections"] = list_source_tcp_connections(tcp_url)
    summary["diagnosis"] = diagnose_video_link(summary)
    payload = {"summary": summary, "samples": samples}

    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"video_link_probe_{stamp}.json"
    csv_path = output_dir / f"video_link_probe_{stamp}.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(csv_path, samples)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"json={json_path}")
    print(f"csv={csv_path}")
    return 0


def probe_mjpeg_source(url: str, *, duration: float) -> dict[str, Any]:
    deadline = time.monotonic() + duration
    frames = 0
    bytes_read = 0
    opens = 0
    errors: list[str] = []
    intervals: list[float] = []
    last_frame_at: float | None = None

    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                url,
                headers={"Accept": "multipart/x-mixed-replace,image/jpeg,*/*", "User-Agent": "camera-service-probe/1.0"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                opens += 1
                set_socket_timeout(response, 2.0)
                buffer = b""
                while time.monotonic() < deadline:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    buffer += chunk
                    found, buffer = extract_jpeg_count(buffer)
                    for _ in range(found):
                        now = time.monotonic()
                        if last_frame_at is not None:
                            intervals.append((now - last_frame_at) * 1000)
                        last_frame_at = now
                    frames += found
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc)[:120]}")
            time.sleep(0.2)

    elapsed = max(0.001, duration)
    return {
        "url": redact_url(url),
        "opens": opens,
        "frames": frames,
        "fps": round(frames / elapsed, 2),
        "bytes_read": bytes_read,
        "mbps": round((bytes_read * 8 / elapsed) / 1_000_000, 2),
        "inter_frame_ms": stats(intervals),
        "error_count": len(errors),
        "errors_tail": errors[-5:],
    }


def display_stream_url(base_url: str, camera_id: str, display_fps: float = 0.0) -> str:
    url = f"{base_url}/stream/display.mjpg?camera_id={quote(camera_id)}"
    if display_fps and display_fps > 0:
        url += f"&fps={display_fps:g}"
    return url


def probe_tcp_url(url: str, *, timeout: float = 2.0) -> dict[str, Any]:
    started = time.monotonic()
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port
    if not host:
        return {
            "url": redact_url(url),
            "reachable": False,
            "elapsed_ms": 0.0,
            "error": "missing host",
        }
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError as exc:
        return {
            "url": redact_url(url),
            "host": host,
            "port": port,
            "reachable": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "error": str(exc),
        }
    return {
        "url": redact_url(url),
        "host": host,
        "port": port,
        "reachable": True,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }


def list_source_tcp_connections(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    host = parsed.hostname
    port = parsed.port
    if not host:
        return {
            "url": redact_url(url),
            "host": None,
            "port": None,
            "connections": [],
            "active_count": 0,
            "error": "missing host",
        }
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    try:
        import psutil
    except Exception as exc:
        return {
            "url": redact_url(url),
            "host": host,
            "port": port,
            "connections": [],
            "active_count": 0,
            "error": f"psutil_unavailable: {exc}",
        }

    active_states = {"ESTABLISHED", "SYN_SENT", "SYN_RECV"}
    rows: list[dict[str, Any]] = []
    try:
        connections = psutil.net_connections(kind="tcp")
    except Exception as exc:
        return {
            "url": redact_url(url),
            "host": host,
            "port": port,
            "connections": [],
            "active_count": 0,
            "error": str(exc),
        }
    for conn in connections:
        raddr = getattr(conn, "raddr", None)
        if not raddr:
            continue
        remote_ip = getattr(raddr, "ip", None) or (raddr[0] if len(raddr) >= 1 else None)
        remote_port = getattr(raddr, "port", None) or (raddr[1] if len(raddr) >= 2 else None)
        if str(remote_ip) != str(host) or int(remote_port or 0) != int(port):
            continue
        pid = getattr(conn, "pid", None)
        process_name = None
        if pid:
            try:
                process_name = psutil.Process(pid).name()
            except Exception:
                process_name = None
        rows.append(
            {
                "local_address": _addr_host(getattr(conn, "laddr", None)),
                "local_port": _addr_port(getattr(conn, "laddr", None)),
                "remote_address": remote_ip,
                "remote_port": remote_port,
                "status": str(getattr(conn, "status", "") or "UNKNOWN"),
                "pid": pid,
                "process_name": process_name,
            }
        )
    active = [row for row in rows if str(row.get("status")) in active_states]
    return {
        "url": redact_url(url),
        "host": host,
        "port": port,
        "connections": rows,
        "active_count": len(active),
        "total_count": len(rows),
    }


def _addr_host(addr: Any) -> str | None:
    if not addr:
        return None
    return getattr(addr, "ip", None) or (addr[0] if len(addr) >= 1 else None)


def _addr_port(addr: Any) -> int | None:
    if not addr:
        return None
    value = getattr(addr, "port", None) or (addr[1] if len(addr) >= 2 else None)
    return int(value) if value is not None else None


def extract_jpeg_count(buffer: bytes) -> tuple[int, bytes]:
    count = 0
    data = buffer
    while True:
        start = data.find(b"\xff\xd8")
        if start < 0:
            return count, data[-2:] if len(data) > 2 else data
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            return count, data[start:][-2_000_000:]
        count += 1
        data = data[end + 2:]


def set_socket_timeout(response, timeout: float) -> None:
    try:
        response.fp.raw._sock.settimeout(timeout)
    except Exception:
        return


def redact_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def collect_samples(*, base_url: str, camera_id: str, duration: float, interval: float) -> list[dict[str, Any]]:
    run_started = time.monotonic()
    deadline = time.monotonic() + duration
    samples: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        started = time.monotonic()
        sample: dict[str, Any] = {
            "sampled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_sec": round(started - run_started, 3),
        }
        try:
            status = get_json(f"{base_url}/status?camera_id={quote(camera_id)}", timeout=5)
            cameras = status.get("cameras") or []
            camera = cameras[0] if cameras else {}
            runtime = (((status.get("workers") or {}).get("post_fall_v2_runtime")) or {})
            display = (((status.get("display_stream") or {}).get("cameras") or {}).get(camera_id) or {})
            effective_config = ((status.get("configuration") or {}).get("effective_config") or {})
            sample.update(
                {
                    "camera_present": bool(cameras),
                    "latest_reason": (status.get("latest_result") or {}).get("reason"),
                    "latest_camera_stream_state": (status.get("latest_result") or {}).get("camera_stream_state"),
                    "stream_state": camera.get("stream_state"),
                    "source_url_masked": camera.get("source_url_masked"),
                    "source_protocol": camera.get("source_protocol"),
                    "frame_status": camera.get("frame_status"),
                    "frame_seq": camera.get("frame_seq"),
                    "frame_age_ms": camera.get("frame_age_ms"),
                    "capture_fps": camera.get("capture_fps"),
                    "mjpeg_receive_fps": camera.get("mjpeg_receive_fps"),
                    "mjpeg_publish_fps": camera.get("mjpeg_publish_fps"),
                    "mjpeg_dropped_frames": camera.get("mjpeg_dropped_frames"),
                    "mjpeg_inter_frame_ms": camera.get("mjpeg_inter_frame_ms"),
                    "mjpeg_inter_frame_max_ms": camera.get("mjpeg_inter_frame_max_ms"),
                    "read_latency_ms": camera.get("read_latency_ms"),
                    "read_latency_max_ms": camera.get("read_latency_max_ms"),
                    "reconnect_count": camera.get("reconnect_count"),
                    "webrtc_clients": (status.get("streaming") or {}).get("webrtc_clients"),
                    "ws_clients": (status.get("streaming") or {}).get("ws_clients"),
                    "binary_running": runtime.get("running"),
                    "binary_queue_depth": runtime.get("queue_depth"),
                    "binary_frames_processed": runtime.get("frames_processed"),
                    "binary_frames_dropped": runtime.get("frames_dropped"),
                    "binary_avg_ms": runtime.get("binary_inference_latency_avg_ms"),
                    "binary_p95_ms": runtime.get("binary_inference_latency_p95_ms"),
                    "binary_frame_age_ms": runtime.get("frame_age_ms"),
                    "binary_provider": runtime.get("binary_provider"),
                    "display_encoded_frames": display.get("encoded_frames"),
                    "display_cache_hits": display.get("cache_hits"),
                    "display_served_frames": display.get("served_frames"),
                    "display_mjpeg_served_frames": display.get("display_mjpeg_served_frames"),
                    "latest_frame_served_frames": display.get("latest_frame_served_frames"),
                    "display_encode_fps": display.get("display_encode_fps"),
                    "display_served_fps": display.get("display_served_fps"),
                    "display_mjpeg_served_fps": display.get("display_mjpeg_served_fps"),
                    "latest_frame_served_fps": display.get("latest_frame_served_fps"),
                    "display_target_fps": effective_config.get("display_mjpeg_fps"),
                    "display_encode_ms": display.get("encode_ms"),
                    "display_encode_ms_max": display.get("encode_ms_max"),
                    "display_age_ms": display.get("display_age_ms"),
                }
            )
        except Exception as exc:
            sample["error"] = str(exc)
        samples.append(sample)
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, interval - elapsed))
    return samples


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [item for item in samples if not item.get("error")]
    ages = numbers(valid, "frame_age_ms")
    receive_fps = numbers(valid, "mjpeg_receive_fps")
    publish_fps = numbers(valid, "mjpeg_publish_fps")
    binary_ms = numbers(valid, "binary_avg_ms")
    display_encode_fps = numbers(valid, "display_encode_fps")
    display_served_fps = numbers(valid, "display_served_fps")
    display_mjpeg_served_fps = numbers(valid, "display_mjpeg_served_fps")
    latest_frame_served_fps = numbers(valid, "latest_frame_served_fps")
    display_target_fps = numbers(valid, "display_target_fps")
    display_encode_ms = numbers(valid, "display_encode_ms")
    display_age_ms = numbers(valid, "display_age_ms")
    states = {}
    camera_missing_count = 0
    for sample in valid:
        if sample.get("camera_present") is False:
            camera_missing_count += 1
        state = str(sample.get("stream_state") or "unknown")
        states[state] = states.get(state, 0) + 1
    seq_values = numbers(valid, "frame_seq")
    seq_delta = int(seq_values[-1] - seq_values[0]) if len(seq_values) >= 2 else 0
    elapsed_values = numbers(valid, "elapsed_sec")
    duration_sec = max(0.001, elapsed_values[-1] - elapsed_values[0]) if len(elapsed_values) >= 2 else max(0.001, len(samples))
    return {
        "sample_count": len(samples),
        "valid_samples": len(valid),
        "camera_missing_samples": camera_missing_count,
        "stream_states": states,
        "frame_seq_delta": seq_delta,
        "observed_seq_fps": round(seq_delta / duration_sec, 2),
        "frame_age_ms": stats(ages),
        "mjpeg_receive_fps": stats(receive_fps),
        "mjpeg_publish_fps": stats(publish_fps),
        "display_encode_fps": stats(display_encode_fps),
        "display_served_fps": stats(display_served_fps),
        "display_mjpeg_served_fps": stats(display_mjpeg_served_fps),
        "latest_frame_served_fps": stats(latest_frame_served_fps),
        "display_target_fps": stats(display_target_fps),
        "display_encode_ms": stats(display_encode_ms),
        "display_age_ms": stats(display_age_ms),
        "binary_avg_ms": stats(binary_ms),
        "last_sample": valid[-1] if valid else None,
    }


def diagnose_video_link(summary: dict[str, Any]) -> dict[str, Any]:
    source = summary.get("source_direct") or {}
    source_tcp = summary.get("source_tcp") or {}
    source_connections = summary.get("source_connections") or {}
    display_probe = summary.get("display_stream_probe") or {}
    last = summary.get("last_sample") or {}
    states = summary.get("stream_states") or {}
    receive_fps = stat_avg(summary, "mjpeg_receive_fps")
    publish_fps = stat_avg(summary, "mjpeg_publish_fps")
    capture_fps = number_or_none(last.get("capture_fps"))
    source_protocol = str(last.get("source_protocol") or "").lower()
    if not source_protocol and ((receive_fps or 0.0) > 0.0 or (publish_fps or 0.0) > 0.0):
        source_protocol = "mjpeg"
    display_status_fps = stat_avg(summary, "display_mjpeg_served_fps")
    if display_status_fps is None:
        display_status_fps = stat_avg(summary, "display_served_fps")
    display_probe_fps = number_or_none(display_probe.get("fps"))
    binary_queue_depth = number_or_none(last.get("binary_queue_depth"))
    binary_avg_ms = number_or_none(last.get("binary_avg_ms"))
    evidence: list[str] = []

    if not summary.get("valid_samples"):
        return {
            "bottleneck": "camera_service_status_unavailable",
            "severity": "blocking",
            "evidence": ["no valid /status samples"],
            "recommended_next_action": "确认 camera-service 是否启动，先恢复 /healthz 与 /status。 ",
        }

    if int(summary.get("camera_missing_samples") or 0) >= int(summary.get("valid_samples") or 0):
        reason = last.get("latest_reason")
        stream_state = last.get("latest_camera_stream_state")
        return {
            "bottleneck": "camera_stream_not_started",
            "severity": "blocking",
            "evidence": [
                f"camera_missing_samples={summary.get('camera_missing_samples')}",
                f"latest_reason={reason}",
                f"latest_camera_stream_state={stream_state}",
            ],
            "recommended_next_action": "先调用 /stream/start 启动 camera-service 单路视频接入；启动后再判断是源端无帧、显示瓶颈还是 Binary 背压。",
        }

    source_frames = number_or_none(source.get("frames"))
    source_fps = number_or_none(source.get("fps"))
    if source and (not source_frames or source_frames <= 0):
        evidence.append(f"direct source frames={source_frames or 0}, fps={source_fps or 0}")
        if source.get("errors_tail"):
            evidence.append(f"direct source error={source.get('errors_tail')[-1]}")
        return {
            "bottleneck": "upstream_source_unreachable_or_not_emitting_frames",
            "severity": "blocking",
            "evidence": evidence,
            "recommended_next_action": "先恢复 Go2/视频桥接/MJPEG 服务，使源地址能直连读到连续 JPEG 帧，再验证本地显示与 Binary。",
        }

    if "unreachable" in states and (receive_fps or 0.0) < 1.0:
        evidence.append(f"stream_states={states}")
        evidence.append(f"mjpeg_receive_fps.avg={receive_fps}")
        if source_connections:
            evidence.append(f"source_connection_active_count={source_connections.get('active_count')}")
            if source_connections.get("total_count") is not None:
                evidence.append(f"source_connection_total_count={source_connections.get('total_count')}")
        if source_tcp:
            evidence.append(f"source_tcp_reachable={source_tcp.get('reachable')}")
            if source_tcp.get("error"):
                evidence.append(f"source_tcp_error={source_tcp.get('error')}")
        if int(source_connections.get("active_count") or 0) > 1:
            return {
                "bottleneck": "local_multiple_clients_pull_go2_source",
                "severity": "blocking",
                "evidence": evidence,
                "recommended_next_action": "本机存在多个到 Go2 MJPEG 源的活跃连接，先关闭浏览器直连/VLC/其它探测脚本，只保留 camera-service 单路接入。",
            }
        if source_tcp.get("reachable") is True:
            return {
                "bottleneck": "upstream_http_mjpeg_stream_closes_without_frames",
                "severity": "blocking",
                "evidence": evidence,
                "recommended_next_action": "TCP端口可达但MJPEG无帧，优先重启 Go2 视频桥/视频会话，关闭其它直连客户端，再重新启动 camera-service 单路接入。",
            }
        return {
            "bottleneck": "camera_service_cannot_receive_from_source",
            "severity": "blocking",
            "evidence": evidence,
            "recommended_next_action": "检查 Go2 IP、端口、视频服务进程、App 是否抢占视频会话，以及本机是否仍在 192.168.8.x 网段。",
        }

    if source_protocol == "mjpeg" and receive_fps is not None and publish_fps is not None and receive_fps >= 8.0 and publish_fps < receive_fps * 0.7:
        return {
            "bottleneck": "local_mjpeg_decode_or_publish_bottleneck",
            "severity": "high",
            "evidence": [
                f"mjpeg_receive_fps.avg={receive_fps}",
                f"mjpeg_publish_fps.avg={publish_fps}",
                f"mjpeg_dropped_frames={last.get('mjpeg_dropped_frames')}",
            ],
            "recommended_next_action": "继续优化本机 MJPEG decode/publish，重点看 jpeg decode 耗时、CPU 和 latest compressed drop。",
        }

    effective_display_fps = display_probe_fps if display_probe_fps is not None else display_status_fps
    upstream_for_display_fps = publish_fps if source_protocol == "mjpeg" else capture_fps
    display_target_fps = stat_avg(summary, "display_target_fps")
    display_expected_fps = upstream_for_display_fps
    if display_expected_fps is not None and display_target_fps is not None and display_target_fps > 0:
        display_expected_fps = min(display_expected_fps, display_target_fps)
    if display_expected_fps is not None and display_expected_fps >= 8.0 and effective_display_fps is not None and effective_display_fps < display_expected_fps * 0.7:
        return {
            "bottleneck": "display_stream_or_browser_delivery_bottleneck",
            "severity": "high",
            "evidence": [
                f"upstream_display_input_fps={upstream_for_display_fps}",
                f"display_expected_fps={display_expected_fps}",
                f"display_fps={effective_display_fps}",
                f"display_encode_ms.avg={stat_avg(summary, 'display_encode_ms')}",
            ],
            "recommended_next_action": "优先检查 /stream/display.mjpg、浏览器连接数量、前端 fallback/WebRTC 切换，以及显示 JPEG 编码耗时。",
        }

    if binary_queue_depth is not None and binary_queue_depth > 0:
        return {
            "bottleneck": "binary_worker_backpressure",
            "severity": "medium",
            "evidence": [
                f"binary_queue_depth={binary_queue_depth}",
                f"binary_avg_ms={binary_avg_ms}",
                f"binary_provider={last.get('binary_provider')}",
            ],
            "recommended_next_action": "保持视频显示与 Binary 分离，检查 Binary 是否退回 CPU 或 sample_fps 是否被提高。",
        }

    if source_protocol == "mjpeg" and receive_fps is not None and receive_fps < 8.0:
        return {
            "bottleneck": "upstream_low_fps_or_network_jitter",
            "severity": "medium",
            "evidence": [
                f"mjpeg_receive_fps.avg={receive_fps}",
                f"inter_frame_ms={last.get('mjpeg_inter_frame_ms')}",
                f"read_latency_ms={last.get('read_latency_ms')}",
            ],
            "recommended_next_action": "源头已可达但 FPS 偏低，重点检查 Go2 视频桥接、Wi-Fi 干扰、是否有多客户端抢流，必要时做有线/专网测试。",
        }

    return {
        "bottleneck": "no_clear_local_bottleneck_detected",
        "severity": "ok_or_needs_longer_probe",
        "evidence": [
            f"mjpeg_receive_fps.avg={receive_fps}",
            f"mjpeg_publish_fps.avg={publish_fps}",
            f"capture_fps={capture_fps}",
            f"source_protocol={source_protocol or 'unknown'}",
            f"display_fps={effective_display_fps}",
            f"binary_queue_depth={binary_queue_depth}",
        ],
        "recommended_next_action": "做 30-60 分钟长稳测试，并用 stopwatch/计时器画面单独测真实端到端视觉延迟。",
    }


def stat_avg(summary: dict[str, Any], key: str) -> float | None:
    value = (summary.get(key) or {}).get("avg")
    return number_or_none(value)


def number_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def numbers(samples: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        value = sample.get(key)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg": None, "min": None, "max": None}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for sample in samples for key in sample})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)


def get_json(url: str, *, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def quote(value: str) -> str:
    from urllib.parse import quote as url_quote

    return url_quote(value, safe="")


def configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        return


if __name__ == "__main__":
    raise SystemExit(main())
