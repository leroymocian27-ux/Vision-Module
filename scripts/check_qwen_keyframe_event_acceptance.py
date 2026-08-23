from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import requests

_SAFE_INCIDENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_FORBIDDEN_QWEN_TEXT = ("image_path", "keyframe_url", "archive_path", "rtsp", "token", ":\\", "/var/", "/tmp/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only acceptance check for a completed local Qwen event advisory.")
    parser.add_argument("--base-url", required=True, help="Temporary loopback Vision instance, for example http://127.0.0.1:8135")
    parser.add_argument("--incident-id", required=True)
    parser.add_argument("--require-six-keyframes", action="store_true")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()

    if not _SAFE_INCIDENT_ID.fullmatch(args.incident_id):
        return _emit({"status": "REVISE", "reason": "invalid_incident_id"}, args.output)
    if not _is_loopback_url(args.base_url):
        return _emit({"status": "REVISE", "reason": "base_url_must_be_loopback"}, args.output)

    base_url = args.base_url.rstrip("/")
    try:
        status_response = requests.get(f"{base_url}/events/status", timeout=5)
        event_response = requests.get(f"{base_url}/events/{args.incident_id}", timeout=5)
        status_response.raise_for_status()
        event_response.raise_for_status()
        status = status_response.json()
        event = event_response.json()
    except (requests.RequestException, ValueError) as exc:
        return _emit({"status": "REVISE", "reason": "event_api_unavailable", "error_type": type(exc).__name__}, args.output)

    advisory = event.get("qwen_advisory") if isinstance(event, dict) else None
    trusted = event.get("trusted_result") if isinstance(event, dict) else None
    keyframes = ((event.get("evidence_package") or {}).get("keyframes") or []) if isinstance(event, dict) else []
    available = [item for item in keyframes if isinstance(item, dict) and item.get("available")]
    qwen_text = json.dumps(advisory or {}, ensure_ascii=False).lower()
    qwen_safe = not any(token in qwen_text for token in _FORBIDDEN_QWEN_TEXT)
    checks = {
        "event_pipeline_enabled": bool(status.get("event_pipeline_enabled")),
        "qwen_keyframe_analysis_enabled": bool(status.get("qwen_keyframe_analysis_enabled")),
        "confirmed_event": bool(isinstance(trusted, dict) and trusted.get("final_event_type") == "fallen_confirmed"),
        "qwen_completed": bool(isinstance(advisory, dict) and advisory.get("analysis_status") == "completed"),
        "qwen_has_images": bool(isinstance(advisory, dict) and int(advisory.get("image_count") or 0) > 0),
        "qwen_scene_summary": bool(isinstance(advisory, dict) and str(advisory.get("scene_summary") or "").strip()),
        "qwen_payload_redacted": qwen_safe,
        "six_keyframes": len(available) == 6,
    }
    required = {key: value for key, value in checks.items() if key != "six_keyframes" or args.require_six_keyframes}
    report = {
        "status": "PASS" if all(required.values()) else "REVISE",
        "incident_id": args.incident_id,
        "checks": checks,
        "qwen_status": advisory.get("analysis_status") if isinstance(advisory, dict) else None,
        "qwen_model": advisory.get("model_name") if isinstance(advisory, dict) else None,
        "qwen_latency_ms": advisory.get("latency_ms") if isinstance(advisory, dict) else None,
        "available_keyframe_count": len(available),
        "evidence_status": (event.get("archive_summary") or {}).get("evidence_status") if isinstance(event, dict) else None,
    }
    return _emit(report, args.output)


def _is_loopback_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _emit(report: dict, output: Path | None) -> int:
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
