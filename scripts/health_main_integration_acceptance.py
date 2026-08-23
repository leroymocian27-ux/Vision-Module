from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np
import requests


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate health-main fall alert integration end to end.")
    parser.add_argument(
        "--main-system-base-url",
        default=os.getenv("MAIN_SYSTEM_BASE_URL", "http://127.0.0.1:8090/api/v1"),
    )
    parser.add_argument("--main-system-origin", default=os.getenv("MAIN_SYSTEM_ORIGIN", "http://127.0.0.1:8090"))
    parser.add_argument(
        "--vision-public-base-url",
        default=os.getenv("VISION_SERVICE_PUBLIC_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--snapshot-dir", default="logs/fall_events/snapshots")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--track-id", default="acceptance-smoke")
    parser.add_argument("--fall-prob", type=float, default=0.92)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--skip-snapshot-reachability", action="store_true")
    args = parser.parse_args()

    base_url = args.main_system_base_url.rstrip("/")
    origin = args.main_system_origin.rstrip("/")
    if args.main_system_origin == parser.get_default("main_system_origin"):
        origin = _origin_from_api_base(base_url)
    summary: dict[str, Any] = {
        "ok": False,
        "main_system_base_url": base_url,
        "vision_public_base_url": args.vision_public_base_url.rstrip("/"),
        "checks": {},
    }

    health = _get_json(f"{origin}/healthz", timeout=args.timeout)
    summary["checks"]["healthz"] = health
    if not health["ok"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 2

    timestamp_slug = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    snapshot_url = _create_smoke_snapshot(
        snapshot_dir=Path(args.snapshot_dir),
        public_base_url=args.vision_public_base_url,
        camera_id=args.camera_id,
        track_id=args.track_id,
        timestamp_slug=timestamp_slug,
    )
    summary["snapshot_url"] = snapshot_url

    if not args.skip_snapshot_reachability:
        snapshot_check = _get_bytes(snapshot_url, timeout=args.timeout)
        summary["checks"]["snapshot_reachable"] = snapshot_check
        if not snapshot_check["ok"]:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 3

    payload = _build_payload(
        camera_id=args.camera_id,
        track_id=args.track_id,
        fall_prob=args.fall_prob,
        snapshot_url=snapshot_url,
        timestamp_slug=timestamp_slug,
    )
    post = _post_json(f"{base_url}/video-bridge/fall-events", payload, timeout=args.timeout)
    summary["checks"]["post_fall_event"] = post
    if not post["ok"]:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 4

    response_json = post.get("json") or {}
    alarm_id = str(response_json.get("alarm_id") or "")
    summary["alarm_id"] = alarm_id
    if not alarm_id:
        summary["checks"]["alarm_id_present"] = {"ok": False, "error": "missing alarm_id"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 5
    summary["checks"]["alarm_id_present"] = {"ok": True}

    alarms = _get_json(f"{base_url}/alarms", params={"active_only": "true"}, timeout=args.timeout)
    queue_snapshot = _get_json(f"{base_url}/alarms/queue", timeout=args.timeout)
    summary["checks"]["alarms_active"] = alarms
    summary["checks"]["alarm_queue"] = queue_snapshot
    alarm_found = _contains_alarm_id(alarms.get("json"), alarm_id) or _contains_alarm_id(queue_snapshot.get("json"), alarm_id)
    summary["checks"]["alarm_visible"] = {"ok": alarm_found, "alarm_id": alarm_id}
    summary["ok"] = bool(alarm_found)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if alarm_found else 6


def _build_payload(
    *,
    camera_id: str,
    track_id: str,
    fall_prob: float,
    snapshot_url: str,
    timestamp_slug: str,
) -> dict[str, Any]:
    probability = max(0.0, min(1.0, float(fall_prob)))
    return {
        "camera_id": camera_id,
        "stream_name": "primary",
        "source": "vision_service_acceptance",
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
        "track_id": track_id,
        "incident_id": f"vision-fall-acceptance-{camera_id}-{track_id}-{timestamp_slug}",
        "bbox": [80.0, 60.0, 380.0, 330.0],
        "snapshot_url": snapshot_url,
        "snapshot_path": snapshot_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": {
            "temporal": probability,
            "acceptance": 1.0,
        },
        "injury": {
            "level": "I3",
            "reason": "vision_service_acceptance_test",
            "advice": "Please inspect the live camera view immediately and confirm the elder's condition.",
        },
        "metadata": {
            "event": {
                "incident_id": f"vision-fall-acceptance-{camera_id}-{track_id}-{timestamp_slug}",
                "camera_id": camera_id,
                "stream_name": "primary",
                "event_type": "fall_confirmed",
                "state": "confirmed_fall",
                "status": "fallen_confirmed",
                "severity": "L3",
                "risk": "critical",
                "risk_level": "critical",
                "fall_score": probability,
                "fall_prob": probability,
                "track_id": track_id,
                "snapshot_url": snapshot_url,
                "snapshot_path": snapshot_url,
                "injury": {
                    "level": "I3",
                    "reason": "vision_service_acceptance_test",
                    "advice": "Please inspect the live camera view immediately and confirm the elder's condition.",
                },
                "multimodal_review": {
                    "provider": "shadow",
                    "temporal_source": "acceptance",
                    "scores": {
                        "temporal": probability,
                        "acceptance": 1.0,
                    },
                },
            },
            "trigger": "vision_service_acceptance_script",
            "provider": "shadow",
        },
    }


def _create_smoke_snapshot(
    *,
    snapshot_dir: Path,
    public_base_url: str,
    camera_id: str,
    track_id: str,
    timestamp_slug: str,
) -> str:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_safe_slug(camera_id)}_{_safe_slug(track_id)}_{timestamp_slug}_acceptance.jpg"
    path = snapshot_dir / filename
    image = np.zeros((360, 640, 3), dtype=np.uint8)
    image[:, :, 2] = 80
    cv2.rectangle(image, (80, 120), (560, 300), (0, 0, 230), 4)
    cv2.putText(
        image,
        "FALL EVENT SMOKE SNAPSHOT",
        (95, 190),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(path), image)
    return f"{public_base_url.rstrip('/')}/fall-events/snapshots/{filename}"


def _get_json(url: str, *, timeout: float, params: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        response = requests.get(url, params=params, timeout=timeout)
        data: Any
        try:
            data = response.json()
        except ValueError:
            data = response.text[:500]
        return {"ok": 200 <= response.status_code < 400, "status": response.status_code, "json": data}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


def _get_bytes(url: str, *, timeout: float) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout)
        return {
            "ok": 200 <= response.status_code < 400 and len(response.content) > 0,
            "status": response.status_code,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type"),
        }
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


def _post_json(url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    try:
        response = requests.post(url, json=payload, timeout=timeout)
        data: Any
        try:
            data = response.json()
        except ValueError:
            data = response.text[:500]
        return {"ok": 200 <= response.status_code < 400, "status": response.status_code, "json": data}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


def _contains_alarm_id(value: Any, alarm_id: str) -> bool:
    if isinstance(value, dict):
        if str(value.get("id") or value.get("alarm_id") or "") == alarm_id:
            return True
        return any(_contains_alarm_id(item, alarm_id) for item in value.values())
    if isinstance(value, list):
        return any(_contains_alarm_id(item, alarm_id) for item in value)
    return False


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value).strip("._") or "unknown"


def _origin_from_api_base(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


if __name__ == "__main__":
    raise SystemExit(main())
