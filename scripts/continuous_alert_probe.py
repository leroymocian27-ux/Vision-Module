from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests


def build_payload(camera_id: str, track_id: str, fall_prob: float) -> dict:
    probability = max(0.0, min(1.0, float(fall_prob)))
    suffix = uuid4().hex[:8]
    return {
        "camera_id": camera_id,
        "stream_name": "primary",
        "source": "vision_service_continuous_probe",
        "event_type": "fall_confirmed",
        "state": "confirmed_fall",
        "status": "fallen_confirmed",
        "service_state": "running",
        "severity": "L3",
        "risk": "critical",
        "risk_level": "critical",
        "fall_detected": True,
        "fall_prob": probability,
        "fall_score": probability,
        "track_id": f"{track_id}-{suffix}",
        "incident_id": f"vision-fall-probe-{camera_id}-{track_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}-{suffix}",
        "bbox": [80.0, 60.0, 380.0, 330.0],
        "snapshot_url": None,
        "snapshot_path": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": {
            "temporal": probability,
            "probe": 1.0,
        },
        "injury": {
            "level": "I3",
            "reason": "vision_service_continuous_probe",
            "advice": "Continuous LAN connectivity probe.",
        },
        "metadata": {
            "trigger": "continuous_probe",
            "provider": "probe",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Continuously POST simulated fall alerts for LAN endpoint verification.")
    parser.add_argument("--target-ip", required=True)
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--base-path", default="/api/v1/video-bridge/fall-events")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=2.5)
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--track-id", default="probe-track")
    parser.add_argument("--fall-prob", type=float, default=0.91)
    parser.add_argument("--log-file", default="logs/continuous_alert_probe.log")
    parser.add_argument("--config-file", default="data/alert_probe_target.json")
    parser.add_argument("--token", default="")
    parser.add_argument("--duration-seconds", type=float, default=0.0, help="Stop automatically after this many seconds; 0 means run forever.")
    args = parser.parse_args()

    config_path = Path(args.config_file)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "target_ip": args.target_ip,
                    "port": args.port,
                    "base_path": args.base_path,
                    "interval": args.interval,
                    "token": args.token,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    started_at = time.monotonic()
    while True:
        if args.duration_seconds > 0 and time.monotonic() - started_at >= args.duration_seconds:
            break
        target = load_target(config_path, args.target_ip, args.port, args.base_path, args.interval)
        url = f"http://{target['target_ip']}:{int(target['port'])}{normalize_path(str(target['base_path']))}"
        payload = build_payload(args.camera_id, args.track_id, args.fall_prob)
        headers = {"Content-Type": "application/json"}
        token = str(target.get("token") or "").strip()
        if token:
            headers["X-Vision-Service-Token"] = token
        record = {
            "url": url,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=args.timeout)
            record["status"] = response.status_code
            record["ok"] = response.status_code < 400
            record["body"] = response.text[:500]
        except Exception as exc:
            record["status"] = "request_error"
            record["ok"] = False
            record["body"] = str(exc)
        log_path.open("a", encoding="utf-8").write(json.dumps(record, ensure_ascii=False) + "\n")
        if args.duration_seconds > 0:
            remaining = args.duration_seconds - (time.monotonic() - started_at)
            if remaining <= 0:
                break
            time.sleep(min(max(float(target["interval"]), 0.2), remaining))
        else:
            time.sleep(max(float(target["interval"]), 0.2))


def normalize_path(value: str) -> str:
    return value if value.startswith("/") else f"/{value}"


def load_target(config_path: Path, default_ip: str, default_port: int, default_base_path: str, default_interval: float) -> dict:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("config payload must be an object")
    except Exception:
        payload = {}
    return {
        "target_ip": str(payload.get("target_ip") or default_ip),
        "port": int(payload.get("port") or default_port),
        "base_path": str(payload.get("base_path") or default_base_path),
        "interval": float(payload.get("interval") or default_interval),
        "token": str(payload.get("token") or ""),
    }


if __name__ == "__main__":
    raise SystemExit(main())
