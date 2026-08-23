from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_deployment_guard_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard production pose deployment against unproven or brittle runtime settings.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--evidence-package", default="evaluations/pose_evidence_package_check_20260705.json")
    parser.add_argument("--mode", choices=("production", "development"), default="production")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--allow-risky-tracking-delta",
        action="store_true",
        help="Allow POSE_MAX_TRACKING_FRAME_DELTA > 2. Use only with explicit multi-person mismatch risk sign-off.",
    )
    args = parser.parse_args()

    report = build_deployment_guard_report(
        env_file=Path(args.env_file),
        evidence_package_path=Path(args.evidence_package),
        mode=args.mode,
        allow_risky_tracking_delta=args.allow_risky_tracking_delta,
    )
    output = resolve_path(Path(args.output))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["deployment_allowed"] else 1


def build_deployment_guard_report(
    *,
    env_file: Path,
    evidence_package_path: Path,
    mode: str = "production",
    allow_risky_tracking_delta: bool = False,
) -> dict[str, Any]:
    env, env_missing = load_env(env_file)
    return build_deployment_guard_report_from_env(
        env=env,
        env_path=env_file,
        env_missing=env_missing,
        evidence_package_path=evidence_package_path,
        mode=mode,
        allow_risky_tracking_delta=allow_risky_tracking_delta,
    )


def build_deployment_guard_report_from_env(
    *,
    env: dict[str, str],
    env_path: Path | str = "env",
    env_missing: bool = False,
    evidence_package_path: Path,
    mode: str = "production",
    allow_risky_tracking_delta: bool = False,
) -> dict[str, Any]:
    evidence = load_json(evidence_package_path)
    checks = {
        "env_file": check_env_file(env_path, env_missing),
        "pose_runtime_config": check_pose_runtime_config(env, mode=mode, allow_risky_tracking_delta=allow_risky_tracking_delta),
        "evidence_package": check_evidence_package(evidence_package_path, evidence, env=env, mode=mode),
    }
    blockers = [
        {"gate": name, "blockers": check["blockers"]}
        for name, check in checks.items()
        if check["blockers"]
    ]
    warnings = [
        {"gate": name, "warnings": check["warnings"]}
        for name, check in checks.items()
        if check["warnings"]
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "mode": mode,
            "deployment_allowed": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "next_action": next_action(blockers, warnings),
        },
        "checks": checks,
    }


def check_env_file(path: Path | str, missing: bool) -> dict[str, Any]:
    return {
        "path": str(path),
        "passed": not missing,
        "blockers": ["env_file_missing"] if missing else [],
        "warnings": [],
        "metrics": {},
    }


def check_pose_runtime_config(
    env: dict[str, str],
    *,
    mode: str,
    allow_risky_tracking_delta: bool,
) -> dict[str, Any]:
    enable_pose = env_bool(env, "ENABLE_POSE", False)
    provider = env.get("POSE_PROVIDER", "disabled_placeholder")
    active_device = active_pose_device(env, provider)
    blockers: list[str] = []
    warnings: list[str] = []
    if mode == "production" and enable_pose:
        if provider == "disabled_placeholder":
            blockers.append("pose_enabled_with_disabled_provider")
        if not str(active_device or "").lower().startswith("cuda"):
            blockers.append("active_pose_device_is_not_cuda")
    pose_worker_fps = env_float(env, "POSE_WORKER_FPS", 3.0)
    pose_fps = env_float(env, "POSE_FPS", 3.0)
    ttl_ms = env_int(env, "POSE_RESULT_TTL_MS", 800)
    frame_age_ms = env_int(env, "POSE_MAX_FRAME_AGE_MS", 800)
    tracking_delta = env_int(env, "POSE_MAX_TRACKING_FRAME_DELTA", 2)
    lock_wait_ms = env_int(env, "POSE_INFERENCE_LOCK_WAIT_MS", 160)
    if enable_pose:
        if pose_worker_fps < 2.0:
            blockers.append("pose_worker_fps_below_2")
        elif pose_worker_fps < 3.0:
            warnings.append("pose_worker_fps_below_recommended_3")
        if pose_fps < 2.0:
            blockers.append("pose_fps_below_2")
        if ttl_ms < 700:
            blockers.append("pose_result_ttl_ms_below_700")
        if frame_age_ms < 700:
            blockers.append("pose_max_frame_age_ms_below_700")
        if lock_wait_ms < 80:
            blockers.append("pose_inference_lock_wait_ms_below_80")
        if tracking_delta > 2 and not allow_risky_tracking_delta:
            blockers.append("pose_tracking_delta_above_2_requires_risk_signoff")
        if env_bool(env, "POSE_FALLBACK_TO_DETECTION", False):
            warnings.append("pose_fallback_to_detection_enabled")
    return {
        "path": "env",
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "warnings": dedupe(warnings),
        "metrics": {
            "enable_pose": enable_pose,
            "pose_provider": provider,
            "active_pose_device": active_device,
            "pose_worker_fps": pose_worker_fps,
            "pose_fps": pose_fps,
            "pose_result_ttl_ms": ttl_ms,
            "pose_max_frame_age_ms": frame_age_ms,
            "pose_max_tracking_frame_delta": tracking_delta,
            "pose_inference_lock_wait_ms": lock_wait_ms,
        },
    }


def check_evidence_package(path: Path, payload: dict[str, Any], *, env: dict[str, str], mode: str) -> dict[str, Any]:
    enable_pose = env_bool(env, "ENABLE_POSE", False)
    if not payload:
        blockers = ["evidence_package_missing"] if mode == "production" and enable_pose else []
        return {
            "path": str(path),
            "passed": not blockers,
            "blockers": blockers,
            "warnings": [],
            "metrics": {"handoff_ready": None},
        }
    summary = as_dict(payload.get("summary"))
    handoff_ready = summary.get("handoff_ready") is True
    blockers = []
    warnings = []
    if mode == "production" and enable_pose and not handoff_ready:
        blockers.append("pose_enabled_without_handoff_ready_evidence")
    expected_model = evidence_pose_model(payload)
    expected_provider = evidence_pose_provider(payload)
    active_provider = env.get("POSE_PROVIDER", "disabled_placeholder")
    active_model = active_pose_model_path(env, env.get("POSE_PROVIDER", "disabled_placeholder"))
    if mode == "production" and enable_pose and handoff_ready:
        if not expected_provider:
            blockers.append("pose_provider_handoff_evidence_missing")
        elif normalize_provider_text(active_provider) != normalize_provider_text(expected_provider):
            blockers.append("pose_provider_does_not_match_handoff_evidence")
        if not expected_model:
            blockers.append("pose_model_handoff_evidence_missing")
        elif normalize_path_text(active_model) != normalize_path_text(expected_model):
            blockers.append("pose_model_does_not_match_handoff_evidence")
    elif mode == "production" and enable_pose:
        if expected_provider and normalize_provider_text(active_provider) != normalize_provider_text(expected_provider):
            warnings.append("pose_provider_differs_from_current_evidence")
        if expected_model and normalize_path_text(active_model) != normalize_path_text(expected_model):
            warnings.append("pose_model_differs_from_current_evidence")
    if summary.get("blockers"):
        warnings.append("evidence_package_has_blockers")
    return {
        "path": str(path),
        "passed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {
            "handoff_ready": handoff_ready,
            "blocker_gate_count": len(summary.get("blockers") or []),
            "next_action": summary.get("next_action"),
            "active_pose_provider": active_provider,
            "evidence_pose_provider": expected_provider,
            "active_pose_model": active_model,
            "evidence_pose_model": expected_model,
        },
    }


def active_pose_device(env: dict[str, str], provider: str) -> str | None:
    provider = str(provider or "").strip().lower()
    if provider in {"yolo11_legacy", "branch4_legacy"}:
        return env.get("YOLO11_POSE_DEVICE") or env.get("YOLO_POSE_DEVICE")
    if provider == "yolo":
        return env.get("YOLO_POSE_DEVICE")
    if provider in {"rtmpose_onnx", "mmpose"}:
        return env.get("RTMPOSE_DEVICE")
    return env.get("YOLO11_POSE_DEVICE") or env.get("YOLO_POSE_DEVICE") or env.get("RTMPOSE_DEVICE")


def active_pose_model_path(env: dict[str, str], provider: str) -> str | None:
    provider = str(provider or "").strip().lower()
    if provider in {"yolo11_legacy", "branch4_legacy"}:
        return env.get("YOLO11_POSE_MODEL_PATH")
    if provider == "yolo":
        return env.get("YOLO_POSE_MODEL_PATH")
    if provider == "rtmpose_onnx":
        return env.get("RTMPOSE_ONNX_MODEL_PATH")
    if provider == "mmpose":
        return env.get("RTMPOSE_CHECKPOINT_PATH")
    return env.get("YOLO11_POSE_MODEL_PATH") or env.get("YOLO_POSE_MODEL_PATH") or env.get("RTMPOSE_ONNX_MODEL_PATH")


def evidence_pose_model(payload: dict[str, Any]) -> str | None:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    model_quality = checks.get("model_quality") if isinstance(checks.get("model_quality"), dict) else {}
    metrics = model_quality.get("metrics") if isinstance(model_quality.get("metrics"), dict) else {}
    value = metrics.get("configured_model") or metrics.get("candidate_model")
    return str(value) if value else None


def evidence_pose_provider(payload: dict[str, Any]) -> str | None:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    readiness = checks.get("readiness") if isinstance(checks.get("readiness"), dict) else {}
    readiness_metrics = readiness.get("metrics") if isinstance(readiness.get("metrics"), dict) else {}
    consistency = (
        readiness_metrics.get("evidence_consistency")
        if isinstance(readiness_metrics.get("evidence_consistency"), dict)
        else {}
    )
    value = consistency.get("runtime_pose_provider")
    return str(value) if value else None


def normalize_provider_text(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_path_text(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\\", "/").strip()
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text.lower()


def next_action(blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> str:
    if not blockers:
        if warnings:
            return "deployment guard passed with warnings; review pose fallback and evidence notes before rollout"
        return "deployment guard passed"
    gates = [item.get("gate") for item in blockers]
    if "env_file" in gates:
        return "provide the exact production .env file before pose deployment"
    if "pose_runtime_config" in gates:
        return "fix brittle or non-CUDA pose runtime settings before production deployment"
    if "evidence_package" in gates:
        return "run the production pose optimization pipeline until evidence_package.handoff_ready=true"
    return "fix deployment guard blockers before starting the production service"


def load_env(path: Path) -> tuple[dict[str, str], bool]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}, True
    values: dict[str, str] = {}
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
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
        if key:
            values[key] = value
    return values, False


def load_json(path: Path) -> dict[str, Any]:
    resolved = resolve_path(path)
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def env_bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(env: dict[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def env_float(env: dict[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
