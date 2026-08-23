from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "runtime_debug"


@dataclass
class PythonProcess:
    pid: int
    cpu_seconds: float
    ws_mb: float
    pm_mb: float
    command_line: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample backend runtime health for vision_service.")
    parser.add_argument("--duration", type=int, default=600, help="Sampling duration in seconds.")
    parser.add_argument("--interval", type=float, default=1.0, help="Sampling interval in seconds.")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--output-prefix", default="backend_runtime")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + args.duration
    sample_index = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        row = collect_sample(args.camera_id)
        row["i"] = sample_index
        row["sample_started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rows.append(row)
        print(compact_line(row), flush=True)
        sample_index += 1
        elapsed = time.monotonic() - started
        time.sleep(max(0.0, args.interval - elapsed))

    summary = summarize(rows)
    json_path = LOG_DIR / f"{args.output_prefix}.json"
    csv_path = LOG_DIR / f"{args.output_prefix}.csv"
    json_path.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_csv(csv_path, rows)
    print(json.dumps({"summary": summary, "json": str(json_path), "csv": str(csv_path)}, ensure_ascii=False, indent=2))
    return 0


def collect_sample(camera_id: str) -> dict[str, Any]:
    status: dict[str, Any] | None
    status_error: str | None = None
    started = time.monotonic()
    try:
        response = requests.get(f"http://127.0.0.1:8000/status?camera_id={camera_id}", timeout=3)
        response.raise_for_status()
        status = response.json()
    except Exception as exc:  # diagnostic script
        status = None
        status_error = str(exc)
    status_ms = round((time.monotonic() - started) * 1000, 2)

    python_processes = get_python_processes()
    gpu = get_gpu_snapshot()

    row: dict[str, Any] = {
        "status_ok": status is not None,
        "status_error": status_error,
        "status_request_ms": status_ms,
        "python_processes": [process.__dict__ for process in python_processes],
        "gpu": gpu,
    }
    if status:
        camera = first(status.get("cameras"))
        detection = first(status.get("detection"))
        streaming = status.get("streaming") or {}
        tracking = status.get("tracking") or {}
        pose = status.get("pose") or {}
        behavior = status.get("behavior") or {}
        temporal = status.get("temporal") or {}
        pipeline = status.get("pipeline") or {}
        row.update(
            {
                "stream_state": camera.get("stream_state") if camera else None,
                "frame_age_ms": camera.get("frame_age_ms") if camera else None,
                "capture_fps": camera.get("capture_fps") if camera else None,
                "reconnect_count": camera.get("reconnect_count") if camera else None,
                "camera_last_error": camera.get("last_error") if camera else None,
                "detection_fps": detection.get("detection_fps") if detection else None,
                "detection_latency_ms": detection.get("inference_latency_ms") if detection else None,
                "detection_error": detection.get("last_error") if detection else None,
                "tracking_state": tracking.get("tracking_state"),
                "tracking_fps": tracking.get("tracking_fps"),
                "tracking_worker_fps": pipeline.get("tracking_worker_fps"),
                "tracking_error": tracking.get("last_error"),
                "tracked_objects_count": tracking.get("tracked_objects_count"),
                "pose_fps": pose.get("pose_fps"),
                "pose_error": pose.get("last_error"),
                "behavior_state": behavior.get("state"),
                "behavior_error": behavior.get("last_error"),
                "temporal_state": temporal.get("fall_state"),
                "temporal_error": temporal.get("last_error"),
                "detection_worker_fps": pipeline.get("detection_worker_fps"),
                "result_publish_fps": pipeline.get("result_publish_fps"),
                "latest_detection_age_ms": pipeline.get("latest_detection_age_ms"),
                "latest_tracking_age_ms": pipeline.get("latest_tracking_age_ms"),
                "latest_pose_age_ms": pipeline.get("latest_pose_age_ms"),
                "detection_to_publish_lag_ms": pipeline.get("detection_to_publish_lag_ms"),
                "pipeline_error": pipeline.get("last_error"),
                "ws_clients": streaming.get("ws_clients"),
                "webrtc_clients": streaming.get("webrtc_clients"),
            }
        )
    return row


def first(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value:
        return value[0]
    return None


def get_python_processes() -> list[PythonProcess]:
    command = (
        "Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
        "ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; "
        "if ($p) { [pscustomobject]@{ ProcessId=$_.ProcessId; CPU=$p.CPU; "
        "WSMB=[math]::Round($p.WorkingSet64/1MB,1); PMMB=[math]::Round($p.PrivateMemorySize64/1MB,1); "
        "CommandLine=$_.CommandLine } } } | ConvertTo-Json -Depth 4"
    )
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=5)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        payload = json.loads(result.stdout)
        items = payload if isinstance(payload, list) else [payload]
        return [
            PythonProcess(
                pid=int(item.get("ProcessId") or 0),
                cpu_seconds=float(item.get("CPU") or 0.0),
                ws_mb=float(item.get("WSMB") or 0.0),
                pm_mb=float(item.get("PMMB") or 0.0),
                command_line=str(item.get("CommandLine") or ""),
            )
            for item in items
        ]
    except Exception:
        return []


def get_gpu_snapshot() -> dict[str, Any] | None:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        first_line = result.stdout.splitlines()[0]
        util, mem_used, mem_total, temp, power = [part.strip() for part in first_line.split(",")[:5]]
        return {
            "gpu_util_percent": to_float(util),
            "gpu_memory_used_mb": to_float(mem_used),
            "gpu_memory_total_mb": to_float(mem_total),
            "gpu_temp_c": to_float(temp),
            "gpu_power_w": to_float(power),
        }
    except Exception:
        return None


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def compact_line(row: dict[str, Any]) -> str:
    return (
        f"{row.get('i', '-'):>3} "
        f"ok={row.get('status_ok')} "
        f"age={row.get('frame_age_ms')} "
        f"cap={row.get('capture_fps')} "
        f"det={row.get('detection_worker_fps')} "
        f"trk={row.get('tracking_worker_fps')} "
        f"pub={row.get('result_publish_fps')} "
        f"pose={row.get('pose_fps')} "
        f"lag={row.get('detection_to_publish_lag_ms')} "
        f"ws={row.get('ws_clients')} "
        f"rtc={row.get('webrtc_clients')} "
        f"gpu={((row.get('gpu') or {}).get('gpu_util_percent'))}"
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_keys = [
        "frame_age_ms",
        "capture_fps",
        "detection_worker_fps",
        "tracking_worker_fps",
        "result_publish_fps",
        "pose_fps",
        "detection_to_publish_lag_ms",
        "ws_clients",
        "webrtc_clients",
    ]
    summary: dict[str, Any] = {
        "samples": len(rows),
        "status_failures": sum(1 for row in rows if not row.get("status_ok")),
    }
    for key in numeric_keys:
        values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
        if values:
            summary[key] = {
                "min": round(min(values), 3),
                "avg": round(sum(values) / len(values), 3),
                "max": round(max(values), 3),
            }
    gpu_values = [
        float(row["gpu"]["gpu_util_percent"])
        for row in rows
        if isinstance(row.get("gpu"), dict) and isinstance(row["gpu"].get("gpu_util_percent"), (int, float))
    ]
    if gpu_values:
        summary["gpu_util_percent"] = {
            "min": round(min(gpu_values), 3),
            "avg": round(sum(gpu_values) / len(gpu_values), 3),
            "max": round(max(gpu_values), 3),
        }
    return summary


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "i",
        "sample_started_at",
        "status_ok",
        "status_error",
        "status_request_ms",
        "stream_state",
        "frame_age_ms",
        "capture_fps",
        "detection_worker_fps",
        "tracking_worker_fps",
        "result_publish_fps",
        "pose_fps",
        "detection_to_publish_lag_ms",
        "latest_detection_age_ms",
        "latest_tracking_age_ms",
        "latest_pose_age_ms",
        "ws_clients",
        "webrtc_clients",
        "reconnect_count",
        "pipeline_error",
        "camera_last_error",
        "pose_error",
        "temporal_error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in columns})


if __name__ == "__main__":
    raise SystemExit(main())
