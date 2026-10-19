from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import requests

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    psutil = None  # type: ignore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_ROOT = PROJECT_ROOT.parent / "event"
DEFAULT_CAMERA_API = "http://127.0.0.1:8000/api/v1"
DEFAULT_MAIN_API = "http://127.0.0.1:8090/api/v1"
DEFAULT_CAMERA_ID = "camera_01"
DEFAULT_STREAM_URL = "http://192.168.8.254:8093/stream.mjpg"
DEFAULT_SESSION_PREFIX = "e2e"


@dataclass
class CaseSpec:
    name: str
    duration_seconds: int
    binary_enabled: bool
    qwen_enabled: bool


@dataclass
class CaseResult:
    spec: CaseSpec
    started_at: str
    finished_at: str
    control_before: dict[str, Any]
    control_after: dict[str, Any]
    archive_status: dict[str, Any]
    session_dir: str | None
    copied_dir: str | None
    camera_artifacts: dict[str, str]
    main_system_event: dict[str, Any] | None
    resource_metrics: list[dict[str, Any]]
    notes: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real PFV2 system E2E test against live services.")
    parser.add_argument("--camera-base-url", default=DEFAULT_CAMERA_API)
    parser.add_argument("--main-base-url", default=DEFAULT_MAIN_API)
    parser.add_argument("--camera-id", default=DEFAULT_CAMERA_ID)
    parser.add_argument("--stream-url", default=DEFAULT_STREAM_URL)
    parser.add_argument("--baseline-seconds", type=int, default=60)
    parser.add_argument("--binary-seconds", type=int, default=60)
    parser.add_argument("--manual-wait", dest="manual_wait", action="store_true", help="Wait for a controlled fall after automatic phases.")
    parser.add_argument("--no-manual-wait", dest="manual_wait", action="store_false", help="Skip the controlled-fall pause.")
    parser.set_defaults(manual_wait=True)
    parser.add_argument("--output-root", default=str(EVENT_ROOT / "system_e2e_tests"))
    args = parser.parse_args()

    output_root = Path(args.output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    session_id = f"{DEFAULT_SESSION_PREFIX}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    session_dir = output_root / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    camera = ApiClient(args.camera_base_url, api_prefix="")
    discovered_main_base_url = discover_main_system_base_url(camera, args.main_base_url)
    main_system = ApiClient(discovered_main_base_url, api_prefix="/api/v1")

    manifest: dict[str, Any] = {
        "schema_version": "system_e2e_test_manifest.v1",
        "session_id": session_id,
        "created_at": utc_now_iso(),
        "camera_base_url": args.camera_base_url,
        "main_base_url": discovered_main_base_url,
        "camera_id": args.camera_id,
        "stream_url": args.stream_url,
        "cases": [],
    }

    write_json(session_dir / "SESSION_MANIFEST.json", manifest)
    write_text(
        session_dir / "README.md",
        "# SYSTEM E2E TEST\n\nThis directory contains the live system test artifacts.\n",
    )

    preflight = collect_preflight(camera, main_system, args.camera_id)
    write_json(session_dir / "preflight.json", preflight)

    ensure_stream_started(camera, args.camera_id, args.stream_url)
    camera.set_binary(args.camera_id, False)
    camera.set_qwen(args.camera_id, False)

    cases = [
        CaseSpec("VIDEO_BASELINE", args.baseline_seconds, binary_enabled=False, qwen_enabled=False),
        CaseSpec("BINARY_RUNTIME", args.binary_seconds, binary_enabled=True, qwen_enabled=False),
    ]

    results: list[CaseResult] = []
    for spec in cases:
        result = run_case(
            camera=camera,
            main_system=main_system,
            session_dir=session_dir,
            camera_id=args.camera_id,
            spec=spec,
            stream_url=args.stream_url,
        )
        results.append(result)
        manifest["cases"].append(
            {
                "name": spec.name,
                "duration_seconds": spec.duration_seconds,
                "binary_enabled": spec.binary_enabled,
                "qwen_enabled": spec.qwen_enabled,
                "session_dir": result.session_dir,
                "copied_dir": result.copied_dir,
            }
        )
        write_json(session_dir / "SESSION_MANIFEST.json", manifest)

    if args.manual_wait:
        print("\nREADY FOR CONTROLLED FALL\n", flush=True)
        print("3", flush=True)
        time.sleep(1)
        print("2", flush=True)
        time.sleep(1)
        print("1", flush=True)
        time.sleep(1)
        print("BEEP", flush=True)
        input("Press Enter after the controlled fall has been performed and the real alert has propagated...")

    summary = build_summary(session_id, preflight, results)
    write_json(session_dir / "SUMMARY.json", summary)
    write_csv(session_dir / "RESOURCE_METRICS.csv", flatten_resource_metrics(results))
    write_csv(session_dir / "CASE_METRICS.csv", flatten_case_metrics(results))
    write_text(session_dir / "TEST_REPORT.md", build_report(summary, results))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def run_case(
    *,
    camera: "ApiClient",
    main_system: "ApiClient",
    session_dir: Path,
    camera_id: str,
    spec: CaseSpec,
    stream_url: str,
) -> CaseResult:
    case_dir = session_dir / spec.name.lower()
    case_dir.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    if not camera.stream_ready(camera_id):
        ensure_stream_started(camera, camera_id, stream_url)
        if not wait_for_stream_ready(camera, camera_id):
            notes.append("camera stream did not become ready before the case started; model toggles may be skipped.")

    try:
        camera.set_binary(camera_id, spec.binary_enabled)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            notes.append(f"binary toggle skipped: {exc.response.text.strip() or '409 conflict'}")
        else:
            raise
    try:
        camera.set_qwen(camera_id, spec.qwen_enabled)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 409:
            notes.append(f"qwen toggle skipped: {exc.response.text.strip() or '409 conflict'}")
        else:
            raise

    before = camera.get_control_status(camera_id)
    archive_status = camera.start_test(spec.duration_seconds)
    started_at = utc_now_iso()
    resource_metrics: list[dict[str, Any]] = []

    if not camera.stream_ready(camera_id):
        ensure_stream_started(camera, camera_id, stream_url)

    end_deadline = time.monotonic() + max(1, spec.duration_seconds)
    while time.monotonic() < end_deadline:
        resource_metrics.append(sample_resources())
        time.sleep(1.0)

    camera.stop_test()
    after = camera.get_control_status(camera_id)
    archive_status = camera.get_control_status(camera_id).get("test") or archive_status
    session_path = Path(archive_status["session_dir"]) if isinstance(archive_status, dict) and archive_status.get("session_dir") else None
    copied_dir = None
    if session_path and session_path.exists():
        copied_dir = str(case_dir / "camera_session")
        if Path(copied_dir).exists():
            shutil.rmtree(copied_dir)
        shutil.copytree(session_path, copied_dir)

    main_event = poll_main_system_event(main_system, camera_id)
    camera_artifacts = collect_case_artifacts(session_path)
    write_json(case_dir / "case_result.json", {
        "spec": spec.__dict__,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "control_before": before,
        "control_after": after,
        "archive_status": archive_status,
        "main_system_event": main_event,
        "camera_artifacts": camera_artifacts,
    })

    if spec.name == "BINARY_RUNTIME" and not spec.qwen_enabled:
        notes.append("qwen intentionally disabled for the binary runtime baseline.")

    return CaseResult(
        spec=spec,
        started_at=started_at,
        finished_at=utc_now_iso(),
        control_before=before,
        control_after=after,
        archive_status=archive_status if isinstance(archive_status, dict) else {},
        session_dir=str(session_path) if session_path else None,
        copied_dir=copied_dir,
        camera_artifacts=camera_artifacts,
        main_system_event=main_event,
        resource_metrics=resource_metrics,
        notes=notes,
    )


def ensure_stream_started(camera: "ApiClient", camera_id: str, stream_url: str) -> None:
    source = camera.get_stream_source(camera_id)
    if source.get("running"):
        return
    camera.start_stream(camera_id=camera_id, source_url=stream_url)


def wait_for_stream_ready(camera: "ApiClient", camera_id: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + max(1.0, timeout_seconds)
    while time.monotonic() < deadline:
        if camera.stream_ready(camera_id):
            return True
        time.sleep(0.5)
    return camera.stream_ready(camera_id)


def collect_preflight(camera: "ApiClient", main_system: "ApiClient", camera_id: str) -> dict[str, Any]:
    preflight: dict[str, Any] = {
        "created_at": utc_now_iso(),
        "camera_status": camera.get_control_status(camera_id),
        "stream_source": camera.get_stream_source(camera_id),
        "camera_health": safe_call(camera.get_healthz),
        "main_health": safe_call(main_system.get_healthz),
        "camera_system_info": safe_get(camera, "/system/info"),
        "main_system_info": safe_get(main_system, "/system/info"),
        "ollama": probe_ollama(),
        "binary_model": probe_binary_model(),
    }
    return preflight


def discover_main_system_base_url(camera: "ApiClient", fallback_base_url: str) -> str:
    try:
        payload = camera.get_json("/integration/connection-status")
        main_system = payload.get("main_system") if isinstance(payload, dict) else None
        if isinstance(main_system, dict):
            base_url = str(main_system.get("base_url") or "").strip()
            if base_url:
                return base_url.removesuffix("/api/v1").rstrip("/")
    except Exception:
        pass
    return fallback_base_url.rstrip("/")


def build_summary(session_id: str, preflight: dict[str, Any], results: list[CaseResult]) -> dict[str, Any]:
    return {
        "schema_version": "system_e2e_test_summary.v1",
        "session_id": session_id,
        "created_at": utc_now_iso(),
        "preflight": preflight,
        "cases": [
            {
                "name": result.spec.name,
                "duration_seconds": result.spec.duration_seconds,
                "binary_enabled": result.spec.binary_enabled,
                "qwen_enabled": result.spec.qwen_enabled,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "session_dir": result.session_dir,
                "copied_dir": result.copied_dir,
                "camera_artifacts": result.camera_artifacts,
                "main_system_event": result.main_system_event,
                "notes": result.notes,
            }
            for result in results
        ],
    }


def build_report(summary: dict[str, Any], results: list[CaseResult]) -> str:
    lines = [
        "# SYSTEM E2E TEST REPORT",
        "",
        f"- session_id: `{summary['session_id']}`",
        f"- created_at: `{summary['created_at']}`",
        "",
        "## Cases",
    ]
    for result in results:
        lines.extend(
            [
                f"### {result.spec.name}",
                f"- binary_enabled: `{result.spec.binary_enabled}`",
                f"- qwen_enabled: `{result.spec.qwen_enabled}`",
                f"- started_at: `{result.started_at}`",
                f"- finished_at: `{result.finished_at}`",
                f"- session_dir: `{result.session_dir}`",
                f"- copied_dir: `{result.copied_dir}`",
                f"- notes: `{'; '.join(result.notes) or 'none'}`",
            ]
        )
        if result.main_system_event:
            lines.append(f"- main_system_event: `{json.dumps(result.main_system_event, ensure_ascii=False)}`")
    lines.extend(["", "## Preflight", f"`{json.dumps(summary['preflight'], ensure_ascii=False)}`"])
    return "\n".join(lines) + "\n"


def flatten_resource_metrics(results: list[CaseResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for sample in result.resource_metrics:
            row = {"case": result.spec.name, **sample}
            rows.append(row)
    return rows


def flatten_case_metrics(results: list[CaseResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        row = {
            "case": result.spec.name,
            "duration_seconds": result.spec.duration_seconds,
            "binary_enabled": result.spec.binary_enabled,
            "qwen_enabled": result.spec.qwen_enabled,
            "session_dir": result.session_dir,
            "copied_dir": result.copied_dir,
            "main_system_event": json.dumps(result.main_system_event, ensure_ascii=False) if result.main_system_event else "",
        }
        rows.append(row)
    return rows


def collect_case_artifacts(session_path: Path | None) -> dict[str, str]:
    if session_path is None or not session_path.exists():
        return {}
    names = ["SESSION_MANIFEST.json", "TRACE_TIMELINE.jsonl", "SUMMARY.json", "TEST_REPORT.md", "session_summary.json", "events.json", "binary_predictions.csv", "performance.csv"]
    artifacts: dict[str, str] = {}
    for name in names:
        path = session_path / name
        if path.exists():
            artifacts[name] = str(path)
    return artifacts


def poll_main_system_event(main_system: "ApiClient", camera_id: str, timeout_seconds: float = 1.0) -> dict[str, Any] | None:
    try:
        latest = main_system.get_json("/video-bridge/fall-events/latest?limit=1", timeout=timeout_seconds)
    except Exception:
        return None
    items = latest.get("items") if isinstance(latest, dict) else None
    if not isinstance(items, list) or not items:
        return None
    event = items[0]
    if not isinstance(event, dict):
        return None
    if str(event.get("camera_id") or "") != camera_id:
        return None
    return event


def safe_get(client: "ApiClient", path: str) -> dict[str, Any]:
    try:
        payload = client.get_json(path)
        return payload if isinstance(payload, dict) else {"value": payload}
    except Exception as exc:
        return {"error": str(exc)}


def safe_call(fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": str(exc)}


def probe_ollama() -> dict[str, Any]:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        return {
            "ok": True,
            "endpoint": "http://127.0.0.1:11434",
            "models": [item.get("name") for item in models if isinstance(item, dict)],
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def probe_binary_model() -> dict[str, Any]:
    model_path = PROJECT_ROOT / "models" / "post_fall_v2" / "efficientnet_b0" / "fall_candidate_efficientnet_b0.onnx"
    info: dict[str, Any] = {
        "path": str(model_path),
        "exists": model_path.exists(),
    }
    try:
        import onnxruntime as ort

        info["available_providers"] = list(ort.get_available_providers())
        if model_path.exists():
            session = ort.InferenceSession(str(model_path), providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
            info["active_providers"] = list(session.get_providers())
    except Exception as exc:
        info["error"] = str(exc)
    return info


def sample_resources() -> dict[str, Any]:
    sample: dict[str, Any] = {
        "timestamp": utc_now_iso(),
        "system_cpu_percent": None,
        "system_memory_percent": None,
        "system_memory_used_mb": None,
        "camera_service_cpu_percent": None,
        "camera_service_rss_mb": None,
        "main_system_cpu_percent": None,
        "main_system_rss_mb": None,
        "gpu_util_percent": None,
        "gpu_memory_used_mb": None,
        "gpu_memory_total_mb": None,
        "gpu_memory_percent": None,
    }
    if psutil is not None:
        try:
            sample["system_cpu_percent"] = round(float(psutil.cpu_percent(interval=None)), 2)
            memory = psutil.virtual_memory()
            sample["system_memory_percent"] = round(float(memory.percent), 2)
            sample["system_memory_used_mb"] = round(float(memory.used) / (1024 * 1024), 2)
        except Exception:
            pass
        for port, prefix in ((8000, "camera_service"), (8090, "main_system")):
            proc = process_listening_on_port(port)
            if proc is None:
                continue
            try:
                sample[f"{prefix}_cpu_percent"] = round(float(proc.cpu_percent(interval=None)), 2)
                sample[f"{prefix}_rss_mb"] = round(float(proc.memory_info().rss) / (1024 * 1024), 2)
            except Exception:
                pass
    sample.update(sample_gpu())
    return sample


def process_listening_on_port(port: int):
    if psutil is None:
        return None
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status != psutil.CONN_LISTEN:
                continue
            if not conn.laddr or conn.laddr.port != port:
                continue
            if conn.pid is None:
                continue
            try:
                proc = psutil.Process(conn.pid)
                proc.cpu_percent(interval=None)
                return proc
            except Exception:
                return None
    except Exception:
        return None
    return None


def sample_gpu() -> dict[str, Any]:
    fallback = {
        "gpu_util_percent": None,
        "gpu_memory_used_mb": None,
        "gpu_memory_total_mb": None,
        "gpu_memory_percent": None,
    }
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=0.75,
            check=False,
        )
    except Exception:
        return fallback
    if completed.returncode != 0:
        return fallback
    first_line = next((line.strip() for line in completed.stdout.splitlines() if line.strip()), "")
    parts = [part.strip() for part in first_line.split(",")]
    if len(parts) < 3:
        return fallback
    try:
        used = float(parts[1])
        total = float(parts[2])
        return {
            "gpu_util_percent": float(parts[0]),
            "gpu_memory_used_mb": used,
            "gpu_memory_total_mb": total,
            "gpu_memory_percent": round(used / total * 100, 2) if total > 0 else None,
        }
    except ValueError:
        return fallback


class ApiClient:
    def __init__(self, base_url: str, api_prefix: str | None = None) -> None:
        normalized = base_url.rstrip("/")
        self.root_url = normalized.removesuffix("/api/v1")
        self.api_prefix = api_prefix if api_prefix is not None else detect_api_prefix(self.root_url)
        self.api_base = f"{self.root_url}{self.api_prefix}"
        self.session = requests.Session()

    def get_healthz(self) -> dict[str, Any]:
        return self.get_json("/healthz", api=False)

    def get_json(self, path: str, timeout: float = 10.0, *, api: bool = True) -> dict[str, Any]:
        response = self.session.get(self._url(path, api=api), timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"value": payload}

    def post_json(self, path: str, payload: dict[str, Any] | None = None, timeout: float = 10.0, *, api: bool = True) -> dict[str, Any]:
        response = self.session.post(self._url(path, api=api), json=payload or {}, timeout=timeout)
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {"value": body}

    def start_stream(self, *, camera_id: str, source_url: str) -> dict[str, Any]:
        return self.post_json("/stream/start", {"camera_id": camera_id, "source_url": source_url})

    def get_stream_source(self, camera_id: str) -> dict[str, Any]:
        return self.get_json(f"/stream/source?camera_id={camera_id}")

    def stream_ready(self, camera_id: str) -> bool:
        try:
            payload = self.get_stream_source(camera_id)
        except Exception:
            return False
        return bool(payload.get("running"))

    def get_control_status(self, camera_id: str) -> dict[str, Any]:
        return self.get_json(f"/runtime-control/status?camera_id={camera_id}")

    def set_binary(self, camera_id: str, enabled: bool) -> dict[str, Any]:
        return self.post_json("/runtime-control/binary", {"camera_id": camera_id, "enabled": enabled})

    def set_qwen(self, camera_id: str, enabled: bool) -> dict[str, Any]:
        return self.post_json("/runtime-control/qwen", {"camera_id": camera_id, "enabled": enabled})

    def start_test(self, seconds: int) -> dict[str, Any]:
        hours, minutes, secs = normalize_duration_seconds(seconds)
        return self.post_json("/runtime-control/test/start", {"hours": hours, "minutes": minutes, "seconds": secs})

    def stop_test(self) -> dict[str, Any]:
        return self.post_json("/runtime-control/test/stop", {})

    def _url(self, path: str, *, api: bool = True) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = f"/{path}"
        base = self.api_base if api else self.root_url
        return f"{base}{path}"


def detect_api_prefix(base_url: str) -> str:
    for prefix in ("/api/v1", ""):
        try:
            response = requests.get(f"{base_url.rstrip('/')}{prefix}/healthz", timeout=1.5)
            if response.status_code < 500:
                return prefix
        except Exception:
            continue
    return ""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def normalize_duration_seconds(total_seconds: int) -> tuple[int, int, int]:
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return hours, minutes, seconds


if __name__ == "__main__":
    raise SystemExit(main())
