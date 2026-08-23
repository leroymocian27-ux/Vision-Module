from __future__ import annotations

import subprocess
import sys
from typing import TextIO


def is_process_alive(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is None


def terminate_process(proc: subprocess.Popen | None, timeout_sec: float = 2.0) -> int | None:
    if proc is None:
        return None
    if proc.poll() is not None:
        return proc.returncode
    try:
        proc.terminate()
        return proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        if sys.platform.startswith("win"):
            _taskkill(proc.pid)
        else:
            proc.kill()
        try:
            return proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            return proc.poll()


def drain_stderr(stream: TextIO | None, on_line) -> None:
    if stream is None:
        return
    try:
        for line in iter(stream.readline, ""):
            line = line.strip()
            if line:
                on_line(line)
    except Exception as exc:
        on_line(f"capture_process_stderr_reader_failed: {exc}")


def _taskkill(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
