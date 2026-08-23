from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from process_cleanup_check import check_process_cleanup, is_port_open
from run_startup_shutdown_gate import start_service, stop_process
from run_stable_smoke import check_latest_frame, fetch_json, resolve_profile, run_config_validation, wait_for_json


ROOT = Path(__file__).resolve().parents[1]
STAGE = "S3_CAMERA_AND_VIDEO_STREAM_RESILIENCE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the S3 camera and video stream resilience gate.")
    parser.add_argument("--profile", default="safe_demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8013)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "stabilization" / STAGE)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir / run_id
    status_dir = output_dir / "status_snapshots"
    headers_dir = output_dir / "latest_frame_headers"
    tests_dir = output_dir / "test_results"
    logs_dir = output_dir / "logs"
    faults_dir = output_dir / "fault_scenarios"
    for directory in (status_dir, headers_dir, tests_dir, logs_dir, faults_dir):
        directory.mkdir(parents=True, exist_ok=True)

    (output_dir / "git_status_before.txt").write_text(run_git_status(), encoding="utf-8")

    profile_path = resolve_profile(args.profile)
    report: dict[str, Any] = {
        "status": "NOT_RUN",
        "stage": STAGE,
        "run_id": run_id,
        "profile": str(profile_path),
        "base_url": f"http://{args.host}:{args.port}",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": [],
        "gates": {
            "S3_CAMERA_STATE_CONTRACT_GATE": "NOT_RUN",
            "S3_FRAME_FRESHNESS_GATE": "NOT_RUN",
            "S3_NO_FRAME_SEMANTICS_GATE": "NOT_RUN",
            "S3_MOCK_STREAM_CONTINUITY_GATE": "NOT_RUN",
            "S3_MOCK_PAUSE_STALE_RECOVERY_GATE": "NOT_RUN",
            "S3_MOCK_FREEZE_DETECTION_GATE": "NOT_RUN",
            "S3_SOURCE_SWITCH_RESET_GATE": "NOT_RUN",
            "S3_NO_FRAME_BUSY_LOOP_GATE": "NOT_RUN",
            "S3_LATEST_FRAME_API_GATE": "NOT_RUN",
            "S3_RECONNECT_POLICY_GATE": "NOT_RUN",
            "REAL_RTSP_ACCEPTANCE": "NOT_RUN",
            "REAL_RTSP_RECONNECT_ACCEPTANCE": "NOT_RUN",
        },
        "not_in_scope": [
            "Robot Assist",
            "Go2 control",
            "Qwen/Ollama VLM advisory",
            "real event Delivery",
            "real main-system POST",
        ],
    }
    proc = None
    try:
        step(report, "validate_config", lambda: run_config_validation(profile_path, output_dir / "config_snapshot.json"))
        step(report, "pytest_s3_stabilization", lambda: run_pytest(tests_dir / "pytest_stabilization.txt"))
        report["gates"]["S3_CAMERA_STATE_CONTRACT_GATE"] = "PASS"
        report["gates"]["S3_FRAME_FRESHNESS_GATE"] = "PASS"
        report["gates"]["S3_NO_FRAME_BUSY_LOOP_GATE"] = "PASS"
        report["gates"]["S3_RECONNECT_POLICY_GATE"] = "PASS"

        if is_port_open(args.host, args.port):
            raise RuntimeError(f"port already in use: {args.host}:{args.port}")
        proc = start_service(profile_path, args.host, args.port, logs_dir / "uvicorn.log")
        step(report, "start_service", lambda: {"pid": proc.pid})
        base_url = f"http://{args.host}:{args.port}"
        step(report, "wait_healthz", lambda: wait_for_json(f"{base_url}/healthz", timeout_seconds=60))

        initial = wait_for_stream_state(base_url, "streaming", status_dir / "initial_streaming.json")
        initial_generation = first_camera(initial).get("source_generation")
        step(report, "wait_initial_streaming", lambda: {"source_generation": initial_generation})

        frame_headers = save_latest_frame(base_url, headers_dir / "fresh_headers.json", output_dir / "latest_frame_fresh.jpg")
        assert_header(frame_headers, "X-Frame-Status", {"fresh", "delayed"})
        assert_header(frame_headers, "X-Source-Generation", {str(initial_generation)})
        report["gates"]["S3_MOCK_STREAM_CONTINUITY_GATE"] = "PASS"
        report["gates"]["S3_LATEST_FRAME_API_GATE"] = "PASS"

        set_mock_fault(base_url, "pause", faults_dir / "pause.json")
        stale_status = wait_for_stream_state(base_url, "stale", status_dir / "pause_stale.json", timeout_seconds=8)
        latest_result = stale_status.get("latest_result") or {}
        if latest_result.get("safe_to_interpret_as_no_fall") is not False:
            raise RuntimeError("stale latest_result was not marked unsafe")
        report["gates"]["S3_NO_FRAME_SEMANTICS_GATE"] = "PASS"
        report["gates"]["S3_MOCK_PAUSE_STALE_RECOVERY_GATE"] = "PASS"

        stale_headers = save_latest_frame(base_url, headers_dir / "stale_headers.json", output_dir / "latest_frame_stale.jpg")
        assert_header(stale_headers, "X-Frame-Status", {"stale"})

        set_mock_fault(base_url, "resume", faults_dir / "resume_after_pause.json")
        wait_for_stream_state(base_url, "streaming", status_dir / "resume_streaming.json", timeout_seconds=8)

        set_mock_fault(base_url, "freeze", faults_dir / "freeze.json")
        freeze_status = wait_for_stream_state(base_url, "stale", status_dir / "freeze_stale.json", timeout_seconds=8)
        report["gates"]["S3_MOCK_FREEZE_DETECTION_GATE"] = "PASS"

        set_mock_fault(base_url, "resume", faults_dir / "resume_after_freeze.json")
        wait_for_stream_state(base_url, "streaming", status_dir / "resume_after_freeze_streaming.json", timeout_seconds=8)

        post_json(base_url + "/stream/stop", {"camera_id": "camera_01"}, faults_dir / "stop_source.json")
        no_frame_result = expect_latest_frame_404(base_url, headers_dir / "after_stop_no_frame.json")
        if no_frame_result.get("safe_to_interpret_as_no_fall") is not False:
            raise RuntimeError("no-frame response was not marked unsafe")

        post_json(base_url + "/stream/start", {"camera_id": "camera_01", "rtsp_url": "mock://colorbars"}, faults_dir / "restart_source.json")
        restarted = wait_for_stream_state(base_url, "streaming", status_dir / "restart_streaming.json", timeout_seconds=8)
        restarted_generation = first_camera(restarted).get("source_generation")
        if restarted_generation is None or initial_generation is None or int(restarted_generation) <= int(initial_generation):
            raise RuntimeError(f"source generation did not advance: {initial_generation} -> {restarted_generation}")
        report["gates"]["S3_SOURCE_SWITCH_RESET_GATE"] = "PASS"

        step(report, "stop_service", lambda: stop_process(proc))
        step(report, "process_cleanup_check", lambda: run_process_cleanup(proc.pid, args.host, args.port, output_dir / "process_cleanup.json"))

        report["status"] = "PASS" if all_core_gates_pass(report["gates"]) else "REVISE"
        return finish(report, output_dir, 0 if report["status"] == "PASS" else 1)
    except Exception as exc:
        report["status"] = "REVISE"
        report["fatal_error"] = str(exc)
        if proc is not None:
            try:
                stop_process(proc)
                cleanup = check_process_cleanup(pid=proc.pid, host=args.host, port=args.port, timeout_seconds=20)
                (output_dir / "process_cleanup.json").write_text(json.dumps(cleanup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception as cleanup_exc:
                report["cleanup_error"] = str(cleanup_exc)
        return finish(report, output_dir, 1)
    finally:
        (output_dir / "git_status_after.txt").write_text(run_git_status(), encoding="utf-8")


def step(report: dict[str, Any], name: str, fn) -> dict[str, Any]:
    started = time.perf_counter()
    item = {"name": name, "ok": False}
    try:
        item["result"] = fn()
        item["ok"] = True
    except Exception as exc:
        item["error"] = str(exc)
        report["steps"].append(item)
        raise
    finally:
        item["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["steps"].append(item)
    return item


def run_pytest(output_path: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "tests\\stabilization", "-q", "--maxfail=1"]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=120)
    output_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout or completed.stderr)
    return {"status": "PASS", "path": str(output_path.resolve())}


def wait_for_stream_state(base_url: str, expected: str, path: Path, *, timeout_seconds: float = 10) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = fetch_json(base_url + "/status")
        last_status = status
        cameras = status.get("cameras") or []
        if cameras and cameras[0].get("stream_state") == expected:
            path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return status
        time.sleep(0.25)
    path.write_text(json.dumps(last_status or {}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    raise RuntimeError(f"timeout waiting for stream_state={expected}")


def first_camera(status: dict[str, Any]) -> dict[str, Any]:
    cameras = status.get("cameras") or []
    if not cameras:
        raise RuntimeError("status has no cameras")
    return cameras[0]


def save_latest_frame(base_url: str, header_path: Path, image_path: Path) -> dict[str, str]:
    result = check_latest_frame(base_url + "/stream/latest-frame.jpg", image_path)
    headers = {
        "X-Camera-Id": result.get("headers", {}).get("X-Camera-Id", ""),
    }
    request = Request(base_url + "/stream/latest-frame.jpg", headers={"Accept": "image/jpeg"})
    with urlopen(request, timeout=10) as response:
        response.read()
        headers = dict(response.headers.items())
    header_path.write_text(json.dumps(headers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return headers


def set_mock_fault(base_url: str, mode: str, path: Path) -> dict[str, Any]:
    return post_json(base_url + "/stream/mock-fault", {"camera_id": "camera_01", "mode": mode}, path)


def post_json(url: str, payload: dict[str, Any], path: Path) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        body = response.read().decode("utf-8")
    result = json.loads(body) if body else {}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def expect_latest_frame_404(base_url: str, path: Path) -> dict[str, Any]:
    try:
        request = Request(base_url + "/stream/latest-frame.jpg", headers={"Accept": "image/jpeg"})
        with urlopen(request, timeout=10) as response:
            response.read()
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        path.write_text(json.dumps(detail, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if exc.code != 404:
            raise RuntimeError(f"expected 404, got {exc.code}")
        return detail
    raise RuntimeError("expected latest-frame 404 after stop")


def assert_header(headers: dict[str, str], name: str, allowed_values: set[str]) -> None:
    value = header_value(headers, name)
    if value not in allowed_values:
        raise RuntimeError(f"unexpected {name}: {value}, expected one of {sorted(allowed_values)}")


def header_value(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def all_core_gates_pass(gates: dict[str, str]) -> bool:
    required = [name for name in gates if name.startswith("S3_")]
    return all(gates.get(name) == "PASS" for name in required)


def run_process_cleanup(pid: int, host: str, port: int, path: Path) -> dict[str, Any]:
    cleanup = check_process_cleanup(pid=pid, host=host, port=port, timeout_seconds=20)
    path.write_text(json.dumps(cleanup, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if cleanup.get("status") != "PASS":
        raise RuntimeError("process cleanup failed")
    return cleanup


def run_git_status() -> str:
    completed = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, timeout=20)
    return completed.stdout


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
        "# S3 Camera And Video Stream Resilience",
        "",
        f"- Status: `{report['status']}`",
        f"- Profile: `{report['profile']}`",
        f"- Base URL: `{report['base_url']}`",
        "",
        "## Gates",
        "",
    ]
    lines.extend(f"- `{value}` {name}" for name, value in report["gates"].items())
    lines.extend(["", "## Steps", ""])
    for item in report.get("steps", []):
        marker = "PASS" if item.get("ok") else "REVISE"
        lines.append(f"- `{marker}` {item['name']} ({item.get('elapsed_seconds')}s)")
    if report.get("fatal_error"):
        lines.extend(["", "## Fatal Error", "", f"`{report['fatal_error']}`"])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
