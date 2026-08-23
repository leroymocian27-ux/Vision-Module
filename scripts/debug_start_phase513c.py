from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "runtime_debug"
LOG_DIR.mkdir(parents=True, exist_ok=True)


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

def start_identity():
    return subprocess.Popen(
        [_python_executable(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8100"],
        cwd=ROOT / "identity_service",
        stdout=(LOG_DIR / "identity_phase513c.out.log").open("ab"),
        stderr=(LOG_DIR / "identity_phase513c.err.log").open("ab"),
    )

def start_vision():
    env = os.environ.copy()
    env.update({
        "DEFAULT_RTSP_URL": os.getenv("DEBUG_RTSP_URL", "rtsp://admin:***@192.168.8.254:554/tcp/av0_1"),
        "MOCK_CAMERA_ENABLED": "false",
        "ENABLE_TRACKING": "true",
        "ENABLE_IDENTITY_BINDING": "true",
        "IDENTITY_BINDING_ASYNC": "true",
        "IDENTITY_SERVICE_URL": "http://127.0.0.1:8100",
        "IDENTITY_REQUEST_TIMEOUT_MS": "1000",
        "ENABLE_POSE": "true",
        "POSE_PROVIDER": "yolo",
        "ENABLE_BEHAVIOR": "true",
        "ENABLE_TEMPORAL": "true",
        "TRACKING_WORKER_FPS": "12",
        "POSE_WORKER_FPS": "2",
        "RESULT_PUBLISH_FPS": "10",
        "CAPTURE_BACKEND": "subprocess_opencv",
        "CAPTURE_PROCESS_FRAME_TIMEOUT_MS": "2000",
        "CAPTURE_PROCESS_RESTART_MS": "500",
        "CAPTURE_IPC_MODE": "jpeg_pipe",
        "CAPTURE_JPEG_QUALITY": "60",
        "CAPTURE_PROCESS_OUTPUT_HEIGHT": "720",
        "CAPTURE_PROCESS_WRITE_FPS": "10",
        "CAPTURE_PROCESS_MAX_RESTARTS": "0",
    })
    return subprocess.Popen(
        [_python_executable(), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        env=env,
        stdout=(LOG_DIR / "vision_phase513c.out.log").open("ab"),
        stderr=(LOG_DIR / "vision_phase513c.err.log").open("ab"),
    )

if __name__ == "__main__":
    ident = start_identity()
    time.sleep(8)
    vision = start_vision()
    print(f"identity_launcher_pid={ident.pid}")
    print(f"vision_launcher_pid={vision.pid}")
    print("press Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
            if vision.poll() is not None:
                print(f"vision exited {vision.returncode}")
                break
            if ident.poll() is not None:
                print(f"identity exited {ident.returncode}")
                break
    except KeyboardInterrupt:
        pass
    for proc in [vision, ident]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
