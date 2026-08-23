from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import create_app


def gpu_snapshot() -> dict:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError:
        return {"status": "NOT_AVAILABLE"}
    if completed.returncode != 0:
        return {"status": "UNAVAILABLE", "stderr": completed.stderr.strip()[:300]}
    return {"status": "AVAILABLE", "rows": [line.strip() for line in completed.stdout.splitlines() if line.strip()]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely validate PFV2 FastAPI runtime against the configured mock source.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/post_fall_v2/finalization/runtime_validation_report.json"),
    )
    args = parser.parse_args()
    process = psutil.Process()
    report: dict = {
        "source_classification": "MOCK_RUNTIME_SANITY_ONLY",
        "status": "FAIL",
        "endpoints": {},
        "websocket": {},
        "resource_before": {
            "rss_bytes": process.memory_info().rss,
            "cpu_percent": process.cpu_percent(interval=None),
            "gpu": gpu_snapshot(),
        },
    }
    try:
        with TestClient(create_app()) as client:
            latest = None
            for _ in range(30):
                latest = client.get("/stream/latest-frame.jpg")
                if latest.status_code == 200:
                    break
                time.sleep(0.2)
            for path in ("/status", "/demo/", "/stream/source"):
                response = client.get(path)
                report["endpoints"][path] = {"status_code": response.status_code}
                if path == "/status" and response.status_code == 200:
                    body = response.json()
                    configuration = body.get("configuration") or {}
                    effective_config = configuration.get("effective_config") or {}
                    report["status_snapshot"] = {
                        "pipeline_mode": effective_config.get("pipeline_mode"),
                        "post_fall_v2_enabled": effective_config.get("post_fall_v2_enabled"),
                        "post_fall_v2_qwen_enabled": effective_config.get("post_fall_v2_qwen_enabled"),
                    }
                if path == "/stream/source" and response.status_code == 200:
                    body = response.json()
                    report["stream_source"] = {
                        "camera_id": body.get("camera_id"),
                        "source_url_masked": body.get("source_url_masked"),
                        "stream_state": body.get("stream_state"),
                    }
            report["endpoints"]["/stream/latest-frame.jpg"] = {
                "status_code": latest.status_code if latest is not None else None,
                "content_type": latest.headers.get("content-type") if latest is not None else None,
            }
            try:
                with client.websocket_connect("/ws/results") as websocket:
                    payload = websocket.receive_json()
                report["websocket"] = {
                    "status": "PASS",
                    "pipeline": payload.get("detector", {}).get("pipeline"),
                    "camera_id": payload.get("camera_id"),
                }
            except Exception as exc:
                report["websocket"] = {"status": "FAIL", "reason": type(exc).__name__}
            report["status"] = (
                "PASS"
                if all(item.get("status_code") == 200 for item in report["endpoints"].values())
                and report["status_snapshot"].get("pipeline_mode") == "post_fall_v2"
                and report["websocket"].get("status") == "PASS"
                else "PARTIAL"
            )
    except Exception as exc:
        report["reason"] = f"{type(exc).__name__}: {exc}"
    report["resource_after"] = {
        "rss_bytes": process.memory_info().rss,
        "cpu_percent": process.cpu_percent(interval=0.1),
        "gpu": gpu_snapshot(),
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": report["status"]}, ensure_ascii=False))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
