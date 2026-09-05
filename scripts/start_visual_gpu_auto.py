"""Start the vision service on the first free port from 8000 to 8002.

Open this file in VS Code and use the Run Python File button. The selected
port is passed to start_visual_gpu.ps1, which owns the project's CUDA checks
and GPU-specific environment variables.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORTS = (8000, 8001, 8002)


def is_port_available(host: str, port: int) -> bool:
    """Return whether a TCP listener can bind to host and port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((host, port))
        return True
    except OSError:
        return False


def choose_available_port(
    host: str,
    ports: Sequence[int] = DEFAULT_PORTS,
    check: Callable[[str, int], bool] = is_port_available,
) -> int:
    for port in ports:
        if check(host, port):
            return port
    candidates = ", ".join(str(port) for port in ports)
    raise RuntimeError(f"No free startup port is available ({candidates}).")


def build_powershell_command(script_path: Path, host: str, port: int) -> list[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        raise RuntimeError("Windows PowerShell was not found on PATH.")
    return [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-HostName",
        host,
        "-Port",
        str(port),
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start camera-service with the enforced GPU launcher on ports 8000-8002."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected port and command without starting the service.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parents[1]
    gpu_launcher = project_root / "scripts" / "start_visual_gpu.ps1"
    if not gpu_launcher.is_file():
        print(f"GPU launcher not found: {gpu_launcher}", file=sys.stderr)
        return 2

    try:
        port = choose_available_port(args.host)
        command = build_powershell_command(gpu_launcher, args.host, port)
    except RuntimeError as exc:
        print(f"Startup aborted: {exc}", file=sys.stderr)
        return 2

    base_url = f"http://{args.host}:{port}"
    print("Vision Service GPU launcher")
    print(f"Selected port: {port}")
    print(f"Demo URL: {base_url}/demo/")
    print("CUDA availability will be verified before Uvicorn starts.")
    print("Press Ctrl+C in this terminal to stop the service.")
    sys.stdout.flush()

    if args.dry_run:
        print("Command:", subprocess.list2cmdline(command))
        return 0

    try:
        return subprocess.call(command, cwd=project_root)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
