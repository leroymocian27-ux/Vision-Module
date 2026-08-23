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
DEFAULT_OUTPUT = LOG_DIR / "phase5_12_long_run.json"


def _get_json(url: str, timeout: float = 2.0) -> dict:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gpu_snapshot() -> dict | None:
    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2)
    except Exception:
        return None
    line = output.strip().splitlines()[0] if output.strip() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != 4:
        return None
    return {
        "gpu_util_percent": _to_float(parts[0]),
        "gpu_memory_used_mib": _to_float(parts[1]),
        "gpu_memory_total_mib": _to_float(parts[2]),
        "gpu_temp_c": _to_float(parts[3]),
    }


def _python_process_snapshot() -> list[dict]:
    script = r"""
$cpuByPid = @{}
Get-CimInstance Win32_PerfFormattedData_PerfProc_Process |
  ForEach-Object { $cpuByPid[[int]$_.IDProcess] = [double]$_.PercentProcessorTime }
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'python.exe' -or $_.Name -eq 'conda.exe' } |
  Select-Object ProcessId,Name,CommandLine,
    @{Name='WorkingSetMB';Expression={[math]::Round(($_.WorkingSetSize / 1MB), 2)}},
    @{Name='PrivateMB';Expression={[math]::Round(($_.PrivatePageCount / 1MB), 2)}},
    @{Name='CpuPercent';Expression={$cpuByPid[[int]$_.ProcessId]}} |
  ConvertTo-Json -Depth 3
"""
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    try:
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        return []
    if not output.strip():
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []


def _select_camera(status: dict, camera_id: str | None) -> dict:
    cameras = status.get("cameras") or []
    if camera_id:
        for camera in cameras:
            if camera.get("camera_id") == camera_id:
                return camera
    return cameras[0] if cameras else {}


def _sample_status(status: dict, camera_id: str | None) -> dict:
    camera = _select_camera(status, camera_id)
    pipeline = status.get("pipeline") or {}
    identity = status.get("identity") or {}
    temporal = status.get("temporal") or {}
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
        "reconnect_count": camera.get("reconnect_count"),
        "reconnect_reason": camera.get("reconnect_reason"),
        "consecutive_slow_reads": camera.get("consecutive_slow_reads"),
        "capture_backend": camera.get("capture_backend"),
        "capture_process_alive": camera.get("capture_process_alive"),
        "capture_process_pid": camera.get("capture_process_pid"),
        "capture_process_restart_count": camera.get("capture_process_restart_count"),
        "capture_process_last_frame_age_ms": camera.get("capture_process_last_frame_age_ms"),
        "capture_process_last_error": camera.get("capture_process_last_error"),
        "capture_process_last_exit_code": camera.get("capture_process_last_exit_code"),
        "capture_ipc_decode_errors": camera.get("capture_ipc_decode_errors"),
        "capture_ipc_dropped_frames": camera.get("capture_ipc_dropped_frames"),
        "capture_output_width": camera.get("capture_output_width"),
        "capture_output_height": camera.get("capture_output_height"),
        "last_error": camera.get("last_error"),
        "detection_worker_fps": pipeline.get("detection_worker_fps"),
        "tracking_worker_fps": pipeline.get("tracking_worker_fps"),
        "result_publish_fps": pipeline.get("result_publish_fps"),
        "detection_to_publish_lag_ms": pipeline.get("detection_to_publish_lag_ms"),
        "pipeline_last_error": pipeline.get("last_error"),
        "pose_fps": pose.get("pose_fps"),
        "identity_cache_age_ms": identity.get("cache_age_ms"),
        "identity_last_match_latency_ms": identity.get("last_match_latency_ms"),
        "identity_pending_requests": identity.get("pending_requests"),
        "identity_skipped_due_to_inflight": identity.get("skipped_due_to_inflight"),
        "identity_last_error": identity.get("last_error"),
        "temporal_last_error": temporal.get("last_error"),
        "webrtc_clients": streaming.get("webrtc_clients"),
        "ws_clients": streaming.get("ws_clients"),
    }


def _values(samples: list[dict], key: str) -> list[float]:
    values = [_to_float(sample.get(key)) for sample in samples]
    return [value for value in values if value is not None]


def _avg(samples: list[dict], key: str) -> float | None:
    values = _values(samples, key)
    return round(sum(values) / len(values), 2) if values else None


def _max(samples: list[dict], key: str) -> float | None:
    values = _values(samples, key)
    return max(values) if values else None


def _min(samples: list[dict], key: str) -> float | None:
    values = _values(samples, key)
    return min(values) if values else None


def _delta(samples: list[dict], key: str) -> int:
    values = _values(samples, key)
    if len(values) < 2:
        return 0
    return int(values[-1] - values[0])


def _summarize(samples: list[dict], failures: list[dict], duration_sec: int) -> dict:
    connected_count = sum(1 for sample in samples if sample.get("stream_state") == "connected")
    high_age = [sample for sample in samples if (_to_float(sample.get("frame_age_ms")) or 0) > 3000]
    pipeline_errors = [sample for sample in samples if sample.get("pipeline_last_error")]
    temporal_errors = [sample for sample in samples if sample.get("temporal_last_error")]
    identity_errors = [sample for sample in samples if sample.get("identity_last_error")]
    capture_errors = [sample for sample in samples if sample.get("capture_process_last_error")]
    python_ws_values = _values(samples, "vision_python_working_set_mb")
    identity_ws_values = _values(samples, "identity_python_working_set_mb")
    return {
        "duration_sec": duration_sec,
        "sample_count": len(samples),
        "failure_count": len(failures),
        "connected_ratio": round(connected_count / len(samples), 4) if samples else 0.0,
        "max_frame_age_ms": _max(samples, "frame_age_ms"),
        "avg_frame_age_ms": _avg(samples, "frame_age_ms"),
        "frame_age_over_3000_count": len(high_age),
        "avg_capture_fps": _avg(samples, "capture_fps"),
        "min_capture_fps": _min(samples, "capture_fps"),
        "max_read_latency_ms": _max(samples, "read_latency_ms"),
        "max_recorded_read_latency_ms": _max(samples, "read_latency_max_ms"),
        "read_timeout_delta": _delta(samples, "read_timeout_count"),
        "stale_delta": _delta(samples, "stale_count"),
        "reconnect_delta": _delta(samples, "reconnect_count"),
        "capture_process_restart_delta": _delta(samples, "capture_process_restart_count"),
        "capture_ipc_decode_error_delta": _delta(samples, "capture_ipc_decode_errors"),
        "capture_ipc_dropped_frame_delta": _delta(samples, "capture_ipc_dropped_frames"),
        "max_capture_process_last_frame_age_ms": _max(samples, "capture_process_last_frame_age_ms"),
        "capture_process_error_count": len(capture_errors),
        "avg_detection_worker_fps": _avg(samples, "detection_worker_fps"),
        "avg_tracking_worker_fps": _avg(samples, "tracking_worker_fps"),
        "min_tracking_worker_fps": _min(samples, "tracking_worker_fps"),
        "avg_result_publish_fps": _avg(samples, "result_publish_fps"),
        "min_result_publish_fps": _min(samples, "result_publish_fps"),
        "avg_pose_fps": _avg(samples, "pose_fps"),
        "max_detection_to_publish_lag_ms": _max(samples, "detection_to_publish_lag_ms"),
        "avg_detection_to_publish_lag_ms": _avg(samples, "detection_to_publish_lag_ms"),
        "max_identity_pending_requests": _max(samples, "identity_pending_requests"),
        "identity_skipped_due_to_inflight_delta": _delta(samples, "identity_skipped_due_to_inflight"),
        "pipeline_error_count": len(pipeline_errors),
        "temporal_error_count": len(temporal_errors),
        "identity_error_count": len(identity_errors),
        "avg_gpu_util_percent": _avg(samples, "gpu_util_percent"),
        "max_gpu_memory_used_mib": _max(samples, "gpu_memory_used_mib"),
        "vision_python_working_set_delta_mb": (
            round(python_ws_values[-1] - python_ws_values[0], 2) if len(python_ws_values) >= 2 else None
        ),
        "identity_python_working_set_delta_mb": (
            round(identity_ws_values[-1] - identity_ws_values[0], 2) if len(identity_ws_values) >= 2 else None
        ),
        "sustained_stall_observed": bool(high_age),
    }


def _classify_processes(processes: list[dict]) -> dict:
    result: dict[str, float | None] = {
        "vision_python_working_set_mb": None,
        "vision_python_cpu_percent": None,
        "identity_python_working_set_mb": None,
        "identity_python_cpu_percent": None,
    }
    for proc in processes:
        command = str(proc.get("CommandLine") or "")
        if "uvicorn" not in command or "python.exe" not in str(proc.get("Name") or ""):
            continue
        if "--port 8000" in command:
            result["vision_python_working_set_mb"] = _to_float(proc.get("WorkingSetMB"))
            result["vision_python_cpu_percent"] = _to_float(proc.get("CpuPercent"))
        elif "--port 8100" in command:
            result["identity_python_working_set_mb"] = _to_float(proc.get("WorkingSetMB"))
            result["identity_python_cpu_percent"] = _to_float(proc.get("CpuPercent"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 5.12 long-run stability sampler.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--duration-sec", type=int, default=1800)
    parser.add_argument("--interval-sec", type=float, default=1.0)
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
            sample = _sample_status(status, args.camera_id)
            sample["timestamp"] = timestamp
            gpu = _gpu_snapshot()
            if gpu:
                sample.update(gpu)
            sample.update(_classify_processes(_python_process_snapshot()))
            samples.append(sample)
            print(
                "phase5_12_sample",
                f"i={len(samples)}",
                f"state={sample.get('stream_state')}",
                f"age={sample.get('frame_age_ms')}",
                f"read={sample.get('read_latency_ms')}",
                f"track={sample.get('tracking_worker_fps')}",
                f"publish={sample.get('result_publish_fps')}",
                f"reconnects={sample.get('reconnect_count')}",
            )
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            failures.append({"timestamp": timestamp, "error": repr(exc)})
            print("phase5_12_sample_failed", repr(exc))

        elapsed = time.monotonic() - sample_started
        time.sleep(max(0.0, args.interval_sec - elapsed))

    payload = {
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "camera_id": args.camera_id,
        "duration_sec": args.duration_sec,
        "interval_sec": args.interval_sec,
        "summary": _summarize(samples, failures, args.duration_sec),
        "samples": samples,
        "failures": failures,
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("phase5_12_long_run_written", output)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
