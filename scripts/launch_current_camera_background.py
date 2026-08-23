from __future__ import annotations

import subprocess
import sys
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
OUT_LOG = ROOT / "logs" / "runtime_debug" / "current_camera.out.log"
ERR_LOG = ROOT / "logs" / "runtime_debug" / "current_camera.err.log"


def _default_python() -> Path:
    candidates = [
        Path(r"C:\Users\YANG\.conda\envs\torchgpu\python.exe"),
        Path(sys.executable),
        Path(shutil.which("python") or ""),
        Path(r"D:\Anaconda\python.exe"),
        Path(r"D:\Python\python.exe"),
    ]
    for candidate in candidates:
        if candidate and str(candidate) and candidate.exists():
            return candidate
    return Path(sys.executable)


def main() -> int:
    python_exe = _default_python()
    OUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    out = OUT_LOG.open("w", encoding="utf-8")
    err = ERR_LOG.open("w", encoding="utf-8")
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    if sys.platform == "win32":
        creationflags |= subprocess.DETACHED_PROCESS
    process = subprocess.Popen(
        [str(python_exe), "scripts/start_current_camera.py", "--no-wait"],
        cwd=str(ROOT),
        stdout=out,
        stderr=err,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
