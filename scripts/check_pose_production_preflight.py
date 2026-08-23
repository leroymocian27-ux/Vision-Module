from __future__ import annotations

import argparse
import importlib.util
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "evaluations" / "pose_production_preflight_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check hard preflight requirements for production pose optimization.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--labels", default="data/phase7_labels/phase7_video_labels.jsonl")
    parser.add_argument("--temporal-output-dir", default="data/temporal_sequences_pose_v1")
    parser.add_argument("--lstm-eval-split", default="test")
    parser.add_argument("--baseline-lstm-model", default="models/fall_lstm_v5.onnx")
    parser.add_argument("--baseline-lstm-schema", default="models/fall_lstm_v5_features.json")
    parser.add_argument("--baseline-lstm-threshold", default="models/fall_lstm_v5_threshold_calibration.json")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--skip-live-status",
        action="store_true",
        help="Skip live /status reachability check. Do not use for production promotion evidence.",
    )
    args = parser.parse_args()

    report = build_preflight_report(
        base_url=args.base_url,
        camera_id=args.camera_id,
        device=args.device,
        duration_seconds=args.duration_seconds,
        labels=Path(args.labels),
        temporal_output_dir=Path(args.temporal_output_dir),
        lstm_eval_split=args.lstm_eval_split,
        baseline_lstm_model=Path(args.baseline_lstm_model),
        baseline_lstm_schema=Path(args.baseline_lstm_schema),
        baseline_lstm_threshold=Path(args.baseline_lstm_threshold),
        env_file=Path(args.env_file),
        skip_live_status=args.skip_live_status,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["passed"] else 1


def build_preflight_report(
    *,
    base_url: str,
    camera_id: str,
    device: str,
    duration_seconds: float,
    labels: Path,
    temporal_output_dir: Path,
    lstm_eval_split: str,
    baseline_lstm_model: Path,
    baseline_lstm_schema: Path,
    baseline_lstm_threshold: Path,
    env_file: Path = Path(".env"),
    skip_live_status: bool = False,
) -> dict[str, Any]:
    env, _ = load_env(env_file)
    expected_pose_provider = str(env.get("POSE_PROVIDER") or "disabled_placeholder").strip()
    expected_pose_model = active_pose_model_path(env, expected_pose_provider)
    checks = {
        "python_dependencies": check_python_dependencies(),
        "production_parameters": check_production_parameters(
            duration_seconds=duration_seconds,
            temporal_output_dir=temporal_output_dir,
            lstm_eval_split=lstm_eval_split,
        ),
        "pose_runtime_config": check_pose_runtime_config(env_file=env_file, requested_device=device),
        "cuda_device": check_cuda_device(device),
        "required_files": check_required_files(
            {
                "labels": labels,
                "baseline_lstm_model": baseline_lstm_model,
                "baseline_lstm_schema": baseline_lstm_schema,
                "baseline_lstm_threshold": baseline_lstm_threshold,
            }
        ),
        "live_status": check_live_status(
            base_url=base_url,
            camera_id=camera_id,
            expected_pose_provider=expected_pose_provider,
            expected_pose_model=expected_pose_model,
            skip=skip_live_status,
        ),
    }
    blockers = []
    warnings = []
    for name, check in checks.items():
        for blocker in check.get("blockers", []):
            blockers.append({"gate": name, "blocker": blocker})
        for warning in check.get("warnings", []):
            warnings.append({"gate": name, "warning": warning})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "passed": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "next_action": next_action(blockers, warnings),
        },
        "checks": checks,
    }


def check_python_dependencies() -> dict[str, Any]:
    required = ("onnx", "onnxruntime", "torch")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    return {
        "passed": not missing,
        "blockers": [f"missing_python_dependency:{name}" for name in missing],
        "warnings": [],
        "metrics": {"required": list(required), "missing": missing},
    }


def check_production_parameters(
    *,
    duration_seconds: float,
    temporal_output_dir: Path,
    lstm_eval_split: str,
) -> dict[str, Any]:
    blockers = []
    normalized_split = str(lstm_eval_split or "").strip().lower()
    temporal_name = str(temporal_output_dir).replace("\\", "/").lower()
    dev_markers = ("dev", "smoke", "local", "mock", "replay")
    if duration_seconds < 120.0:
        blockers.append("runtime_duration_below_120s")
    if normalized_split != "test":
        blockers.append("lstm_eval_split_is_not_test")
    if any(marker in temporal_name for marker in dev_markers):
        blockers.append("temporal_output_dir_looks_like_dev_evidence")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "warnings": [],
        "metrics": {
            "duration_seconds": duration_seconds,
            "temporal_output_dir": str(temporal_output_dir),
            "lstm_eval_split": lstm_eval_split,
        },
    }


def check_cuda_device(device: str) -> dict[str, Any]:
    normalized = str(device or "").strip().lower()
    blockers = []
    warnings = []
    available = None
    device_count = None
    if not normalized.startswith("cuda"):
        blockers.append("production_device_is_not_cuda")
    try:
        import torch

        available = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if available else 0
    except Exception as exc:
        blockers.append("torch_cuda_check_failed")
        warnings.append(str(exc))
    if normalized.startswith("cuda") and available is False:
        blockers.append("cuda_unavailable")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "metrics": {"requested_device": device, "cuda_available": available, "cuda_device_count": device_count},
    }


def check_required_files(paths: dict[str, Path]) -> dict[str, Any]:
    missing = []
    resolved = {}
    for name, raw_path in paths.items():
        path = raw_path if raw_path.is_absolute() else ROOT / raw_path
        resolved[name] = str(path)
        if not path.exists():
            missing.append(name)
    return {
        "passed": not missing,
        "blockers": [f"required_file_missing:{name}" for name in missing],
        "warnings": [],
        "metrics": {"paths": resolved, "missing": missing},
    }


def check_pose_runtime_config(*, env_file: Path, requested_device: str) -> dict[str, Any]:
    env, missing = load_env(env_file)
    blockers: list[str] = []
    warnings: list[str] = []
    if missing:
        blockers.append("pose_env_file_missing")
    enable_pose = env_bool(env, "ENABLE_POSE", False)
    provider = str(env.get("POSE_PROVIDER") or "disabled_placeholder").strip()
    active_model = active_pose_model_path(env, provider)
    active_device = active_pose_device(env, provider)
    requested = str(requested_device or "").strip().lower()
    active = str(active_device or "").strip().lower()
    if not enable_pose:
        blockers.append("pose_disabled_for_production_preflight")
    if provider == "disabled_placeholder":
        blockers.append("pose_provider_disabled_for_production_preflight")
    if not active_model:
        blockers.append("active_pose_model_missing")
    else:
        model_path = resolve_path(Path(active_model))
        if not model_path.exists():
            blockers.append("active_pose_model_file_missing")
    if not active.startswith("cuda"):
        blockers.append("active_pose_device_is_not_cuda")
    elif requested.startswith("cuda") and active != requested:
        blockers.append("active_pose_device_does_not_match_requested_device")
    if provider in {"rtmpose_onnx", "mmpose"}:
        warnings.append("rtmpose_provider_requires_separate_quality_metrics")
    return {
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "warnings": dedupe(warnings),
        "metrics": {
            "env_file": str(env_file),
            "enable_pose": enable_pose,
            "pose_provider": provider,
            "active_pose_model": active_model,
            "active_pose_device": active_device,
            "requested_device": requested_device,
        },
    }


def check_live_status(
    *,
    base_url: str,
    camera_id: str,
    expected_pose_provider: str | None = None,
    expected_pose_model: str | None = None,
    skip: bool = False,
) -> dict[str, Any]:
    if skip:
        return {
            "passed": True,
            "blockers": [],
            "warnings": ["live_status_check_skipped"],
            "metrics": {"base_url": base_url, "camera_id": camera_id, "skipped": True},
        }
    attempts = status_url_candidates(base_url=base_url, camera_id=camera_id)
    last_failure: dict[str, Any] | None = None
    for url in attempts:
        try:
            request = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=3.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return validate_live_status_payload(
                payload,
                url=url,
                expected_pose_provider=expected_pose_provider,
                expected_pose_model=expected_pose_model,
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                last_failure = failed_live_status(url, f"http_{exc.code}")
                continue
            return failed_live_status(url, f"http_{exc.code}")
        except Exception as exc:
            return failed_live_status(url, str(exc))
    assert last_failure is not None
    return last_failure


def validate_live_status_payload(
    payload: dict[str, Any],
    *,
    url: str,
    expected_pose_provider: str | None = None,
    expected_pose_model: str | None = None,
) -> dict[str, Any]:
    pose = payload.get("pose") if isinstance(payload.get("pose"), dict) else {}
    latest = payload.get("latest_result") if isinstance(payload.get("latest_result"), dict) else {}
    pose_debug = latest.get("pose_debug") if isinstance(latest.get("pose_debug"), dict) else {}
    has_pose = bool(pose)
    blockers: list[str] = []
    warnings: list[str] = []
    if not has_pose:
        blockers.append("live_status_pose_section_missing")
    live_pose_enabled = pose.get("pose_enabled")
    live_pose_provider = _live_pose_provider(pose, latest)
    live_pose_model = _live_pose_model_path(pose, latest, pose_debug)
    live_pose_model_source = "live_status" if live_pose_model else None
    if has_pose and live_pose_enabled is not True:
        blockers.append("live_status_pose_disabled")
    if expected_pose_provider and live_pose_provider and live_pose_provider != expected_pose_provider:
        blockers.append("live_status_pose_provider_mismatch")
    if expected_pose_provider and not live_pose_provider:
        blockers.append("live_status_pose_provider_missing")
    if expected_pose_model:
        if not live_pose_model:
            warnings.append("live_status_pose_model_path_unobservable_using_expected_config")
            live_pose_model = expected_pose_model
            live_pose_model_source = "expected_config_fallback"
        elif not pose_model_paths_match(live_pose_model, expected_pose_model):
            blockers.append("live_status_pose_model_path_mismatch")
    return {
        "passed": not blockers,
        "blockers": dedupe(blockers),
        "warnings": dedupe(warnings),
        "metrics": {
            "url": url,
            "http_status": 200,
            "pose_section_present": has_pose,
            "live_pose_enabled": live_pose_enabled,
            "live_pose_provider": live_pose_provider or None,
            "expected_pose_provider": expected_pose_provider,
            "live_pose_model_path": live_pose_model or None,
            "live_pose_model_path_source": live_pose_model_source,
            "expected_pose_model": expected_pose_model,
        },
    }


def failed_live_status(url: str, reason: str) -> dict[str, Any]:
    return {
        "passed": False,
        "blockers": ["live_status_unreachable"],
        "warnings": [],
        "metrics": {"url": url, "error": reason},
    }


def status_url(*, base_url: str, camera_id: str) -> str:
    query = urllib.parse.urlencode({"camera_id": camera_id})
    return f"{base_url.rstrip('/')}/status?{query}"


def status_url_candidates(*, base_url: str, camera_id: str) -> list[str]:
    primary = status_url(base_url=base_url, camera_id=camera_id)
    candidates = [primary]
    trimmed = base_url.rstrip("/")
    if trimmed.lower().endswith("/api/v1"):
        root_base = trimmed[:-7].rstrip("/")
        if root_base:
            candidates.append(status_url(base_url=root_base, camera_id=camera_id))
    return dedupe(candidates)


def next_action(blockers: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
    names = {item["blocker"] for item in blockers}
    if not blockers:
        if warnings:
            return "preflight passed with warnings; do not use skipped live-status checks as production evidence"
        return "preflight passed; run production runtime/provider/data/LSTM gates"
    if any(name.startswith("missing_python_dependency") for name in names):
        return "install missing ONNX/Torch dependencies before production pose optimization"
    if "production_device_is_not_cuda" in names or "cuda_unavailable" in names:
        return "run production gates on a CUDA-capable host; CPU evidence is development-only"
    if (
        "pose_env_file_missing" in names
        or "pose_disabled_for_production_preflight" in names
        or "pose_provider_disabled_for_production_preflight" in names
        or "active_pose_model_missing" in names
        or "active_pose_model_file_missing" in names
        or "active_pose_device_is_not_cuda" in names
        or "active_pose_device_does_not_match_requested_device" in names
    ):
        return "fix active pose provider/model/device settings in .env before production pose optimization"
    if (
        "runtime_duration_below_120s" in names
        or "lstm_eval_split_is_not_test" in names
        or "temporal_output_dir_looks_like_dev_evidence" in names
    ):
        return "use production parameters: >=120s runtime probe, test split evaluation, and non-dev temporal output paths"
    if "live_status_unreachable" in names or "live_status_pose_section_missing" in names:
        return "start the live FastAPI service and verify /status exposes pose diagnostics"
    if any(name.startswith("required_file_missing") for name in names):
        return "restore required labels and baseline LSTM artifacts before running production gates"
    return "fix production preflight blockers before running pose optimization pipeline"


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
        key, raw_value = line.split("=", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values, False


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def env_bool(env: dict[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


def normalize_path_text(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\\", "/").strip()
    root = str(ROOT).replace("\\", "/").rstrip("/")
    if text.lower().startswith(root.lower() + "/"):
        text = text[len(root) + 1 :]
    return text.lower()


def pose_model_paths_match(live_value: str | None, expected_value: str | None) -> bool:
    live = normalize_path_text(live_value)
    expected = normalize_path_text(expected_value)
    if not live or not expected:
        return live == expected
    if live == expected:
        return True
    return live.endswith("/" + expected) or live.rsplit("/", 1)[-1] == expected


def _live_pose_provider(pose: dict[str, Any], latest: dict[str, Any]) -> str:
    direct = str(pose.get("pose_provider") or "").strip()
    if direct:
        return direct
    debug = latest.get("pose_debug") if isinstance(latest.get("pose_debug"), dict) else {}
    return str(debug.get("pose_provider") or "").strip()


def _live_pose_model_path(pose: dict[str, Any], latest: dict[str, Any], pose_debug: dict[str, Any]) -> str:
    for candidate in (
        pose.get("pose_model_path"),
        pose_debug.get("pose_model_path"),
        pose_debug.get("model_path"),
        latest.get("pose_model_path"),
    ):
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
