from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from process_cleanup_check import check_process_cleanup, is_port_open
from run_stable_smoke import check_latest_frame, fetch_json, resolve_profile, run_config_validation, save_json, wait_for_json


ROOT = Path(__file__).resolve().parents[1]
STAGE = "S2_STARTUP_SHUTDOWN_AND_PROCESS_STABILITY"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S2 startup/shutdown/process stability gate.")
    parser.add_argument("--profile", default="safe_demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "stabilization" / STAGE)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    profile_path = resolve_profile(args.profile)
    report: dict[str, Any] = {
        "status": "NOT_RUN",
        "stage": STAGE,
        "run_id": run_id,
        "profile": str(profile_path),
        "host": args.host,
        "port": args.port,
        "cycles_requested": args.cycles,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "cycles": [],
        "not_run": [
            "real RTSP startup/shutdown",
            "synthetic fall event",
            "incident evidence package",
            "WebSocket contract",
            "browser visual check",
        ],
        "not_in_scope": [
            "Robot Assist",
            "Go2 control",
            "Qwen/Ollama VLM advisory",
            "real event Delivery",
            "real main-system POST",
        ],
    }

    try:
        add_step(report, "validate_config", lambda: run_config_validation(profile_path, output_dir / "validate_config.json"))
        for index in range(1, max(1, args.cycles) + 1):
            cycle_result = run_cycle(
                index=index,
                profile_path=profile_path,
                host=args.host,
                port=args.port,
                output_dir=output_dir,
                expect_latest_frame=_env_file_bool(profile_path, "AUTO_START_STREAM", default=False),
            )
            report["cycles"].append(cycle_result)
            if cycle_result["status"] != "PASS":
                report["status"] = "REVISE"
                return finish(report, output_dir, 1)
        report["status"] = "PASS"
        return finish(report, output_dir, 0)
    except PortBlockedError as exc:
        report["status"] = "BLOCKED"
        report["fatal_error"] = str(exc)
        return finish(report, output_dir, 2)
    except Exception as exc:
        report["status"] = "REVISE"
        report["fatal_error"] = str(exc)
        return finish(report, output_dir, 1)


class PortBlockedError(RuntimeError):
    pass


def add_step(report: dict[str, Any], name: str, fn) -> dict[str, Any]:
    started = time.perf_counter()
    step = {"name": name, "ok": False}
    try:
        step["result"] = fn()
        step["ok"] = True
    except Exception as exc:
        step["error"] = str(exc)
        report["steps"].append(step)
        raise
    finally:
        step["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["steps"].append(step)
    return step


def run_cycle(*, index: int, profile_path: Path, host: str, port: int, output_dir: Path, expect_latest_frame: bool) -> dict[str, Any]:
    cycle_dir = output_dir / f"cycle_{index:02d}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    cycle: dict[str, Any] = {
        "index": index,
        "status": "NOT_RUN",
        "steps": [],
        "artifacts": {},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    proc: subprocess.Popen[Any] | None = None
    try:
        if is_port_open(host, port):
            raise PortBlockedError(f"port already in use before cycle {index}: {host}:{port}")
        proc = start_service(profile_path, host, port, cycle_dir / "uvicorn.log")
        cycle["artifacts"]["uvicorn_log"] = str((cycle_dir / "uvicorn.log").resolve())
        cycle["pid"] = proc.pid
        cycle_step(cycle, "start_service", lambda: {"pid": proc.pid})

        base_url = f"http://{host}:{port}"
        cycle_step(cycle, "wait_healthz", lambda: wait_for_json(f"{base_url}/healthz", timeout_seconds=60))
        cycle_step(cycle, "get_status", lambda: _check_status(fetch_json(f"{base_url}/status"), cycle_dir / "status.json"))
        if expect_latest_frame:
            cycle_step(cycle, "get_latest_frame", lambda: check_latest_frame(f"{base_url}/stream/latest-frame.jpg", cycle_dir / "latest-frame.jpg"))
        else:
            cycle_step(cycle, "skip_latest_frame", lambda: {"reason": "AUTO_START_STREAM=false"})
        cycle_step(cycle, "stop_service", lambda: stop_process(proc))
        cycle_step(
            cycle,
            "process_cleanup_check",
            lambda: _cleanup_or_raise(check_process_cleanup(pid=proc.pid, host=host, port=port, timeout_seconds=20)),
        )
        cycle["status"] = "PASS"
        return cycle
    except PortBlockedError:
        cycle["status"] = "BLOCKED"
        raise
    except Exception as exc:
        cycle["status"] = "REVISE"
        cycle["error"] = str(exc)
        if proc is not None:
            try:
                stop_process(proc)
                cleanup = check_process_cleanup(pid=proc.pid, host=host, port=port, timeout_seconds=20)
                cycle["cleanup_after_error"] = cleanup
            except Exception as cleanup_exc:
                cycle["cleanup_after_error"] = {"status": "REVISE", "error": str(cleanup_exc)}
        return cycle
    finally:
        cycle["finished_at"] = datetime.now(timezone.utc).isoformat()


def cycle_step(cycle: dict[str, Any], name: str, fn) -> dict[str, Any]:
    started = time.perf_counter()
    step = {"name": name, "ok": False}
    try:
        result = fn()
        step["result"] = result
        step["ok"] = True
    except Exception as exc:
        step["error"] = str(exc)
        cycle["steps"].append(step)
        raise
    finally:
        step["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    cycle["steps"].append(step)
    return step


def start_service(profile_path: Path, host: str, port: int, log_path: Path) -> subprocess.Popen[Any]:
    env = os.environ.copy()
    env["VISION_SERVICE_ENV_FILE"] = str(profile_path)
    env["PYTHONUNBUFFERED"] = "1"
    command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    log_handle = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log_handle, stderr=subprocess.STDOUT, text=True)


def stop_process(proc: subprocess.Popen[Any]) -> dict[str, Any]:
    if proc.poll() is not None:
        return {"status": "PASS", "pid": proc.pid, "action": "already_exited", "returncode": proc.returncode}
    proc.terminate()
    try:
        returncode = proc.wait(timeout=20)
        return {"status": "PASS", "pid": proc.pid, "action": "terminated", "returncode": returncode}
    except subprocess.TimeoutExpired:
        proc.kill()
        returncode = proc.wait(timeout=10)
        return {"status": "REVISE", "pid": proc.pid, "action": "force_killed_after_timeout", "returncode": returncode}


def _check_status(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    status = save_json(payload, path)
    service_status = payload.get("service_status")
    runtime_profile = payload.get("runtime_profile")
    if service_status != "running":
        raise RuntimeError(f"unexpected service_status: {service_status}")
    if runtime_profile != "safe_demo":
        raise RuntimeError(f"unexpected runtime_profile: {runtime_profile}")
    status["service_status"] = service_status
    status["runtime_profile"] = runtime_profile
    return status


def _cleanup_or_raise(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "PASS":
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def _env_file_bool(path: Path, key: str, *, default: bool) -> bool:
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


def finish(report: dict[str, Any], output_dir: Path, exit_code: int) -> int:
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "summary_json": str(summary_json.resolve()), "summary_md": str(summary_md.resolve())}, ensure_ascii=False, indent=2))
    return exit_code


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# S2 Startup Shutdown And Process Stability",
        "",
        f"- Status: `{report['status']}`",
        f"- Profile: `{report['profile']}`",
        f"- Host: `{report['host']}`",
        f"- Port: `{report['port']}`",
        f"- Cycles requested: `{report['cycles_requested']}`",
        "",
        "## Top-Level Steps",
        "",
    ]
    for step in report.get("steps", []):
        marker = "PASS" if step.get("ok") else "REVISE"
        lines.append(f"- `{marker}` {step['name']} ({step.get('elapsed_seconds')}s)")
    lines.extend(["", "## Cycles", ""])
    for cycle in report.get("cycles", []):
        lines.append(f"- Cycle {cycle['index']}: `{cycle['status']}`")
        for step in cycle.get("steps", []):
            marker = "PASS" if step.get("ok") else "REVISE"
            lines.append(f"  - `{marker}` {step['name']} ({step.get('elapsed_seconds')}s)")
    if report.get("not_run"):
        lines.extend(["", "## Not Run", ""])
        lines.extend(f"- {item}" for item in report["not_run"])
    if report.get("not_in_scope"):
        lines.extend(["", "## Not In Scope", ""])
        lines.extend(f"- {item}" for item in report["not_in_scope"])
    if report.get("fatal_error"):
        lines.extend(["", "## Fatal Error", "", f"`{report['fatal_error']}`"])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
