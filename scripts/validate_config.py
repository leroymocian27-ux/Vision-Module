from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEYWORDS = ("PASSWORD", "TOKEN", "SECRET", "AUTH")
REQUIRED_SAFE_FALSE = {
    "MAIN_SYSTEM_ALERT_ENABLED",
    "EVENT_DELIVERY_ENABLED",
    "EVENT_VLM_ENABLED",
    "EVENT_QWEN_KEYFRAME_ANALYSIS_ENABLED",
    "QWEN_MEDIA_INPUT_ENABLED",
    "ROBOT_ASSIST_SERVICE_ENABLED",
    "ROBOT_ASSIST_ENABLED",
    "ROBOT_AUTO_DISPATCH_ENABLED",
    "GO2_READ_ONLY_ENABLED",
    "GO2_CONTROL_ENABLED",
    "GO2_LOW_LEVEL_CONTROL_ENABLED",
}
MODEL_KEYS = (
    "YOLO_MODEL_PATH",
    "YOLO_FALL_MODEL_PATH",
    "TEMPORAL_ONNX_MODEL_PATH",
    "YOLO_POSE_MODEL_PATH",
    "YOLO11_POSE_MODEL_PATH",
    "RTMPOSE_ONNX_MODEL_PATH",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Vision Service runtime profile.")
    parser.add_argument("--profile", default="safe_demo", help="Profile name under configs/ or an env file path.")
    parser.add_argument("--json-out", type=Path, help="Optional JSON report path.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args()

    profile_path = resolve_profile(args.profile)
    profile_values = read_env_file(profile_path)

    # Settings reads VISION_SERVICE_ENV_FILE during import. This script is run as
    # a fresh process, so setting it here keeps validation isolated from .env.
    os.environ["VISION_SERVICE_ENV_FILE"] = str(profile_path)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app.core.config import Settings, safe_configuration_snapshot

    errors: list[str] = []
    warnings: list[str] = []
    try:
        settings = Settings()
    except Exception as exc:
        report = build_report(
            profile_path=profile_path,
            profile_values=profile_values,
            settings=None,
            snapshot=None,
            errors=[f"settings_load_failed: {exc}"],
            warnings=[],
        )
        return finish(report, args.json_out, exit_code=1)

    snapshot = safe_configuration_snapshot(settings)
    errors.extend(settings.startup_safety_errors())

    profile_name = profile_path.stem
    validate_profile_boundaries(profile_name, profile_values, settings, errors, warnings)
    validate_model_paths(settings, errors, warnings)
    validate_sensitive_values(profile_values, warnings)

    report = build_report(
        profile_path=profile_path,
        profile_values=profile_values,
        settings=settings,
        snapshot=snapshot,
        errors=errors,
        warnings=warnings,
    )
    exit_code = 1 if errors or (args.strict and warnings) else 0
    return finish(report, args.json_out, exit_code=exit_code)


def resolve_profile(profile: str) -> Path:
    candidate = Path(profile)
    if candidate.exists():
        return candidate.resolve()
    if not profile.endswith(".env"):
        profile = f"{profile}.env"
    candidate = ROOT / "configs" / profile
    if not candidate.exists():
        raise SystemExit(f"profile not found: {candidate}")
    return candidate.resolve()


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def validate_profile_boundaries(
    profile_name: str,
    values: dict[str, str],
    settings: Any,
    errors: list[str],
    warnings: list[str],
) -> None:
    if profile_name == "safe_demo":
        if not settings.mock_camera_enabled:
            errors.append("safe_demo requires MOCK_CAMERA_ENABLED=true")
        if settings.default_rtsp_url:
            errors.append("safe_demo must not set DEFAULT_RTSP_URL")
        for key in REQUIRED_SAFE_FALSE:
            if truthy(values.get(key, "false")):
                errors.append(f"safe_demo requires {key}=false")
        if settings.enable_identity or settings.enable_identity_binding:
            errors.append("safe_demo requires identity and identity binding disabled")

    if profile_name == "production_candidate":
        if settings.mock_camera_enabled:
            warnings.append("production_candidate should use MOCK_CAMERA_ENABLED=false for real RTSP checks")
        if not settings.default_rtsp_url:
            warnings.append("production_candidate DEFAULT_RTSP_URL is empty; provide it via secure process env before real validation")
        for key in ("EVENT_DELIVERY_ENABLED", "EVENT_VLM_ENABLED", "ROBOT_ASSIST_ENABLED", "GO2_CONTROL_ENABLED"):
            if truthy(values.get(key, "false")):
                errors.append(f"production_candidate requires {key}=false until separately approved")

    if settings.pipeline_mode == "legacy":
        if not settings.fall_hint_in_detection_service or settings.fall_hint_worker_enabled:
            errors.append("PIPELINE_MODE=legacy requires FALL_HINT_IN_DETECTION_SERVICE=true and FALL_HINT_WORKER_ENABLED=false")

    if settings.event_delivery_enabled and settings.event_delivery_mode == "post":
        errors.append("real EVENT_DELIVERY_MODE=post is outside stable profile validation")


def validate_model_paths(settings: Any, errors: list[str], warnings: list[str]) -> None:
    values = asdict(settings)
    for env_key in MODEL_KEYS:
        attr = env_key.lower()
        value = values.get(attr)
        if not value:
            continue
        if env_key == "TEMPORAL_ONNX_MODEL_PATH" and not settings.enable_temporal:
            continue
        if env_key in {"YOLO_POSE_MODEL_PATH", "YOLO11_POSE_MODEL_PATH", "RTMPOSE_ONNX_MODEL_PATH"} and not settings.enable_pose:
            continue
        path = Path(str(value))
        resolved = path if path.is_absolute() else ROOT / path
        if not resolved.exists():
            errors.append(f"{env_key} file not found: {redact_path(resolved)}")
        elif resolved.is_file() and resolved.stat().st_size < 1024:
            warnings.append(f"{env_key} is unexpectedly small: {redact_path(resolved)}")


def validate_sensitive_values(values: dict[str, str], warnings: list[str]) -> None:
    for key, value in values.items():
        if not value:
            continue
        if is_sensitive_key(key):
            warnings.append(f"{key} is set in profile; avoid committing real credentials")


def build_report(
    *,
    profile_path: Path,
    profile_values: dict[str, str],
    settings: Any | None,
    snapshot: dict[str, Any] | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    models = []
    if settings is not None:
        for env_key in MODEL_KEYS:
            value = getattr(settings, env_key.lower(), None)
            if not value:
                continue
            path = Path(str(value))
            resolved = path if path.is_absolute() else ROOT / path
            item = {
                "env_key": env_key,
                "path": redact_path(resolved),
                "exists": resolved.exists(),
            }
            if resolved.exists() and resolved.is_file():
                item["size_bytes"] = resolved.stat().st_size
                item["sha256"] = sha256_file(resolved)
            models.append(item)

    public_profile_values = {
        key: ("<redacted>" if is_sensitive_key(key) and value else value)
        for key, value in profile_values.items()
    }
    return {
        "status": "PASS" if not errors else "REVISE",
        "profile_path": redact_path(profile_path),
        "profile_values": public_profile_values,
        "safe_configuration_snapshot": snapshot,
        "models": models,
        "errors": errors,
        "warnings": warnings,
    }


def finish(report: dict[str, Any], json_out: Path | None, exit_code: int) -> int:
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(text + "\n", encoding="utf-8")
    return exit_code


def truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return (
        any(word in upper for word in SENSITIVE_KEYWORDS)
        or upper.endswith("_KEY")
        or upper.endswith("_API_KEY")
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
