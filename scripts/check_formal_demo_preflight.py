from __future__ import annotations

import argparse
import json
from typing import Any, Callable
from urllib.parse import urlsplit
from urllib.request import urlopen


JsonFetcher = Callable[[str], tuple[int, dict[str, Any]]]


def _is_safe_loopback_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _fetch_json(url: str) -> tuple[int, dict[str, Any]]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - URL is loopback-validated by evaluate.
        payload = json.loads(response.read().decode("utf-8"))
        return int(response.status), payload if isinstance(payload, dict) else {}


def evaluate(
    *,
    live_url: str = "http://127.0.0.1:8000",
    demo_url: str | None = None,
    fetch_json: JsonFetcher = _fetch_json,
) -> dict[str, Any]:
    """Return a redacted, read-only readiness report for the dual-instance demo."""
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"level": level, "code": code, "message": message})

    targets = {"live": live_url}
    if demo_url:
        targets["demo"] = demo_url
    for label, target in targets.items():
        if not _is_safe_loopback_url(target):
            add("fail", f"{label}_url", "preflight accepts an HTTP loopback base URL without credentials")

    if any(item["level"] == "fail" for item in findings):
        return {"ok": False, "findings": findings, "checked_targets": sorted(targets)}

    _check_health("live", _normalize_base_url(live_url), fetch_json, add)
    _check_event_pipeline("live", _normalize_base_url(live_url), expected_enabled=False, fetch_json=fetch_json, add=add)
    if demo_url:
        normalized_demo = _normalize_base_url(demo_url)
        _check_health("demo", normalized_demo, fetch_json, add)
        _check_event_pipeline("demo", normalized_demo, expected_enabled=True, fetch_json=fetch_json, add=add)

    return {
        "ok": not any(item["level"] == "fail" for item in findings),
        "findings": findings,
        "checked_targets": sorted(targets),
        "safety_boundary": {
            "writes_performed": False,
            "external_network_used": False,
            "sensitive_response_fields_recorded": False,
        },
    }


def _check_health(label: str, base_url: str, fetch_json: JsonFetcher, add: Callable[[str, str, str], None]) -> None:
    try:
        status, payload = fetch_json(f"{base_url}/healthz")
    except Exception:
        add("fail", f"{label}_healthz", "health endpoint is unavailable")
        return
    if status == 200 and payload.get("status") == "ok":
        add("pass", f"{label}_healthz", "health endpoint is available")
    else:
        add("fail", f"{label}_healthz", "health endpoint did not return the expected safe status")


def _check_event_pipeline(
    label: str,
    base_url: str,
    *,
    expected_enabled: bool,
    fetch_json: JsonFetcher,
    add: Callable[[str, str, str], None],
) -> None:
    try:
        status, payload = fetch_json(f"{base_url}/events/status")
    except Exception:
        add("fail", f"{label}_event_status", "event status endpoint is unavailable")
        return

    enabled = payload.get("event_pipeline_enabled")
    vlm_enabled = payload.get("vlm_enabled")
    if status != 200 or enabled is not expected_enabled:
        desired = "enabled" if expected_enabled else "disabled"
        add("fail", f"{label}_event_pipeline", f"event pipeline must be {desired} for this demo instance")
    else:
        desired = "enabled" if expected_enabled else "disabled"
        add("pass", f"{label}_event_pipeline", f"event pipeline is {desired}")

    if vlm_enabled is False:
        add("pass", f"{label}_vlm", "VLM/Ollama is disabled")
    else:
        add("fail", f"{label}_vlm", "VLM/Ollama must remain disabled during the formal demo")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only dual-instance formal-demo preflight check.")
    parser.add_argument("--live-url", default="http://127.0.0.1:8000")
    parser.add_argument("--demo-url", default=None, help="Optional temporary loopback demo instance, such as http://127.0.0.1:8011")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate(live_url=args.live_url, demo_url=args.demo_url)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for finding in report["findings"]:
            print(f"{finding['level'].upper()} {finding['code']}: {finding['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
