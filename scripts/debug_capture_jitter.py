from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "runtime_debug"
DEFAULT_OUTPUT = LOG_DIR / "capture_jitter_debug.json"


def _get_json(url: str, timeout: float = 2.0) -> dict:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _gpu_snapshot() -> dict | None:
    query = "utilization.gpu,memory.used,memory.total,temperature.gpu"
    cmd = [
        "nvidia-smi",
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        return None
    first_line = output.strip().splitlines()[0] if output.strip() else ""
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) != 4:
        return None
    return {
        "gpu_util_percent": _to_float(parts[0]),
        "gpu_memory_used_mib": _to_float(parts[1]),
        "gpu_memory_total_mib": _to_float(parts[2]),
        "gpu_temp_c": _to_float(parts[3]),
    }


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _camera_sample(status: dict, camera_id: str | None) -> dict:
    cameras = status.get("cameras") or []
    camera = None
    if camera_id:
        camera = next((item for item in cameras if item.get("camera_id") == camera_id), None)
    if camera is None and cameras:
        camera = cameras[0]
    camera = camera or {}
    pipeline = status.get("pipeline") or {}
    pose = status.get("pose") or {}
    streaming = status.get("streaming") or {}
    return {
        "camera_id": camera.get("camera_id"),
        "stream_state": camera.get("stream_state"),
        "connected": camera.get("connected"),
        "frame_age_ms": camera.get("frame_age_ms"),
        "capture_fps": camera.get("capture_fps"),
        "read_latency_ms": camera.get("read_latency_ms"),
        "read_latency_max_ms": camera.get("read_latency_max_ms"),
        "read_timeout_count": camera.get("read_timeout_count"),
        "stale_count": camera.get("stale_count"),
        "consecutive_slow_reads": camera.get("consecutive_slow_reads"),
        "reconnect_count": camera.get("reconnect_count"),
        "reconnect_reason": camera.get("reconnect_reason"),
        "last_read_started_at": camera.get("last_read_started_at"),
        "last_read_completed_at": camera.get("last_read_completed_at"),
        "last_error": camera.get("last_error"),
        "detection_worker_fps": pipeline.get("detection_worker_fps"),
        "tracking_worker_fps": pipeline.get("tracking_worker_fps"),
        "result_publish_fps": pipeline.get("result_publish_fps"),
        "detection_to_publish_lag_ms": pipeline.get("detection_to_publish_lag_ms"),
        "pose_fps": pose.get("pose_fps"),
        "webrtc_clients": streaming.get("webrtc_clients"),
        "ws_clients": streaming.get("ws_clients"),
    }


def _max_numeric(samples: list[dict], key: str) -> float | None:
    values = [_to_float(sample.get(key)) for sample in samples]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _avg_numeric(samples: list[dict], key: str) -> float | None:
    values = [_to_float(sample.get(key)) for sample in samples]
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 2) if values else None


def _summarize(samples: list[dict], failures: list[dict], warn_ms: float) -> dict:
    reconnect_counts = [_to_float(sample.get("reconnect_count")) for sample in samples]
    reconnect_counts = [value for value in reconnect_counts if value is not None]
    reconnect_delta = 0
    if len(reconnect_counts) >= 2:
        reconnect_delta = int(reconnect_counts[-1] - reconnect_counts[0])

    timeout_counts = [_to_float(sample.get("read_timeout_count")) for sample in samples]
    timeout_counts = [value for value in timeout_counts if value is not None]
    slow_read_delta = 0
    if len(timeout_counts) >= 2:
        slow_read_delta = int(timeout_counts[-1] - timeout_counts[0])

    stale_counts = [_to_float(sample.get("stale_count")) for sample in samples]
    stale_counts = [value for value in stale_counts if value is not None]
    stale_delta = 0
    if len(stale_counts) >= 2:
        stale_delta = int(stale_counts[-1] - stale_counts[0])

    reasons: dict[str, int] = {}
    for sample in samples:
        reason = sample.get("reconnect_reason")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1

    slow_samples = [
        sample
        for sample in samples
        if (_to_float(sample.get("read_latency_ms")) or 0.0) >= warn_ms
    ]
    high_age_samples = [
        sample
        for sample in samples
        if (_to_float(sample.get("frame_age_ms")) or 0.0) >= 1000.0
    ]

    return {
        "sample_count": len(samples),
        "failure_count": len(failures),
        "max_frame_age_ms": _max_numeric(samples, "frame_age_ms"),
        "avg_frame_age_ms": _avg_numeric(samples, "frame_age_ms"),
        "max_read_latency_ms": _max_numeric(samples, "read_latency_ms"),
        "max_recorded_read_latency_ms": _max_numeric(samples, "read_latency_max_ms"),
        "avg_read_latency_ms": _avg_numeric(samples, "read_latency_ms"),
        "slow_read_samples": len(slow_samples),
        "slow_read_delta": slow_read_delta,
        "final_read_timeout_count": int(timeout_counts[-1]) if timeout_counts else 0,
        "stale_delta": stale_delta,
        "final_stale_count": int(stale_counts[-1]) if stale_counts else 0,
        "reconnect_delta": reconnect_delta,
        "final_reconnect_count": int(reconnect_counts[-1]) if reconnect_counts else 0,
        "reconnect_reasons_seen": reasons,
        "avg_capture_fps": _avg_numeric(samples, "capture_fps"),
        "min_capture_fps": min(
            [
                value
                for value in (_to_float(sample.get("capture_fps")) for sample in samples)
                if value is not None
            ],
            default=None,
        ),
        "avg_tracking_worker_fps": _avg_numeric(samples, "tracking_worker_fps"),
        "avg_result_publish_fps": _avg_numeric(samples, "result_publish_fps"),
        "high_frame_age_samples": len(high_age_samples),
        "proactive_reopen_observed": any(
            sample.get("reconnect_reason") in {"slow_read", "slow_read_sequence", "stale_frame"}
            for sample in samples
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture jitter sampler for vision_service.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--duration-sec", type=int, default=600)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--warn-ms", type=float, default=500.0)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    samples: list[dict] = []
    failures: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + max(1, args.duration_sec)

    while time.monotonic() < deadline:
        sample_started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()
        try:
            status = _get_json(f"{args.base_url}/status?camera_id={args.camera_id}")
            sample = _camera_sample(status, args.camera_id)
            sample["timestamp"] = timestamp
            gpu = _gpu_snapshot()
            if gpu:
                sample.update(gpu)
            samples.append(sample)
            print(
                "capture_sample",
                f"i={len(samples)}",
                f"state={sample.get('stream_state')}",
                f"age={sample.get('frame_age_ms')}",
                f"read={sample.get('read_latency_ms')}",
                f"cap={sample.get('capture_fps')}",
                f"reconnects={sample.get('reconnect_count')}",
                f"reason={sample.get('reconnect_reason')}",
            )
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            failure = {"timestamp": timestamp, "error": repr(exc)}
            failures.append(failure)
            print("capture_sample_failed", failure["error"])

        elapsed = time.monotonic() - sample_started
        time.sleep(max(0.0, args.interval_sec - elapsed))

    payload = {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "camera_id": args.camera_id,
        "duration_sec": args.duration_sec,
        "interval_sec": args.interval_sec,
        "summary": _summarize(samples, failures, args.warn_ms),
        "samples": samples,
        "failures": failures,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("capture_jitter_debug_written", output)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
