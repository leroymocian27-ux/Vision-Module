from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_event_visual_qa" / "formal_demo_execution_20260718"
LIVE_BASE = "http://127.0.0.1:8000"
DEMO_PORT = 8011
DEMO_BASE = f"http://127.0.0.1:{DEMO_PORT}"
CANDIDATE_ID = "demo-rehearsal-20260718-candidate"
CONFIRMED_ID = "demo-rehearsal-20260718-confirmed-synthetic"
CHROME_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P1 loopback-only synthetic formal-demo acceptance.")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep isolated JSON summaries and screenshots after a successful run.")
    parser.add_argument("--port", type=int, default=8011, help="Temporary loopback demo port; default 8011.")
    args = parser.parse_args()

    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port must be between 1024 and 65535")
    global DEMO_PORT, DEMO_BASE
    DEMO_PORT = args.port
    DEMO_BASE = f"http://127.0.0.1:{DEMO_PORT}"

    OUT.mkdir(parents=True, exist_ok=True)
    env_file = ROOT / ".env"
    env_before = _hash_file(env_file)
    result: dict[str, Any] = {
        "scope": "P1_formal_demo_synthetic_only",
        "result": "REVISE",
        "actual_env_modified": False,
        "real_main_system_post": False,
        "event_vlm_enabled": False,
        "ollama_called": False,
        "production_ready": False,
        "live_instance": {},
        "demo_instance": {},
        "browser": {},
        "artifacts": [],
    }
    result["demo_instance"]["port"] = DEMO_PORT

    _require_port_free(DEMO_PORT)
    result["live_instance"]["before"] = _safe_live_summary()
    process: subprocess.Popen[bytes] | None = None
    stage = "start_demo_service"
    try:
        process = _start_demo_service()
        stage = "wait_demo_health"
        _wait_for_health(DEMO_BASE)
        result["demo_instance"]["status"] = _safe_event_status(DEMO_BASE)
        stage = "seed_candidate"
        _seed(CANDIDATE_ID, "fall_candidate_support", clear_demo=True)
        stage = "seed_confirmed_synthetic"
        _seed(CONFIRMED_ID, "fallen_confirmed_high", clear_demo=False)

        stage = "collect_api"
        api_candidate = _collect_api(CANDIDATE_ID)
        api_confirmed = _collect_api(CONFIRMED_ID)
        api_path = OUT / "p1_api_summary.json"
        api_path.write_text(json.dumps({"candidate": api_candidate, "confirmed_synthetic": api_confirmed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["demo_instance"]["candidate"] = _compact_api_result(api_candidate)
        result["demo_instance"]["confirmed_synthetic"] = _compact_api_result(api_confirmed)
        result["artifacts"].append(_relative(api_path))

        stage = "collect_browser"
        browser_result = _collect_browser_evidence()
        browser_path = OUT / "p1_browser_summary.json"
        browser_path.write_text(json.dumps(browser_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result["browser"] = browser_result
        result["artifacts"].append(_relative(browser_path))
        result["artifacts"].extend(browser_result.get("screenshot_paths", []))
    except Exception as exc:
        result["failure_stage"] = stage
        result["failure"] = _safe_error(exc)
    finally:
        if process is not None:
            _stop_process(process)
        result["demo_instance"]["listener_after_stop"] = _port_is_listening(DEMO_PORT)
        result["live_instance"]["after"] = _safe_live_summary()
        result["actual_env_modified"] = _hash_file(env_file) != env_before

    result["result"] = "PASS" if _is_pass(result) else "REVISE"
    summary_path = OUT / "p1_execution_summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["artifacts"].append(_relative(summary_path))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["result"] == "PASS" else 1


def _demo_environment() -> dict[str, str]:
    return {
        "VISION_SERVICE_RUNTIME_PROFILE": "formal_demo_synthetic",
        "MOCK_CAMERA_ENABLED": "true",
        "DEFAULT_RTSP_URL": "",
        "MAIN_STREAM_URL": "",
        "ANALYSIS_STREAM_URL": "",
        "DEVICE_DISCOVERY_ENABLED": "false",
        "ENABLE_POSE": "false",
        "DETECTION_ENABLED": "false",
        "FALL_DETECTOR_ENABLED": "false",
        "MAIN_SYSTEM_ALERT_ENABLED": "false",
        "MAIN_SYSTEM_ALERT_TOKEN": "",
        "MAIN_SYSTEM_ALERT_TOKEN_HEADER": "",
        "EVENT_PIPELINE_ENABLED": "true",
        "EVENT_RING_BUFFER_ENABLED": "true",
        "EVENT_WORKER_ENABLED": "true",
        "EVENT_SEMANTIC_ENABLED": "true",
        "EVENT_ARCHIVE_ENABLED": "true",
        "EVENT_ARCHIVE_DIR": str(OUT / "archive"),
        "EVENT_KEYFRAME_SERVING_ENABLED": "true",
        "EVENT_POST_KEYFRAME_COLLECTION_ENABLED": "false",
        "EVENT_OUTBOX_BACKEND": "sqlite",
        "EVENT_OUTBOX_SQLITE_PATH": str(OUT / "event_outbox.sqlite3"),
        "EVENT_DELIVERY_ENABLED": "true",
        "EVENT_DELIVERY_MODE": "dry_run",
        "EVENT_DELIVERY_BACKEND": "sqlite",
        "EVENT_DELIVERY_SQLITE_PATH": str(OUT / "delivery_outbox.sqlite3"),
        "EVENT_DELIVERY_WORKER_ENABLED": "false",
        "EVENT_DELIVERY_TARGET_URL": "",
        "EVENT_DELIVERY_ENDPOINT": "",
        "EVENT_VLM_ENABLED": "false",
        "EVENT_VLM_PROVIDER": "dummy",
        "PYTHONUTF8": "1",
    }


def _start_demo_service() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.update(_demo_environment())
    stdout = (OUT / f"p1_{DEMO_PORT}.stdout.log").open("wb")
    stderr = (OUT / f"p1_{DEMO_PORT}.stderr.log").open("wb")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(DEMO_PORT)],
        cwd=ROOT,
        env=env,
        stdout=stdout,
        stderr=stderr,
    )


def _seed(incident_id: str, scenario: str, *, clear_demo: bool) -> None:
    command = [
        sys.executable,
        "scripts/seed_event_pipeline_demo.py",
        "--incident-id",
        incident_id,
        "--camera-id",
        "camera_01",
        "--scenario",
        scenario,
        "--db",
        str(OUT / "event_outbox.sqlite3"),
        "--archive-dir",
        str(OUT / "archive"),
        "--delivery-db",
        str(OUT / "delivery_outbox.sqlite3"),
        "--seed-delivery-dry-run",
    ]
    if clear_demo:
        command.append("--clear-demo")
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _collect_api(incident_id: str) -> dict[str, Any]:
    from capture_formal_demo_evidence import evaluate

    return evaluate(live_url=LIVE_BASE, demo_url=DEMO_BASE, incident_id=incident_id)


def _compact_api_result(report: dict[str, Any]) -> dict[str, Any]:
    checks = {item["name"]: item["result"] for item in report.get("checks", [])}
    return {"ok": report.get("ok") is True, "keyframe_count": report.get("keyframe_count"), "checks": checks}


def _collect_browser_evidence() -> dict[str, Any]:
    chrome = next((path for path in CHROME_CANDIDATES if path.exists()), None)
    if chrome is None:
        raise RuntimeError("No supported local browser executable is available for P1 visual acceptance")
    import websocket

    debug_port = 9231
    _require_port_free(debug_port)
    profile = Path(tempfile.mkdtemp(prefix="vision-p1-browser-"))
    browser = subprocess.Popen(
        [str(chrome), "--headless=new", f"--remote-debugging-port={debug_port}", "--remote-allow-origins=*", f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu", "--window-size=1366,900", "about:blank"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    page = None
    try:
        _wait_for_debug_port(debug_port)
        page = _CdpPage(_new_page(debug_port, websocket))
        live = page.inspect_live()
        candidate = page.inspect_demo_event(CANDIDATE_ID, "p1_candidate_1366.png")
        confirmed = page.inspect_demo_event(CONFIRMED_ID, "p1_confirmed_synthetic_1366.png")
        return {
            "live": live,
            "candidate": candidate,
            "confirmed_synthetic": confirmed,
            "screenshot_paths": [_relative(OUT / "p1_live_8000.png"), _relative(OUT / "p1_candidate_1366.png"), _relative(OUT / "p1_confirmed_synthetic_1366.png")],
        }
    finally:
        if page is not None:
            page.close()
        _stop_process(browser)
        shutil.rmtree(profile, ignore_errors=True)


class _CdpPage:
    def __init__(self, ws: Any):
        self.ws = ws
        self.next_id = 0
        self.console_count = 0
        for method in ("Page.enable", "Runtime.enable", "Log.enable"):
            self.call(method)

    def close(self) -> None:
        self.ws.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        request_id = self.next_id
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except Exception as exc:
                if type(exc).__name__ == "WebSocketTimeoutException":
                    continue
                raise
            self._observe(message)
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"browser CDP {method} failed")
                return message.get("result") or {}
        raise TimeoutError(f"browser CDP {method} timed out")

    def _observe(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Runtime.consoleAPICalled" and params.get("type") in {"warning", "error", "assert"}:
            self.console_count += 1
        if method == "Log.entryAdded" and (params.get("entry") or {}).get("level") in {"warning", "error"}:
            self.console_count += 1

    def navigate(self, url: str) -> None:
        self.console_count = 0
        self.call("Page.navigate", {"url": url})
        time.sleep(4)

    def evaluate(self, expression: str) -> Any:
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        return (result.get("result") or {}).get("value")

    def screenshot(self, filename: str) -> None:
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})
        (OUT / filename).write_bytes(base64.b64decode(result["data"]))

    def inspect_live(self) -> dict[str, Any]:
        self.navigate(f"{LIVE_BASE}/demo/?v=p1-live&rawJson=0")
        state = self.evaluate(_connection_expression())
        self.screenshot("p1_live_8000.png")
        return {"state": state, "console_warn_error_count": self.console_count}

    def inspect_demo_event(self, incident_id: str, filename: str) -> dict[str, Any]:
        self.navigate(f"{DEMO_BASE}/demo/?v=p1-{incident_id}&rawJson=0")
        self.evaluate(_connection_expression())
        selected = self.evaluate(_select_event_expression(incident_id))
        state = self.evaluate(_event_expression(incident_id))
        self.screenshot(filename)
        return {"selected": selected, "state": state, "console_warn_error_count": self.console_count}


def _new_page(port: int, websocket_module: Any) -> Any:
    request = Request(f"http://127.0.0.1:{port}/json/new", method="PUT")
    with urlopen(request, timeout=5) as response:
        target = json.loads(response.read().decode("utf-8"))
    return websocket_module.create_connection(target["webSocketDebuggerUrl"], timeout=10)


def _connection_expression() -> str:
    return """(async () => {
      const connect = document.getElementById('connectBtn');
      if (connect && !connect.disabled) connect.click();
      for (let i = 0; i < 20; i++) {
        const webrtc = document.getElementById('webrtcState')?.textContent?.trim();
        const ws = document.getElementById('wsState')?.textContent?.trim();
        if (webrtc === 'connected' && ws === 'connected') break;
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      const video = document.getElementById('video');
      return {webrtc: document.getElementById('webrtcState')?.textContent?.trim(), ws: document.getElementById('wsState')?.textContent?.trim(), video_ready_state: video?.readyState ?? null, video_width: video?.videoWidth ?? null, video_height: video?.videoHeight ?? null, overlay: !!document.getElementById('overlay')};
    })()"""


def _select_event_expression(incident_id: str) -> str:
    encoded = json.dumps(incident_id)
    return f"""(async () => {{
      const wanted = {encoded};
      const shortId = wanted.length > 18 ? `${{wanted.slice(0, 8)}}...${{wanted.slice(-6)}}` : wanted;
      for (let i = 0; i < 20; i++) {{
        const item = Array.from(document.querySelectorAll('#eventRecentList .event-recent-item')).find(node => node.querySelector('strong')?.textContent?.trim() === shortId);
        if (item) {{ item.click(); break; }}
        await new Promise(resolve => setTimeout(resolve, 500));
      }}
      for (let i = 0; i < 20; i++) {{
        if (document.getElementById('eventIncidentId')?.textContent?.trim() === wanted) return true;
        await new Promise(resolve => setTimeout(resolve, 500));
      }}
      return false;
    }})()"""


def _event_expression(incident_id: str) -> str:
    encoded = json.dumps(incident_id)
    return f"""(async () => {{
      const wanted = {encoded};
      document.getElementById('eventTimeline')?.scrollIntoView({{block: 'center', behavior: 'instant'}});
      await new Promise(resolve => setTimeout(resolve, 250));
      for (let i = 0; i < 20; i++) {{
        const pending = Array.from(document.querySelectorAll('#eventTimeline img'));
        if (pending.length === 6 && pending.every(image => image.complete && image.naturalWidth > 0)) break;
        await new Promise(resolve => setTimeout(resolve, 250));
      }}
      const images = Array.from(document.querySelectorAll('#eventTimeline img'));
      const imageOk = images.filter(image => image.complete && image.naturalWidth > 0).length;
      const text = document.body.innerText || '';
      const leak = /(?:source_url|rtsp:\/\/|payload_json|lock_token|[A-Za-z]:[\\\\/]|logs[\\\\/]event_archive)/i.test(text);
      return {{ selected_incident: document.getElementById('eventIncidentId')?.textContent?.trim(), expected_incident: wanted, webrtc: document.getElementById('webrtcState')?.textContent?.trim(), ws: document.getElementById('wsState')?.textContent?.trim(), delivery: document.getElementById('eventDeliveryStatus')?.textContent?.trim(), vlm: document.getElementById('eventVlmStatus')?.textContent?.trim(), keyframe_cards: document.querySelectorAll('#eventTimeline .event-keyframe').length, keyframe_images: images.length, keyframe_images_loaded: imageOk, sensitive_text_leak: leak }};
    }})()"""


def _safe_live_summary() -> dict[str, Any]:
    health = _json_get(f"{LIVE_BASE}/healthz")
    events = _json_get(f"{LIVE_BASE}/events/status")
    return {"health_ok": health[0] == 200 and health[1].get("status") == "ok", "event_pipeline_enabled": events[1].get("event_pipeline_enabled"), "vlm_enabled": events[1].get("vlm_enabled")}


def _safe_event_status(base_url: str) -> dict[str, Any]:
    status, payload = _json_get(f"{base_url}/events/status")
    return {"http_status": status, "event_pipeline_enabled": payload.get("event_pipeline_enabled"), "worker_enabled": payload.get("worker_enabled"), "semantic_enabled": payload.get("semantic_enabled"), "vlm_enabled": payload.get("vlm_enabled")}


def _json_get(url: str) -> tuple[int, dict[str, Any]]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - constants are fixed local loopback URLs.
        body = json.loads(response.read().decode("utf-8"))
        return int(response.status), body if isinstance(body, dict) else {}


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            status, payload = _json_get(f"{base_url}/healthz")
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("temporary demo service did not become healthy")


def _wait_for_debug_port(port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("local browser debugger did not become ready")


def _require_port_free(port: int) -> None:
    if _port_is_listening(port):
        raise RuntimeError(f"port {port} is already in use")


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _hash_file(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _safe_error(error: Exception) -> str:
    return type(error).__name__


def _is_pass(result: dict[str, Any]) -> bool:
    if result.get("failure") or result.get("actual_env_modified") or result.get("demo_instance", {}).get("listener_after_stop"):
        return False
    live = result.get("live_instance", {})
    if not all(summary.get("health_ok") and summary.get("event_pipeline_enabled") is False and summary.get("vlm_enabled") is False for summary in (live.get("before", {}), live.get("after", {}))):
        return False
    demo = result.get("demo_instance", {})
    status = demo.get("status", {})
    if not (status.get("event_pipeline_enabled") is True and status.get("vlm_enabled") is False):
        return False
    for name in ("candidate", "confirmed_synthetic"):
        if not demo.get(name, {}).get("ok") or demo[name].get("keyframe_count") != 6:
            return False
    browser = result.get("browser", {})
    live_browser = browser.get("live", {})
    if live_browser.get("console_warn_error_count") != 0 or live_browser.get("state", {}).get("webrtc") != "connected" or live_browser.get("state", {}).get("ws") != "connected":
        return False
    for name, expected in (("candidate", CANDIDATE_ID), ("confirmed_synthetic", CONFIRMED_ID)):
        item = browser.get(name, {})
        state = item.get("state", {})
        if not item.get("selected") or state.get("selected_incident") != expected or state.get("keyframe_images_loaded") != 6 or state.get("sensitive_text_leak") is not False or item.get("console_warn_error_count") != 0:
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
