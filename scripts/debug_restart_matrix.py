from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen
import shutil
import sys

import requests

from debug_backend_runtime import collect_sample, summarize


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "runtime_debug"
RTSP_URL = os.getenv("DEBUG_RTSP_URL", "rtsp://admin:***@192.168.8.254:554/tcp/av0_1")


def _python_executable() -> str:
    candidates = [
        Path(r"C:\Users\YANG\.conda\envs\torchgpu\python.exe"),
        Path(sys.executable),
        Path(shutil.which("python") or ""),
        Path(r"D:\Anaconda\python.exe"),
        Path(r"D:\Python\python.exe"),
    ]
    for candidate in candidates:
        if candidate and str(candidate) and candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart vision_service with debug env matrix and sample status.")
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--cases", default="identity-off,pose-off,full")
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    existing = find_listener_pid(8000)
    if existing:
        print(f"[stop-existing] 8000 pid={existing}")
        stop_pid(existing)
        wait_port_free(8000)

    results: list[dict[str, Any]] = []
    for case_name in [item.strip() for item in args.cases.split(",") if item.strip()]:
        config = case_env(case_name)
        print(f"[case-start] {case_name}")
        process = start_vision(config)
        try:
            wait_http("http://127.0.0.1:8000/healthz", timeout=60)
            start_rtsp()
            wait_connected(timeout=60)
            rows = sample_case(duration=args.duration, interval=args.interval)
            result = {"case": case_name, "summary": summarize(rows), "rows": rows}
            results.append(result)
            print(json.dumps({"case": case_name, "summary": result["summary"]}, ensure_ascii=False, indent=2))
        finally:
            stop_process(process)
            wait_port_free(8000)

    output_path = LOG_DIR / "restart_matrix_debug.json"
    output_path.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[written] {output_path}")
    return 0


def case_env(case_name: str) -> dict[str, str]:
    base = {
        "MOCK_CAMERA_ENABLED": "false",
        "ENABLE_TRACKING": "true",
        "ENABLE_IDENTITY_BINDING": "true",
        "IDENTITY_SERVICE_URL": "http://127.0.0.1:8100",
        "IDENTITY_REQUEST_TIMEOUT_MS": "1000",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo",
        "ENABLE_BEHAVIOR": "true",
        "ENABLE_TEMPORAL": "true",
        "TRACKING_WORKER_FPS": "12",
        "POSE_WORKER_FPS": "2",
        "RESULT_PUBLISH_FPS": "10",
    }
    if case_name == "identity-off":
        base["ENABLE_IDENTITY_BINDING"] = "false"
    elif case_name == "pose-off":
        base["ENABLE_IDENTITY_BINDING"] = "false"
        base["ENABLE_POSE"] = "false"
        base["ENABLE_BEHAVIOR"] = "false"
        base["ENABLE_TEMPORAL"] = "false"
    elif case_name == "full":
        pass
    elif case_name == "identity-timeout":
        base["IDENTITY_SERVICE_URL"] = "http://127.0.0.1:8999"
        base["IDENTITY_REQUEST_TIMEOUT_MS"] = "300"
    else:
        raise ValueError(f"unknown case: {case_name}")
    return base


def start_vision(env_updates: dict[str, str]) -> subprocess.Popen:
    env = os.environ.copy()
    env.update(env_updates)
    return subprocess.Popen(
        [_python_executable(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(ROOT),
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def start_rtsp() -> None:
    payload = {"camera_id": "camera_01", "rtsp_url": RTSP_URL}
    response = requests.post("http://127.0.0.1:8000/stream/start", json=payload, timeout=10)
    response.raise_for_status()


def wait_connected(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = requests.get("http://127.0.0.1:8000/status?camera_id=camera_01", timeout=3).json()
            camera = (status.get("cameras") or [{}])[0]
            if camera.get("stream_state") == "connected":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("camera did not reach connected state")


def sample_case(duration: int, interval: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration
    index = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        row = collect_sample("camera_01")
        row["i"] = index
        rows.append(row)
        print(
            f"  {index:>3} age={row.get('frame_age_ms')} cap={row.get('capture_fps')} "
            f"det={row.get('detection_worker_fps')} trk={row.get('tracking_worker_fps')} "
            f"pub={row.get('result_publish_fps')} pose={row.get('pose_fps')} gpu={((row.get('gpu') or {}).get('gpu_util_percent'))}",
            flush=True,
        )
        index += 1
        time.sleep(max(0.0, interval - (time.monotonic() - started)))
    return rows


def wait_http(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"service did not respond: {url}")


def find_listener_pid(port: int) -> int | None:
    command = (
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=5)
    text = result.stdout.strip().splitlines()
    if not text:
        return None
    try:
        return int(text[0].strip())
    except ValueError:
        return None


def stop_pid(pid: int) -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"], timeout=10)


def wait_port_free(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_listener_pid(port) is None:
            return
        time.sleep(0.5)
    raise RuntimeError(f"port did not become free: {port}")


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=8)
    except Exception:
        process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
