from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CHECKED_KEYS = {
    "EVENT_ARCHIVE_DIR",
    "EVENT_ARCHIVE_ENABLED",
    "EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA",
    "EVENT_ARCHIVE_RETENTION_DAYS",
    "EVENT_DELIVERY_BACKEND",
    "EVENT_DELIVERY_ENABLED",
    "EVENT_DELIVERY_ENDPOINT",
    "EVENT_DELIVERY_MODE",
    "EVENT_DELIVERY_TARGET_URL",
    "EVENT_DELIVERY_TIMEOUT_SECONDS",
    "EVENT_DELIVERY_WORKER_ENABLED",
    "EVENT_KEYFRAME_SERVING_ENABLED",
    "EVENT_PIPELINE_ENABLED",
    "EVENT_RING_BUFFER_ENABLED",
    "EVENT_SEMANTIC_ENABLED",
    "EVENT_VLM_ENABLED",
    "EVENT_VLM_OLLAMA_ALLOW_NON_LOCALHOST",
    "EVENT_VLM_OLLAMA_ENDPOINT",
    "EVENT_VLM_OLLAMA_INCLUDE_IMAGES",
    "EVENT_VLM_OLLAMA_TEXT_ONLY",
    "EVENT_VLM_OLLAMA_TIMEOUT_SECONDS",
    "EVENT_VLM_PROVIDER",
    "EVENT_WORKER_ENABLED",
    "MAIN_SYSTEM_ALERT_ENABLED",
    "MAIN_SYSTEM_ALERT_TIMEOUT_MS",
    "MAIN_SYSTEM_ALERT_TOKEN",
    "MAIN_SYSTEM_ALERT_TOKEN_HEADER",
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def enabled(values: dict[str, str], key: str) -> bool:
    return values.get(key, "false").strip().lower() in {"1", "true", "yes", "on"}


def evaluate(
    values: dict[str, str],
    *,
    main_source: str | None = None,
    event_api_source: str | None = None,
) -> dict:
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"level": level, "code": code, "message": message})

    default_disabled_keys = (
        "EVENT_PIPELINE_ENABLED",
        "EVENT_RING_BUFFER_ENABLED",
        "EVENT_WORKER_ENABLED",
        "EVENT_SEMANTIC_ENABLED",
        "EVENT_ARCHIVE_ENABLED",
        "EVENT_DELIVERY_ENABLED",
        "EVENT_DELIVERY_WORKER_ENABLED",
        "EVENT_VLM_ENABLED",
        "EVENT_KEYFRAME_SERVING_ENABLED",
        "MAIN_SYSTEM_ALERT_ENABLED",
    )
    defaults = all(not enabled(values, key) for key in default_disabled_keys)
    add("pass" if defaults else "fail", "safe_defaults", "event side paths and external effects are disabled by default" if defaults else "one or more event side paths or external effects are enabled")

    if values.get("EVENT_DELIVERY_MODE", "dry_run") == "post":
        if not (values.get("EVENT_DELIVERY_TARGET_URL") or values.get("EVENT_DELIVERY_ENDPOINT")):
            add("fail", "delivery_missing_target_url", "post mode requires EVENT_DELIVERY_TARGET_URL or EVENT_DELIVERY_ENDPOINT")
        for key in ("MAIN_SYSTEM_ALERT_TOKEN_HEADER", "MAIN_SYSTEM_ALERT_TOKEN"):
            if not values.get(key):
                add("fail", f"delivery_missing_{key.lower()}", f"post mode requires {key}")
        if values.get("EVENT_DELIVERY_BACKEND") != "sqlite":
            add("fail", "delivery_backend", "post mode requires EVENT_DELIVERY_BACKEND=sqlite")
        if _positive_number(values.get("EVENT_DELIVERY_TIMEOUT_SECONDS", values.get("MAIN_SYSTEM_ALERT_TIMEOUT_MS", "0"))) is False:
            add("fail", "delivery_timeout", "post mode requires a positive timeout")

    archive_dir = Path(values.get("EVENT_ARCHIVE_DIR", "logs/event_archive"))
    archive_resolved = (ROOT / archive_dir).resolve() if not archive_dir.is_absolute() else archive_dir.resolve()
    allowed_archive_root = (ROOT / "logs").resolve()
    if enabled(values, "EVENT_ARCHIVE_ENABLED") or enabled(values, "EVENT_KEYFRAME_SERVING_ENABLED"):
        if not _inside(archive_resolved, allowed_archive_root):
            add("fail", "archive_dir_outside_logs", "EVENT_ARCHIVE_DIR must remain under the project logs directory")
        if int(values.get("EVENT_ARCHIVE_RETENTION_DAYS", "0")) < 1 or int(values.get("EVENT_ARCHIVE_MAX_EVENTS_PER_CAMERA", "0")) < 1:
            add("fail", "archive_retention", "archive retention days and per-camera limit must be positive")
    if enabled(values, "EVENT_KEYFRAME_SERVING_ENABLED"):
        source = main_source if main_source is not None else (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        if _archive_is_statically_mounted(source):
            add("fail", "keyframe_static_mount", "archive directory must not be statically mounted")
        else:
            add("warn", "keyframe_internal_only", "keyframe serving is enabled; restrict API to a trusted internal network")
        api_source = event_api_source if event_api_source is not None else (ROOT / "app" / "api" / "event_api.py").read_text(encoding="utf-8")
        if not _event_api_redacts_archive_paths(api_source):
            add("fail", "keyframe_absolute_path_exposure", "event API must redact local archive paths from JSON responses")

    if enabled(values, "EVENT_VLM_ENABLED"):
        provider = values.get("EVENT_VLM_PROVIDER", "disabled")
        if provider not in {"disabled", "dummy", "http_mock", "http", "ollama", "qwen_ollama", "ollama_qwen"}:
            add("fail", "vlm_provider", "VLM provider is not allowed")
        if provider in {"ollama", "qwen_ollama", "ollama_qwen"}:
            url = values.get("EVENT_VLM_OLLAMA_ENDPOINT", values.get("EVENT_OLLAMA_ENDPOINT", values.get("EVENT_OLLAMA_BASE_URL", "http://127.0.0.1:11434/api/chat")))
            allow_non_localhost = enabled(values, "EVENT_VLM_OLLAMA_ALLOW_NON_LOCALHOST") or enabled(values, "EVENT_OLLAMA_ALLOW_NON_LOCALHOST")
            if not allow_non_localhost and not _is_loopback_http_url(url):
                add("fail", "ollama_non_localhost", "ollama_qwen must use localhost unless explicitly allowed")
            text_only = values.get("EVENT_VLM_OLLAMA_TEXT_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
            if enabled(values, "EVENT_VLM_OLLAMA_INCLUDE_IMAGES") or enabled(values, "EVENT_OLLAMA_ALLOW_IMAGE_INPUT") or not text_only:
                add("fail", "ollama_image_input", "structured-only Ollama adapter does not permit image input")
            timeout = values.get("EVENT_VLM_OLLAMA_TIMEOUT_SECONDS", values.get("EVENT_OLLAMA_TIMEOUT_SECONDS", "0"))
            if _positive_number(timeout) is False:
                add("fail", "ollama_timeout", "Ollama timeout must be positive")

    return {
        "ok": not any(item["level"] == "fail" for item in findings),
        "findings": findings,
        "checked_keys": sorted(key for key in CHECKED_KEYS if key in values),
    }


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _positive_number(value: str) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _is_loopback_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _archive_is_statically_mounted(main_source: str) -> bool:
    compact = "".join(main_source.split())
    return "StaticFiles(directory=" in compact and any(
        marker in compact
        for marker in ("event_archive", "EVENT_ARCHIVE_DIR", "settings.event_archive_dir")
    )


def _event_api_redacts_archive_paths(event_api_source: str) -> bool:
    compact = "".join(event_api_source.split())
    return "payload[\"archive_path\"]=None" in compact and "_redact_local_absolute_paths" in compact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=".env.example")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = evaluate(read_env(Path(args.env)))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("PASS" if report["ok"] else "FAIL")
        for item in report["findings"]:
            print(f"{item['level'].upper()} {item['code']}: {item['message']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
