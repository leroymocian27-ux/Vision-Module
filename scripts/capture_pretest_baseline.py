from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def _get_json(url: str, *, timeout: float) -> Any:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _alarm_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), list):
            return [item for item in payload["value"] if isinstance(item, dict)]
        if isinstance(payload.get("items"), list):
            return [item for item in payload["items"] if isinstance(item, dict)]
        if isinstance(payload.get("alarms"), list):
            return [item for item in payload["alarms"] if isinstance(item, dict)]
        if isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, dict)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a pre-test baseline snapshot for fall alert linkage.")
    parser.add_argument("--vision-base", default="http://127.0.0.1:8000")
    parser.add_argument("--main-base", required=True, help="Main-system API base that exposes /alarms and /alarms/queue, e.g. http://<main-host>:8000/api/v1")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", default="logs/pretest_baseline_latest.json")
    args = parser.parse_args()

    vision_base = args.vision_base.rstrip("/")
    main_base = args.main_base.rstrip("/")
    now = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "captured_at": now,
        "vision_base": vision_base,
        "main_base": main_base,
        "camera_id": args.camera_id,
        "vision": {
            "healthz": _get_json(f"{vision_base}/healthz", timeout=args.timeout),
            "status": _get_json(f"{vision_base}/status?camera_id={args.camera_id}", timeout=args.timeout),
            "stream_source": _get_json(f"{vision_base}/stream/source?camera_id={args.camera_id}", timeout=args.timeout),
            "latest_result": _get_json(f"{vision_base}/integration/results/{args.camera_id}/latest", timeout=args.timeout),
            "alerting_status": _get_json(f"{vision_base}/alerting/status", timeout=args.timeout),
        },
    }

    alarms_payload = _get_json(f"{main_base}/alarms?active_only=true&limit=50", timeout=args.timeout)
    queue_payload = _get_json(f"{main_base}/alarms/queue", timeout=args.timeout)
    alarms = _alarm_items(alarms_payload)
    snapshot["main_system"] = {
        "alarms_active": alarms_payload,
        "alarm_queue": queue_payload,
        "active_alarm_count": len(alarms),
        "active_alarm_ids": [str(item.get("id") or "") for item in alarms if item.get("id")],
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output_path.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
