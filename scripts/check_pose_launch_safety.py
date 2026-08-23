from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_launch_safety_check_20260705.json"
DEFAULT_LAUNCH_SCRIPTS = (
    "scripts/start_current_camera.py",
    "scripts/launch_current_camera_background.py",
    "scripts/start_phase5_test.py",
    "scripts/debug_start_phase513c.py",
    "scripts/debug_restart_matrix.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit service launch scripts for unsafe pose deployment bypasses.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--script", action="append", dest="scripts", help="Launch script to audit. May be repeated.")
    args = parser.parse_args()

    report = build_launch_safety_report([Path(item) for item in args.scripts] if args.scripts else None)
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["launch_safety_passed"] else 1


def build_launch_safety_report(scripts: list[Path] | None = None) -> dict[str, Any]:
    script_paths = scripts or [Path(item) for item in DEFAULT_LAUNCH_SCRIPTS]
    checks = [check_launch_script(path) for path in script_paths]
    blockers = [
        {"script": item["path"], "blockers": item["blockers"]}
        for item in checks
        if item["blockers"]
    ]
    warnings = [
        {"script": item["path"], "warnings": item["warnings"]}
        for item in checks
        if item["warnings"]
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "launch_safety_passed": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "next_action": next_action(blockers, warnings),
        },
        "checks": checks,
    }


def check_launch_script(path: Path) -> dict[str, Any]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {
            "path": str(path),
            "passed": False,
            "blockers": ["launch_script_missing"],
            "warnings": [],
            "metrics": {},
        }
    text = resolved.read_text(encoding="utf-8")
    blockers: list[str] = []
    warnings: list[str] = []
    metrics = script_metrics(text, path=resolved)
    if path.name == "start_current_camera.py":
        if "_should_run_pose_deployment_guard" not in text or "deployment_allowed" not in text:
            blockers.append("start_current_camera_missing_pose_deployment_guard")
    if path.name == "launch_current_camera_background.py":
        if "scripts/start_current_camera.py" not in text.replace("\\", "/"):
            blockers.append("background_launcher_does_not_delegate_to_guarded_start_current_camera")
    app_guard_available = app_main_has_pose_deployment_guard()
    metrics["app_main_pose_deployment_guard"] = app_guard_available
    if metrics["direct_vision_uvicorn"] and metrics["enable_pose_true"] and metrics["main_alert_true"] and metrics["pose_deployment_guard_disabled"]:
        blockers.append("direct_pose_alert_launch_disables_app_deployment_guard")
    elif metrics["direct_vision_uvicorn"] and metrics["enable_pose_true"] and metrics["main_alert_true"]:
        if "check_pose_deployment_guard" not in text and "_write_pose_deployment_guard" not in text:
            if app_guard_available:
                warnings.append("direct_pose_alert_launch_relies_on_app_lifespan_guard")
            else:
                blockers.append("direct_pose_alert_launch_without_deployment_guard")
    if metrics["brittle_pose_ttl"]:
        blockers.append("brittle_pose_ttl_or_frame_age_default")
    if metrics["pose_worker_fps_below_3"]:
        warnings.append("pose_worker_fps_below_recommended_3")
    if metrics["direct_vision_uvicorn"] and not metrics["main_alert_true"] and metrics["enable_pose_true"]:
        warnings.append("direct_pose_launch_without_main_alert_not_production_evidence")
    if metrics["debug_script"] and metrics["enable_pose_true"]:
        warnings.append("debug_pose_launch_not_production_evidence")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "warnings": dedupe(warnings),
        "metrics": metrics,
    }


def script_metrics(text: str, *, path: Path) -> dict[str, Any]:
    normalized = text.replace("\\", "/")
    path_text = str(path).replace("\\", "/").lower()
    return {
        "direct_vision_uvicorn": '"uvicorn"' in text and '"app.main:app"' in text,
        "delegates_to_start_current_camera": "scripts/start_current_camera.py" in normalized,
        "enable_pose_true": '"ENABLE_POSE": "true"' in text or "'ENABLE_POSE': 'true'" in text,
        "main_alert_true": '"MAIN_SYSTEM_ALERT_ENABLED": "true"' in text or "'MAIN_SYSTEM_ALERT_ENABLED': 'true'" in text,
        "pose_deployment_guard_disabled": (
            '"POSE_DEPLOYMENT_GUARD_ENABLED": "false"' in text
            or "'POSE_DEPLOYMENT_GUARD_ENABLED': 'false'" in text
        ),
        "brittle_pose_ttl": (
            '"POSE_RESULT_TTL_MS": "500"' in text
            or '"POSE_MAX_FRAME_AGE_MS": "500"' in text
            or "'POSE_RESULT_TTL_MS': '500'" in text
            or "'POSE_MAX_FRAME_AGE_MS': '500'" in text
        ),
        "pose_worker_fps_below_3": (
            '"POSE_WORKER_FPS": "1"' in text
            or '"POSE_WORKER_FPS": "2"' in text
            or "'POSE_WORKER_FPS': '1'" in text
            or "'POSE_WORKER_FPS': '2'" in text
        ),
        "debug_script": "debug_" in path_text,
    }


def app_main_has_pose_deployment_guard() -> bool:
    app_main = ROOT / "app" / "main.py"
    if not app_main.exists():
        return False
    text = app_main.read_text(encoding="utf-8")
    required = (
        "_enforce_pose_deployment_guard",
        "build_deployment_guard_report_from_env",
        "deployment_allowed",
    )
    return all(item in text for item in required)


def next_action(blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    if not blockers:
        if warnings:
            return "launch safety passed with debug warnings; do not treat debug launch output as production evidence"
        return "launch safety passed"
    return "fix blocked launch scripts before treating pose-enabled service startup as production-safe"


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
