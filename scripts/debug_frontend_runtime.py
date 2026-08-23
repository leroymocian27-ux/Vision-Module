from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

import requests
import websockets


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "runtime_debug"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser-side runtime diagnostics for /demo.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/demo?v=runtime-debug-auto&rawJson=1")
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument(
        "--modes",
        default="full,off,bbox,bbox-skeleton,full-no-json",
        help="Comma-separated overlay modes.",
    )
    args = parser.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(tempfile.mkdtemp(prefix="vision_edge_debug_"))
    browser = None
    try:
        browser = start_edge(args.url, args.port, profile_dir)
        ws_url = wait_for_debugger(args.port)
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            cdp = CdpClient(ws)
            await cdp.call("Runtime.enable")
            await cdp.call("Page.enable")
            await asyncio.sleep(3)
            await ensure_connected(cdp)
            results = []
            for raw_mode in [item.strip() for item in args.modes.split(",") if item.strip()]:
                raw_json = not raw_mode.endswith("-no-json")
                mode = raw_mode.replace("-no-json", "")
                result = await run_mode(cdp, mode=mode, raw_json=raw_json, duration=args.duration)
                results.append(result)
                print(json.dumps(result, ensure_ascii=False, indent=2))

            output = {
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "url": args.url,
                "duration_seconds": args.duration,
                "results": results,
            }
            (LOG_DIR / "frontend_runtime_debug.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    finally:
        if browser and browser.poll() is None:
            browser.terminate()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)
    return 0


def start_edge(url: str, port: int, profile_dir: Path) -> subprocess.Popen:
    if not EDGE_PATH.exists():
        raise RuntimeError(f"Edge not found: {EDGE_PATH}")
    return subprocess.Popen(
        [
            str(EDGE_PATH),
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--autoplay-policy=no-user-gesture-required",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_debugger(port: int, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                tabs = json.loads(response.read().decode("utf-8"))
            for tab in tabs:
                if tab.get("type") == "page" and "demo" in tab.get("url", ""):
                    return tab["webSocketDebuggerUrl"]
            if tabs:
                return tabs[0]["webSocketDebuggerUrl"]
        except Exception as exc:  # pragma: no cover - diagnostic script.
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Could not connect to Edge debugger: {last_error}")


class CdpClient:
    def __init__(self, ws: websockets.WebSocketClientProtocol) -> None:
        self.ws = ws
        self._next_id = 1

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        msg_id = self._next_id
        self._next_id += 1
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(await self.ws.recv())
            if message.get("id") == msg_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result")


async def eval_js(cdp: CdpClient, expression: str, await_promise: bool = True) -> Any:
    result = await cdp.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        },
    )
    remote = result.get("result", {})
    if "value" in remote:
        return remote["value"]
    if "description" in remote:
        return remote["description"]
    return None


async def ensure_connected(cdp: CdpClient) -> None:
    await eval_js(
        cdp,
        """
        (async () => {
          if (!window.__VISION_DEBUG__) return {ok:false, reason:'debug missing'};
          const webrtc = document.getElementById('webrtcState')?.textContent;
          const ws = document.getElementById('wsState')?.textContent;
          if (webrtc !== 'connected' || ws !== 'connected') {
            document.getElementById('connectBtn')?.click();
          }
          for (let i = 0; i < 20; i++) {
            await new Promise(r => setTimeout(r, 1000));
            const a = document.getElementById('webrtcState')?.textContent;
            const b = document.getElementById('wsState')?.textContent;
            if (a === 'connected' && b === 'connected') {
              return {ok:true, webrtc:a, ws:b};
            }
          }
          return {
            ok:false,
            webrtc: document.getElementById('webrtcState')?.textContent,
            ws: document.getElementById('wsState')?.textContent,
            pc: window.__VISION_APP_STATE__?.pc ? {
              connectionState: window.__VISION_APP_STATE__.pc.connectionState,
              iceConnectionState: window.__VISION_APP_STATE__.pc.iceConnectionState,
              signalingState: window.__VISION_APP_STATE__.pc.signalingState,
            } : null
          };
        })()
        """,
    )


async def run_mode(cdp: CdpClient, mode: str, raw_json: bool, duration: int) -> dict[str, Any]:
    await eval_js(
        cdp,
        f"""
        (() => {{
          window.__VISION_DEBUG__?.reset?.();
          window.__VISION_DEBUG__?.setOverlayMode?.({json.dumps(mode)});
          window.__VISION_DEBUG__?.setRawJson?.({str(raw_json).lower()});
          return window.__VISION_DEBUG__?.snapshot?.();
        }})()
        """,
    )
    await asyncio.sleep(duration)
    snapshot = await eval_js(cdp, "window.__VISION_DEBUG__?.snapshot?.()")
    page_state = await eval_js(
        cdp,
        """
        (() => ({
          webrtc: document.getElementById('webrtcState')?.textContent,
          ws: document.getElementById('wsState')?.textContent,
          stream: document.getElementById('streamState')?.textContent,
          frame: document.getElementById('frameInfo')?.textContent,
          persons: document.getElementById('personCount')?.textContent,
          detectFps: document.getElementById('detectionFps')?.textContent,
          trackFps: document.getElementById('trackingFps')?.textContent,
          poseFps: document.getElementById('poseFps')?.textContent,
        }))()
        """,
    )
    status = fetch_status()
    return {
        "mode": mode,
        "raw_json": raw_json,
        "page_state": page_state,
        "frontend": snapshot,
        "backend": status,
    }


def fetch_status() -> dict[str, Any] | None:
    try:
        response = requests.get("http://127.0.0.1:8000/status?camera_id=camera_01", timeout=3)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
