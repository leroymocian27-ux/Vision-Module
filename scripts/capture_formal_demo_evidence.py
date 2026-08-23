from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import urlopen


JsonFetcher = Callable[[str], tuple[int, dict[str, Any]]]
BinaryFetcher = Callable[[str], tuple[int, str]]
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?:^|[^A-Za-z0-9])[A-Za-z]:[\\/]")
_UNIX_ABSOLUTE_PATH = re.compile(r"(?:^|[^A-Za-z0-9:/\\])/(?!events/)")
_FORBIDDEN_PUBLIC_KEYS = {
    "authorization",
    "auth_header",
    "lock_owner",
    "lock_token",
    "lock_until",
    "payload_json",
    "raw_response",
    "source_url",
    "target_url",
    "token",
}
_KEYFRAME_SELECTORS = (
    "t_minus_3s",
    "t_minus_1s",
    "t0",
    "t_plus_1s",
    "t_plus_3s",
    "t_plus_5s",
)


def _safe_loopback_base_url(value: str) -> str | None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    return value.rstrip("/")


def _fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - all callers loopback-validate the base URL.
        payload = json.loads(response.read().decode("utf-8"))
        return int(response.status), payload if isinstance(payload, dict) else {}


def _fetch_binary_metadata(url: str) -> tuple[int, str]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - all callers loopback-validate the base URL.
        response.read(1)
        return int(response.status), str(response.headers.get("Content-Type", ""))


def evaluate(
    *,
    live_url: str = "http://127.0.0.1:8000",
    demo_url: str = "http://127.0.0.1:8011",
    incident_id: str = "demo-rehearsal-20260718-candidate",
    fetch_json: JsonFetcher = _fetch_json,
    fetch_binary: BinaryFetcher = _fetch_binary_metadata,
) -> dict[str, Any]:
    """Collect a redacted P1 evidence summary without starting a service or writing config."""
    checks: list[dict[str, str]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "result": "pass" if passed else "fail", "detail": detail})

    live = _safe_loopback_base_url(live_url)
    demo = _safe_loopback_base_url(demo_url)
    if live is None:
        add("live_url", False, "live URL must be credential-free HTTP loopback")
    if demo is None:
        add("demo_url", False, "demo URL must be credential-free HTTP loopback")
    if not _safe_incident_id(incident_id):
        add("incident_id", False, "incident ID must use the safe event API identifier format")
    if any(check["result"] == "fail" for check in checks):
        return _report(checks, incident_id, keyframes=0)

    assert live is not None and demo is not None
    _check_health("live", live, fetch_json, add)
    _check_event_status("live", live, expected_pipeline=False, fetch_json=fetch_json, add=add)
    demo_healthy = _check_health("demo", demo, fetch_json, add)
    demo_status_ready = _check_event_status("demo", demo, expected_pipeline=True, fetch_json=fetch_json, add=add)

    if not demo_healthy or not demo_status_ready:
        _add_unavailable_event_checks(add)
        return _report(checks, incident_id, keyframes=0)

    detail: dict[str, Any] = {}
    detail_available = False
    try:
        detail_status, detail = fetch_json(f"{demo}/events/{incident_id}")
        detail_available = detail_status == 200 and _detail_incident_id(detail) == incident_id
        add("demo_event_detail", detail_available, "event detail is available for the selected synthetic candidate")
    except Exception:
        add("demo_event_detail", False, "event detail endpoint is unavailable")

    detail_safe = detail_available and _public_detail_is_safe(detail, incident_id)
    add("public_event_payload", detail_safe, "event detail contains no forbidden field or absolute local path" if detail_available else "event detail was unavailable and cannot be verified")
    trusted = detail.get("trusted_result") if isinstance(detail, dict) else None
    add("rule_review", isinstance(trusted, dict) and bool(trusted.get("review_result")), "rule-review result is present")

    delivery = detail.get("delivery") if isinstance(detail, dict) else None
    delivery_ok = isinstance(delivery, dict) and delivery.get("delivery_mode") == "dry_run" and delivery.get("delivery_status") == "dry_run_sent" and delivery.get("dry_run") is True
    add("delivery_dry_run", delivery_ok, "delivery record is dry-run only and is not a real main-system POST")

    if not detail_available:
        _add_unavailable_event_checks(add, include_detail=False)
        return _report(checks, incident_id, keyframes=0)

    keyframes = 0
    for selector in _KEYFRAME_SELECTORS:
        try:
            status, content_type = fetch_binary(f"{demo}/events/{incident_id}/keyframes/{selector}")
            passed = status == 200 and content_type.lower().startswith("image/jpeg")
        except Exception:
            passed = False
        if passed:
            keyframes += 1
        add(f"keyframe_{selector}", passed, "keyframe response is 200 image/jpeg" if passed else "keyframe is unavailable or not an image/jpeg response")

    return _report(checks, incident_id, keyframes=keyframes)


def _report(checks: list[dict[str, str]], incident_id: str, *, keyframes: int) -> dict[str, Any]:
    return {
        "ok": all(check["result"] == "pass" for check in checks),
        "scope": "formal_demo_synthetic_only",
        "incident_id": incident_id,
        "keyframe_count": keyframes,
        "checks": checks,
        "safety_boundary": {
            "writes_performed": False,
            "services_started": False,
            "external_network_used": False,
            "images_persisted": False,
            "raw_payloads_persisted": False,
        },
    }


def _check_health(label: str, base_url: str, fetch_json: JsonFetcher, add: Callable[[str, bool, str], None]) -> bool:
    try:
        status, payload = fetch_json(f"{base_url}/healthz")
        passed = status == 200 and payload.get("status") == "ok"
        add(f"{label}_healthz", passed, "health endpoint is available")
        return passed
    except Exception:
        add(f"{label}_healthz", False, "health endpoint is unavailable")
        return False


def _check_event_status(
    label: str,
    base_url: str,
    *,
    expected_pipeline: bool,
    fetch_json: JsonFetcher,
    add: Callable[[str, bool, str], None],
) -> bool:
    try:
        status, payload = fetch_json(f"{base_url}/events/status")
        pipeline_ok = status == 200 and payload.get("event_pipeline_enabled") is expected_pipeline
        vlm_ok = payload.get("vlm_enabled") is False
        add(f"{label}_event_pipeline", pipeline_ok, "event pipeline has the required instance state")
        add(f"{label}_vlm", vlm_ok, "VLM/Ollama is disabled")
        return pipeline_ok and vlm_ok
    except Exception:
        add(f"{label}_event_pipeline", False, "event status endpoint is unavailable")
        add(f"{label}_vlm", False, "VLM state could not be verified")
        return False


def _add_unavailable_event_checks(add: Callable[[str, bool, str], None], *, include_detail: bool = True) -> None:
    if include_detail:
        add("demo_event_detail", False, "event detail was not requested because the demo instance is unavailable")
        add("public_event_payload", False, "event detail was not requested and cannot be verified")
    add("rule_review", False, "rule-review result was not requested because the demo instance is unavailable")
    add("delivery_dry_run", False, "delivery result was not requested because the demo instance is unavailable")
    for selector in _KEYFRAME_SELECTORS:
        add(f"keyframe_{selector}", False, "keyframe was not requested because the demo instance is unavailable")


def _public_detail_is_safe(value: Any, incident_id: str) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_PUBLIC_KEYS or not _public_detail_is_safe(child, incident_id):
                return False
        return True
    if isinstance(value, list):
        return all(_public_detail_is_safe(item, incident_id) for item in value)
    if not isinstance(value, str):
        return True
    if _WINDOWS_ABSOLUTE_PATH.search(value) or _UNIX_ABSOLUTE_PATH.search(value):
        return False
    return not (value.startswith("/events/") and not value.startswith(f"/events/{incident_id}/"))


def _safe_incident_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value))


def _detail_incident_id(detail: dict[str, Any]) -> str | None:
    direct = detail.get("incident_id")
    if isinstance(direct, str):
        return direct
    event = detail.get("event")
    nested = event.get("incident_id") if isinstance(event, dict) else None
    return nested if isinstance(nested, str) else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only synthetic formal-demo evidence collector.")
    parser.add_argument("--live-url", default="http://127.0.0.1:8000")
    parser.add_argument("--demo-url", default="http://127.0.0.1:8011")
    parser.add_argument("--incident-id", default="demo-rehearsal-20260718-candidate")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON summary path; no service or configuration is modified.")
    args = parser.parse_args()
    report = evaluate(live_url=args.live_url, demo_url=args.demo_url, incident_id=args.incident_id)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
