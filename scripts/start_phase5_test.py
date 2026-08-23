from __future__ import annotations

import atexit
import os
import signal
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
IDENTITY_DIR = ROOT / "identity_service"
DEMO_URL = "http://127.0.0.1:8000/demo?v=phase53"


def _print(message: str) -> None:
    print(message, flush=True)


def _env_with(updates: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(updates)
    return env


def _start_process(name: str, cwd: Path, args: list[str], env: dict[str, str] | None = None) -> subprocess.Popen:
    _print(f"[start] {name}")
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        env=env,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )


def _conda_executable() -> str:
    for candidate in ("conda", "conda.bat", "conda.exe", "conda.cmd"):
        path = shutil.which(candidate)
        if path:
            return path
    raise RuntimeError("conda was not found on PATH. Run this script from an Anaconda/Miniconda PowerShell.")


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


def _wait_http(name: str, url: str, timeout_sec: float) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 500:
                    _print(f"[ok] {name} is responding: {url}")
                    return True
        except URLError:
            pass
        except Exception:
            pass
        time.sleep(0.5)
    _print(f"[warn] {name} did not respond within {timeout_sec:.0f}s: {url}")
    return False


def _stop_process(name: str, process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return

    _print(f"[stop] {name}")
    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=8)
    except Exception:
        process.kill()


def main() -> int:
    identity_process: subprocess.Popen | None = None
    vision_process: subprocess.Popen | None = None

    def cleanup() -> None:
        _stop_process("Vision Service", vision_process)
        _stop_process("Identity Service", identity_process)

    atexit.register(cleanup)
    conda = _conda_executable()

    identity_process = _start_process(
        "Identity Service",
        IDENTITY_DIR,
        [
            _python_executable(),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8100",
        ],
    )

    _wait_http("Identity Service", "http://127.0.0.1:8100/healthz", 60)

    vision_env = _env_with(
        {
            "ENABLE_TRACKING": "true",
            "ENABLE_IDENTITY_BINDING": "true",
            "IDENTITY_SERVICE_URL": "http://127.0.0.1:8100",
            "IDENTITY_REQUEST_TIMEOUT_MS": "1000",
            "ENABLE_POSE": "true",
            "POSE_PROVIDER": "mmpose",
            "RTMPOSE_CONFIG_PATH": "models/rtmpose/rtmpose_l_pose_adaptation_384x288.py",
            "RTMPOSE_CHECKPOINT_PATH": "models/rtmpose/rtmpose-l-pose-adapted-best.pth",
            "RTMPOSE_DEVICE": "cuda:0",
            "POSE_WORKER_FPS": "3",
            "POSE_FPS": "3",
            "POSE_SKIP_WHEN_INFERENCE_BUSY": "true",
            "POSE_MAX_INFERENCE_MS": "1500",
            "POSE_CROP_PADDING_RATIO": "0.06",
            "POSE_FALLEN_CROP_PADDING_RATIO": "0.14",
            "POSE_MIN_SKELETON_CONFIDENCE": "0.35",
            "POSE_MIN_KEYPOINT_INSIDE_RATIO": "0.65",
            "POSE_MIN_FALLEN_KEYPOINT_INSIDE_RATIO": "0.60",
            "POSE_MIN_CANDIDATE_IOU": "0.25",
            "POSE_MIN_FALLEN_CANDIDATE_IOU": "0.15",
            "POSE_MAX_TRACKING_FRAME_DELTA": "2",
            "POSE_MAX_FRAME_AGE_MS": "800",
            "POSE_RESULT_TTL_MS": "800",
            "POSE_SLOW_INFERENCE_CIRCUIT_BREAKER_COUNT": "3",
            "POSE_CIRCUIT_BREAKER_COOLDOWN_MS": "10000",
            "ENABLE_BEHAVIOR": "true",
            "ENABLE_TEMPORAL": "true",
            "TRACKING_WORKER_FPS": "12",
            "RESULT_PUBLISH_FPS": "10",
        }
    )
    vision_process = _start_process(
        "Vision Service",
        ROOT,
        [
            _python_executable(),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        env=vision_env,
    )

    _wait_http("Vision Service", "http://127.0.0.1:8000/healthz", 60)

    _print("")
    _print("[ready] Phase 5 test stack is running.")
    _print(f"[demo]  {DEMO_URL}")
    _print("[stop]  Press Ctrl+C in this window to stop both services.")
    _print("")
    webbrowser.open(DEMO_URL)

    try:
        while True:
            if identity_process.poll() is not None:
                _print(f"[exit] Identity Service exited with code {identity_process.returncode}")
                return identity_process.returncode or 1
            if vision_process.poll() is not None:
                _print(f"[exit] Vision Service exited with code {vision_process.returncode}")
                return vision_process.returncode or 1
            time.sleep(1)
    except KeyboardInterrupt:
        _print("\n[stop] Ctrl+C received.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
