from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that a service process and TCP port were released.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    result = check_process_cleanup(
        pid=args.pid,
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def check_process_cleanup(*, pid: int, host: str, port: int, timeout_seconds: float = 20.0) -> dict[str, Any]:
    deadline = time.time() + max(0.1, timeout_seconds)
    samples: list[dict[str, Any]] = []
    while True:
        process_alive = process_exists(pid)
        port_open = is_port_open(host, port)
        sample = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "process_alive": process_alive,
            "port_open": port_open,
        }
        samples.append(sample)
        if not process_alive and not port_open:
            return {
                "status": "PASS",
                "pid": pid,
                "host": host,
                "port": port,
                "samples": samples,
            }
        if time.time() >= deadline:
            return {
                "status": "REVISE",
                "pid": pid,
                "host": host,
                "port": port,
                "samples": samples,
                "last_state": sample,
            }
        time.sleep(0.5)


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_exists(pid: int) -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        text=True,
        capture_output=True,
        timeout=10,
    )
    output = (completed.stdout or "").strip()
    if not output or "No tasks are running" in output:
        return False
    return f'"{pid}"' in output or f",{pid}," in output


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def terminate_process(pid: int, *, graceful_timeout_seconds: float = 15.0) -> dict[str, Any]:
    if pid <= 0:
        return {"status": "PASS", "pid": pid, "action": "invalid_pid_already_absent"}
    if not process_exists(pid):
        return {"status": "PASS", "pid": pid, "action": "already_absent"}
    if os.name == "nt":
        return _terminate_windows_process(pid, graceful_timeout_seconds=graceful_timeout_seconds)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"status": "PASS", "pid": pid, "action": "already_absent"}
    deadline = time.time() + graceful_timeout_seconds
    while time.time() < deadline:
        if not process_exists(pid):
            return {"status": "PASS", "pid": pid, "action": "terminated"}
        time.sleep(0.5)
    os.kill(pid, signal.SIGKILL)
    return {"status": "REVISE", "pid": pid, "action": "force_killed_after_timeout"}


def _terminate_windows_process(pid: int, *, graceful_timeout_seconds: float) -> dict[str, Any]:
    subprocess.run(["taskkill", "/PID", str(pid)], text=True, capture_output=True, timeout=10)
    deadline = time.time() + graceful_timeout_seconds
    while time.time() < deadline:
        if not process_exists(pid):
            return {"status": "PASS", "pid": pid, "action": "terminated"}
        time.sleep(0.5)
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], text=True, capture_output=True, timeout=10)
    return {"status": "REVISE", "pid": pid, "action": "force_killed_after_timeout"}


if __name__ == "__main__":
    raise SystemExit(main())
