from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings


MEDIA_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov"}
EXCLUDED_PARTS = {".venv", ".pytest_cache", "__pycache__", "Ultralytics", "artifacts/releases"}
CRITICAL_FILES = (
    ".env",
    "models/post_fall_v2/efficientnet_b0/fall_candidate_efficientnet_b0.onnx",
    "app/post_fall_v2/binary_decision_aggregator.py",
    "app/post_fall_v2/fall_binary_classifier_service.py",
    "app/post_fall_v2/post_fall_runtime_service.py",
    "app/post_fall_v2/qwen_fall_analyzer.py",
    "app/events/qwen_keyframe.py",
)
PLAN_PATH = Path("artifacts/post_fall_v2/domain_evidence/p2_5c_target_camera_session_plan.csv")
SPLIT_MANIFEST_PATH = Path(
    "artifacts/post_fall_v2/domain_evidence/p2_5c_manifest_dry_run/20260811_004924/domain_split_manifest.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_excluded(path: Path) -> bool:
    text = path.as_posix()
    return any(part in text for part in EXCLUDED_PARTS)


def discover_media() -> list[dict]:
    records: list[dict] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS or is_excluded(path):
            continue
        relative = path.relative_to(ROOT).as_posix()
        qualification = "NOT_TARGET_CAMERA_VERIFIED"
        reason = "No target-camera manifest, metadata, annotation, or authorized source linkage found."
        if relative.startswith("private_test_assets/"):
            qualification = "GENERIC_REPLAY"
            reason = "Private replay asset; not linked to the current target camera."
        elif relative.startswith("tests/"):
            qualification = "TEST_FIXTURE"
            reason = "Automated-test fixture; not target-domain evidence."
        elif relative.startswith("artifacts/"):
            qualification = "GENERATED_ARTIFACT"
            reason = "Generated artifact; not an original target-camera recording."
        records.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
                "qualification": qualification,
                "reason": reason,
            }
        )
    return sorted(records, key=lambda item: item["path"])


def plan_inventory() -> dict:
    plan_path = ROOT / PLAN_PATH
    if not plan_path.is_file():
        return {"status": "MISSING_PLAN", "path": PLAN_PATH.as_posix()}
    with plan_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sources = []
    for row in rows:
        source_path = row.get("source_path") or ""
        resolved = (plan_path.parent / source_path).resolve()
        sources.append(
            {
                "session_id": row.get("session_id"),
                "split": row.get("split"),
                "scenario_label": row.get("scenario_label"),
                "source_type": row.get("source_type"),
                "source_path": source_path,
                "available": resolved.is_file(),
            }
        )
    split_manifest_path = ROOT / SPLIT_MANIFEST_PATH
    split_manifest = (
        json.loads(split_manifest_path.read_text(encoding="utf-8"))
        if split_manifest_path.is_file()
        else {}
    )
    return {
        "status": "PLAN_ONLY_NO_TARGET_RECORDINGS",
        "path": PLAN_PATH.as_posix(),
        "plan_file_sha256": sha256(plan_path),
        "split_manifest_path": SPLIT_MANIFEST_PATH.as_posix(),
        "split_manifest_sha256": split_manifest.get("sha256"),
        "session_count": len(rows),
        "calibration_sessions": sum(row.get("split") == "DOMAIN_CALIBRATION" for row in rows),
        "acceptance_sessions": sum(row.get("split") == "DOMAIN_ACCEPTANCE" for row in rows),
        "sessions": sources,
    }


def build_snapshot() -> dict:
    settings = Settings()
    return {
        "created_at": utc_now_iso(),
        "workspace": str(ROOT),
        "git_metadata": "NO_GIT_METADATA" if not (ROOT / ".git").exists() else "AVAILABLE",
        "python": sys.version,
        "platform": platform.platform(),
        "critical_file_sha256": {
            path: sha256(ROOT / path)
            for path in CRITICAL_FILES
            if (ROOT / path).is_file()
        },
        "runtime": {
            "pipeline_mode": settings.pipeline_mode,
            "post_fall_v2_enabled": settings.post_fall_v2_enabled,
            "sample_fps": settings.post_fall_v2_sample_fps,
            "binary_threshold": settings.post_fall_v2_binary_threshold,
            "window_size": settings.post_fall_v2_window_size,
            "min_positive_frames": settings.post_fall_v2_min_positive_frames,
            "min_consecutive_frames": settings.post_fall_v2_min_consecutive_frames,
            "candidate_min_ms": settings.post_fall_v2_candidate_min_ms,
            "recovery_min_ms": settings.post_fall_v2_recovery_min_ms,
            "cooldown_ms": settings.post_fall_v2_cooldown_ms,
            "binary_model_path": settings.post_fall_v2_binary_model_path,
            "binary_model_sha256": settings.post_fall_v2_binary_model_sha256,
            "qwen_enabled": settings.post_fall_v2_qwen_enabled,
            "qwen_provider": settings.post_fall_v2_qwen_provider,
            "qwen_model": settings.post_fall_v2_qwen_model,
            "qwen_endpoint": settings.post_fall_v2_qwen_base_url,
            "qwen_timeout_seconds": settings.post_fall_v2_qwen_timeout_seconds,
            "mock_camera_enabled": settings.mock_camera_enabled,
            "default_rtsp_configured": bool(settings.default_rtsp_url),
            "external_delivery_enabled": settings.event_delivery_enabled,
            "main_system_alert_enabled": settings.main_system_alert_enabled,
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze PFV2 finalization baseline and target-data inventory.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/post_fall_v2/finalization"),
    )
    args = parser.parse_args()
    output_dir = ROOT / args.output_dir
    plan = plan_inventory()
    media = discover_media()
    write_json(output_dir / "baseline_snapshot.json", build_snapshot())
    write_json(
        output_dir / "target_data_inventory.json",
        {
            "created_at": utc_now_iso(),
            "status": "TARGET_DATA_BLOCKED",
            "target_camera_qualified_media_count": 0,
            "qualified_media_rule": "Only current target-camera recordings or an authorized current target RTSP qualify.",
            "active_rtsp_configured": bool(Settings().default_rtsp_url),
            "plan": plan,
            "discovered_media": media,
            "blocked_reasons": [
                "No current target-camera recordings are present at the plan source paths.",
                "No active authorized target RTSP is configured in .env.",
                "Generic replay, test fixtures, and generated artifacts are not target-domain evidence.",
            ],
        },
    )
    print(json.dumps({"output_dir": str(output_dir), "media_count": len(media), "plan_status": plan["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
