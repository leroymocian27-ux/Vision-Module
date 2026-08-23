from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.camera.source_models import mask_source_url


DEFAULT_PATHS = [
    "/tcp/av0_1",
    "/tcp/av0_0",
    "/av0_1",
    "/av0_0",
    "/Streaming/Channels/101",
    "/Streaming/Channels/102",
    "/h264/ch1/main/av_stream",
    "/h264/ch1/sub/av_stream",
    "/live/ch00_0",
    "/live/ch00_1",
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    "/11",
    "/12",
]


@dataclass
class ProbeResult:
    url_masked: str
    reachable: bool
    opened: bool
    frames: int
    width: int | None
    height: int | None
    elapsed_ms: float
    error: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe RTSP URLs and report the first source that yields video frames.")
    parser.add_argument("--host", default="192.186.8.254")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--port", type=int, default=554)
    parser.add_argument("--paths", nargs="+", default=DEFAULT_PATHS)
    parser.add_argument("--urls", nargs="*", default=[], help="Explicit RTSP URLs to probe before generated URLs.")
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    parser.add_argument("--output", default="logs/camera_rtsp_probe_latest.json")
    args = parser.parse_args()

    urls = list(args.urls)
    for path in args.paths:
        normalized = path if path.startswith("/") else f"/{path}"
        urls.append(f"rtsp://{args.username}:***@{args.host}:{args.port}{normalized}")

    results: list[ProbeResult] = []
    first_working: str | None = None
    for url in urls:
        result = probe_url(url, args.host, args.port, args.timeout_sec)
        results.append(result)
        print(json.dumps(asdict(result), ensure_ascii=False), flush=True)
        if result.opened and result.frames > 0:
            first_working = url
            break

    payload = {
        "host": args.host,
        "port": args.port,
        "first_working_url_masked": mask_source_url(first_working) if first_working else None,
        "passed": first_working is not None,
        "results": [asdict(item) for item in results],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if first_working else 2


def probe_url(url: str, fallback_host: str, fallback_port: int, timeout_sec: float) -> ProbeResult:
    started = time.monotonic()
    parsed = urlparse(url)
    host = parsed.hostname or fallback_host
    port = parsed.port or fallback_port
    reachable, reach_error = check_port(host, port, timeout_sec)
    opened = False
    frames = 0
    width: int | None = None
    height: int | None = None
    error = reach_error
    if reachable:
        try:
            import av

            container = av.open(
                url,
                mode="r",
                options={"rtsp_transport": "tcp"},
                timeout=(timeout_sec, timeout_sec),
            )
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                error = "no_video_stream"
            else:
                opened = True
                for frame in container.decode(stream):
                    frames += 1
                    width = int(frame.width)
                    height = int(frame.height)
                    break
                error = None if frames > 0 else "no_first_frame"
            container.close()
        except Exception as exc:
            error = str(exc)[:300]
    elapsed_ms = round((time.monotonic() - started) * 1000, 2)
    return ProbeResult(
        url_masked=mask_source_url(url),
        reachable=reachable,
        opened=opened,
        frames=frames,
        width=width,
        height=height,
        elapsed_ms=elapsed_ms,
        error=error,
    )


def check_port(host: str, port: int, timeout_sec: float) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True, None
    except OSError as exc:
        return False, str(exc)


if __name__ == "__main__":
    raise SystemExit(main())
