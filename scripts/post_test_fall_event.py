from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Post a smoke fall event to health-main video bridge.")
    parser.add_argument(
        "--main-system-base-url",
        default=os.getenv("MAIN_SYSTEM_BASE_URL", "http://127.0.0.1:8090/api/v1"),
    )
    parser.add_argument("--path", default="/video-bridge/fall-events")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--track-id", default="smoke-track")
    parser.add_argument("--snapshot-url", default=None)
    parser.add_argument("--fall-prob", type=float, default=0.91)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    base_url = args.main_system_base_url.rstrip("/")
    path = args.path if args.path.startswith("/") else f"/{args.path}"
    url = f"{base_url}{path}"
    timestamp = datetime.now(timezone.utc).isoformat()
    incident_id = f"vision-fall-smoke-{args.camera_id}-{args.track_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    payload = {
        "camera_id": args.camera_id,
        "stream_name": "primary",
        "source": "vision_service_smoke",
        "event_type": "fall_confirmed",
        "state": "confirmed_fall",
        "status": "fallen_confirmed",
        "service_state": "running",
        "severity": "L3",
        "risk": "critical",
        "risk_level": "critical",
        "fall_detected": True,
        "fall_prob": max(0.0, min(1.0, args.fall_prob)),
        "fall_score": max(0.0, min(1.0, args.fall_prob)),
        "track_id": args.track_id,
        "incident_id": incident_id,
        "bbox": [80.0, 60.0, 380.0, 330.0],
        "snapshot_url": args.snapshot_url,
        "snapshot_path": args.snapshot_url,
        "timestamp": timestamp,
        "scores": {
            "temporal": max(0.0, min(1.0, args.fall_prob)),
            "smoke": 1.0,
        },
        "injury": {
            "level": "I3",
            "reason": "vision_service_smoke_test",
            "advice": "Please inspect the live camera view immediately and confirm the elder's condition.",
        },
        "metadata": {
            "trigger": "vision_service_smoke_script",
            "provider": "shadow",
        },
    }
    response = requests.post(url, json=payload, timeout=args.timeout)
    print(f"POST {url}")
    print(f"status={response.status_code}")
    print(response.text)
    response.raise_for_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
