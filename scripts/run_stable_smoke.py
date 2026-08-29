from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the stable Vision Service smoke check.")
    parser.add_argument("--profile", default="safe_demo", help="Profile name under configs/ or an env file path.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "stable_smoke")
    parser.add_argument("--no-start", action="store_true", help="Validate an already running service instead of starting one.")
    parser.add_argument("--keep-running", action="store_true", help="Do not stop a service started by this script.")
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_path = resolve_profile(args.profile)
    report: dict[str, Any] = {
        "status": "NOT_RUN",
        "run_id": run_id,
        "profile": str(profile_path),
        "base_url": f"http://{args.host}:{args.port}",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "artifacts": {},
        "not_run": [
            "WebSocket contract check",
            "synthetic fall event",
            "incident evidence package",
            "delivery outbox check",
            "browser visual check",
            "process cleanup deep scan",
        ],
    }

    proc: subprocess.Popen[str] | None = None
    try:
        config_result = run_step(
            report,
            "validate_config",
            lambda: run_config_validation(profile_path, output_dir / "validate_config.json"),
        )
        if not config_result["ok"]:
            report["status"] = "REVISE"
            return finish(report, output_dir, 1)

        if args.no_start:
            run_step(report, "assume_existing_service", lambda: {"message": "using existing process"})
        else:
            if is_port_open(args.host, args.port):
                raise RuntimeError(f"port already in use: {args.host}:{args.port}")
            proc = start_service(profile_path, args.host, args.port, output_dir / "uvicorn.log")
            report["artifacts"]["uvicorn_log"] = str((output_dir / "uvicorn.log").resolve())
            report["artifacts"]["pid"] = proc.pid
            run_step(report, "start_service", lambda: {"pid": proc.pid})

        base_url = f"http://{args.host}:{args.port}"
        run_step(report, "wait_healthz", lambda: wait_for_json(f"{base_url}/healthz", timeout_seconds=60))
        run_step(report, "get_status", lambda: save_json(fetch_json(f"{base_url}/status"), output_dir / "status.json"))
        if env_file_bool(profile_path, "AUTO_START_STREAM", default=False):
            run_step(report, "get_latest_frame", lambda: check_latest_frame(f"{base_url}/stream/latest-frame.jpg", output_dir / "latest-frame.jpg"))
        else:
            run_step(report, "skip_latest_frame", lambda: {"reason": "AUTO_START_STREAM=false"})
        run_step(report, "get_integration_latest", lambda: check_optional_json(f"{base_url}/integration/results/camera_01/latest", output_dir / "integration_latest.json"))

        failed = [step for step in report["steps"] if not step["ok"] and step.get("required", True)]
        report["status"] = "PASS" if not failed else "REVISE"
        return finish(report, output_dir, 0 if not failed else 1)
    except Exception as exc:
        report["status"] = "REVISE"
        report["fatal_error"] = str(exc)
        return finish(report, output_dir, 1)
    finally:
        if proc is not None and not args.keep_running:
            stop_process(proc)


def resolve_profile(profile: str) -> Path:
    candidate = Path(profile)
    if candidate.exists():
        return candidate.resolve()
    if not profile.endswith(".env"):
        profile = f"{profile}.env"
    candidate = ROOT / "configs" / profile
    if not candidate.exists():
        raise RuntimeError(f"profile not found: {candidate}")
    return candidate.resolve()


def run_step(report: dict[str, Any], name: str, fn, *, required: bool = True) -> dict[str, Any]:
    started = time.perf_counter()
    step = {"name": name, "required": required, "ok": False}
    try:
        result = fn()
        step["ok"] = True
        step["result"] = result
    except Exception as exc:
        step["error"] = str(exc)
    step["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["steps"].append(step)
    return step


def run_config_validation(profile_path: Path, json_out: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "validate_config.py"),
        "--profile",
        str(profile_path),
        "--json-out",
        str(json_out),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout or completed.stderr)
    return json.loads(json_out.read_text(encoding="utf-8"))


def start_service(profile_path: Path, host: str, port: int, log_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["VISION_SERVICE_ENV_FILE"] = str(profile_path)
    env["PYTHONUNBUFFERED"] = "1"
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    log_handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log_handle, stderr=subprocess.STDOUT, text=True)


def wait_for_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = None
    while time.time() < deadline:
        try:
            return fetch_json(url)
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"timeout waiting for {url}: {last_error}")


def fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def save_json(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path.resolve()), "keys": sorted(payload.keys())}


def check_latest_frame(url: str, path: Path) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "image/jpeg"})
    with urlopen(request, timeout=10) as response:
        body = response.read()
        headers = dict(response.headers.items())
    if len(body) < 1024:
        raise RuntimeError(f"latest frame response too small: {len(body)} bytes")
    path.write_bytes(body)
    return {
        "path": str(path.resolve()),
        "size_bytes": len(body),
        "x_frame_age_ms": headers.get("X-Frame-Age-Ms"),
        "x_camera_status": headers.get("X-Camera-Status"),
    }


def check_optional_json(url: str, path: Path) -> dict[str, Any]:
    try:
        payload = fetch_json(url)
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "NOT_READY", "http_status": 404}
        raise
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "OK", "path": str(path.resolve())}


def env_file_bool(path: Path, key: str, *, default: bool) -> bool:
    if not path.exists():
        return default
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, value = line.split("=", 1)
        if env_key.strip() == key:
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def finish(report: dict[str, Any], output_dir: Path, exit_code: int) -> int:
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary_json": str(summary_json.resolve()), "summary_md": str(summary_md.resolve())}, ensure_ascii=False, indent=2))
    return exit_code


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Stable Smoke Summary",
        "",
        f"- Status: `{report['status']}`",
        f"- Profile: `{report['profile']}`",
        f"- Base URL: `{report['base_url']}`",
        "",
        "## Steps",
        "",
    ]
    for step in report.get("steps", []):
        marker = "PASS" if step.get("ok") else "REVISE"
        lines.append(f"- `{marker}` {step['name']} ({step.get('elapsed_seconds')}s)")
        if step.get("error"):
            lines.append(f"  Error: `{step['error']}`")
    if report.get("not_run"):
        lines.extend(["", "## Not Run", ""])
        lines.extend(f"- {item}" for item in report["not_run"])
    if report.get("fatal_error"):
        lines.extend(["", "## Fatal Error", "", f"`{report['fatal_error']}`"])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
