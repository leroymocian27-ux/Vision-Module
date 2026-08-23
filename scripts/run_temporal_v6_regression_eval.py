from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run baseline vs v6 temporal regression evaluation.")
    parser.add_argument("--manifest", required=True, help="Offline fall eval manifest with expected decisions.")
    parser.add_argument("--output-dir", default=str(ROOT / "evaluations" / "fall_temporal_v6"))
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--temporal-provider", default=None, choices=["mock", "shadow", "onnx_lstm"], help="Optional temporal model provider override.")
    parser.add_argument("--temporal-model-path", default=None, help="Optional TEMPORAL_ONNX_MODEL_PATH override.")
    parser.add_argument("--temporal-schema-path", default=None, help="Optional TEMPORAL_FEATURE_SCHEMA_PATH override.")
    args = parser.parse_args()
    temporal_config = temporal_runtime_config(
        provider=args.temporal_provider,
        model_path=args.temporal_model_path,
        schema_path=args.temporal_schema_path,
    )

    output_dir = Path(args.output_dir)
    baseline_dir = output_dir / "baseline_shadow"
    v6_dir = output_dir / "v6_decision"
    baseline = run_eval(
        manifest=Path(args.manifest),
        output_dir=baseline_dir,
        camera_id=args.camera_id,
        frame_stride=args.frame_stride,
        v6_decision=False,
        temporal_config=temporal_config,
    )
    v6 = run_eval(
        manifest=Path(args.manifest),
        output_dir=v6_dir,
        camera_id=args.camera_id,
        frame_stride=args.frame_stride,
        v6_decision=True,
        temporal_config=temporal_config,
    )
    comparison = build_comparison(baseline, v6, temporal_config=temporal_config)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "temporal_v6_regression_comparison.json"
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"comparison": str(comparison_path.resolve()), **comparison}, ensure_ascii=False, indent=2))
    return 0


def run_eval(
    *,
    manifest: Path,
    output_dir: Path,
    camera_id: str,
    frame_stride: int,
    v6_decision: bool,
    temporal_config: dict[str, str] | None = None,
) -> dict:
    env = os.environ.copy()
    env["FALL_V6_SCORING_ENABLED"] = "true"
    env["FALL_V6_DEBUG_PAYLOAD"] = "true"
    env["FALL_V6_DECISION_ENABLED"] = "true" if v6_decision else "false"
    env["YOLO_DEVICE"] = "cpu"
    env["YOLO_FALL_DEVICE"] = "cpu"
    env["YOLO_POSE_DEVICE"] = "cpu"
    env["YOLO11_POSE_DEVICE"] = "cpu"
    env["RTMPOSE_DEVICE"] = "cpu"
    env["TEMPORAL_ONNX_PROVIDERS"] = "CPUExecutionProvider"
    for key, value in (temporal_config or {}).items():
        env[key] = value
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "evaluate_fall_video_offline.py"),
        "--manifest",
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--camera-id",
        camera_id,
        "--frame-stride",
        str(frame_stride),
    ]
    subprocess.run(cmd, check=True, env=env, cwd=str(ROOT))
    summary_path = output_dir / "offline_fall_eval_summary.json"
    return json.loads(summary_path.read_text(encoding="utf-8"))


def build_comparison(baseline: dict, v6: dict, temporal_config: dict[str, str] | None = None) -> dict:
    baseline_metrics = baseline.get("event_metrics") or {}
    v6_metrics = v6.get("event_metrics") or {}
    baseline_confusion = baseline_metrics.get("confusion") or {}
    v6_confusion = v6_metrics.get("confusion") or {}
    per_video = build_per_video_comparison(baseline, v6)
    hard_negative_summary = build_hard_negative_summary(per_video)
    duplicate_alarm_videos = find_duplicate_alarm_videos(v6)
    return {
        "baseline_report": baseline.get("report"),
        "v6_report": v6.get("report"),
        "temporal_runtime_config": temporal_config or {},
        "baseline_event_metrics": baseline_metrics,
        "v6_event_metrics": v6_metrics,
        "per_video": per_video,
        "hard_negative_summary": hard_negative_summary,
        "v6_path_summary": (v6_metrics.get("v6") or {}).get("motion_path_distribution") or {},
        "duplicate_alarm_videos": duplicate_alarm_videos,
        "delta": {
            "false_positive": int(v6_confusion.get("false_positive") or 0)
            - int(baseline_confusion.get("false_positive") or 0),
            "false_negative": int(v6_confusion.get("false_negative") or 0)
            - int(baseline_confusion.get("false_negative") or 0),
            "true_positive": int(v6_confusion.get("true_positive") or 0)
            - int(baseline_confusion.get("true_positive") or 0),
            "true_negative": int(v6_confusion.get("true_negative") or 0)
            - int(baseline_confusion.get("true_negative") or 0),
        },
        "acceptance_hint": {
            "fp_not_worse": int(v6_confusion.get("false_positive") or 0)
            <= int(baseline_confusion.get("false_positive") or 0),
            "fn_not_worse": int(v6_confusion.get("false_negative") or 0)
            <= int(baseline_confusion.get("false_negative") or 0),
            "no_duplicate_alarm": not duplicate_alarm_videos,
            "slow_path_observed": int(((v6_metrics.get("v6") or {}).get("motion_path_distribution") or {}).get("slow_fall_path") or 0) > 0,
            "fast_path_observed": int(((v6_metrics.get("v6") or {}).get("motion_path_distribution") or {}).get("fast_fall_path") or 0) > 0,
        },
    }


def temporal_runtime_config(
    *,
    provider: str | None,
    model_path: str | None,
    schema_path: str | None,
) -> dict[str, str]:
    config: dict[str, str] = {}
    if provider:
        config["TEMPORAL_MODEL_PROVIDER"] = provider
    if model_path:
        config["TEMPORAL_ONNX_MODEL_PATH"] = model_path
    if schema_path:
        config["TEMPORAL_FEATURE_SCHEMA_PATH"] = schema_path
    return config


def build_per_video_comparison(baseline: dict, v6: dict) -> list[dict]:
    baseline_by_video = {str(item.get("video")): item for item in baseline.get("videos") or []}
    v6_by_video = {str(item.get("video")): item for item in v6.get("videos") or []}
    rows: list[dict] = []
    for video in sorted(set(baseline_by_video) | set(v6_by_video)):
        before = baseline_by_video.get(video) or {}
        after = v6_by_video.get(video) or {}
        expected_alarm = after.get("expected_alarm", before.get("expected_alarm"))
        baseline_confirmed = is_confirmed(before)
        v6_confirmed = is_confirmed(after)
        rows.append(
            {
                "video": video,
                "label": after.get("manifest_label", before.get("manifest_label")),
                "expected_alarm": expected_alarm,
                "hard_negative_type": after.get("hard_negative_type", before.get("hard_negative_type")),
                "scene_type": after.get("scene_type", before.get("scene_type")),
                "baseline_confirmed": baseline_confirmed,
                "v6_confirmed": v6_confirmed,
                "baseline_first_confirmed_timestamp_ms": before.get("first_confirmed_timestamp_ms"),
                "v6_first_confirmed_timestamp_ms": after.get("first_confirmed_timestamp_ms"),
                "baseline_alarm_frames": before.get("alarm_confirmed_frames"),
                "v6_alarm_frames": after.get("alarm_confirmed_frames"),
                "baseline_block_point": before.get("block_point"),
                "v6_block_point": after.get("block_point"),
                "outcome_delta": outcome_delta(expected_alarm, baseline_confirmed, v6_confirmed),
            }
        )
    return rows


def is_confirmed(summary: dict) -> bool:
    return int(summary.get("alarm_confirmed_frames") or 0) > 0 or int(summary.get("confirmed_frames") or 0) > 0


def outcome_delta(expected_alarm: object, baseline_confirmed: bool, v6_confirmed: bool) -> str:
    if baseline_confirmed == v6_confirmed:
        return "unchanged"
    if expected_alarm is True:
        return "recall_improved" if v6_confirmed else "recall_regressed"
    if expected_alarm is False:
        return "fp_regressed" if v6_confirmed else "fp_improved"
    return "changed"


def build_hard_negative_summary(per_video: list[dict]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in per_video:
        if row.get("expected_alarm") is not False:
            continue
        subtype = str(row.get("hard_negative_type") or "unknown")
        bucket = summary.setdefault(
            subtype,
            {
                "total": 0,
                "baseline_confirmed_fp": 0,
                "v6_confirmed_fp": 0,
                "fp_improved": 0,
                "fp_regressed": 0,
            },
        )
        bucket["total"] += 1
        if row.get("baseline_confirmed"):
            bucket["baseline_confirmed_fp"] += 1
        if row.get("v6_confirmed"):
            bucket["v6_confirmed_fp"] += 1
        if row.get("outcome_delta") == "fp_improved":
            bucket["fp_improved"] += 1
        if row.get("outcome_delta") == "fp_regressed":
            bucket["fp_regressed"] += 1
    return summary


def find_duplicate_alarm_videos(summary: dict) -> list[dict]:
    report = summary.get("report")
    if not report:
        return []
    output_dir = Path(report).parent
    duplicates: list[dict] = []
    for item in summary.get("videos") or []:
        video = str(item.get("video") or "")
        if not video:
            continue
        incident_ids = incident_ids_for_video(output_dir, video)
        if len(incident_ids) > 1:
            duplicates.append({"video": video, "incident_ids": incident_ids})
    return duplicates


def incident_ids_for_video(output_dir: Path, video: str) -> list[str]:
    frames_path = output_dir / f"offline_eval_{safe_slug(Path(video).stem)}_frames.jsonl"
    if not frames_path.exists():
        return []
    incident_ids: list[str] = []
    seen: set[str] = set()
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        incident_id = str(row.get("incident_id") or "").strip()
        if incident_id and incident_id not in seen:
            seen.add(incident_id)
            incident_ids.append(incident_id)
    return incident_ids


def safe_slug(value: str) -> str:
    keep = []
    for char in value:
        keep.append(char if char.isalnum() or char in {"-", "_"} else "_")
    return "".join(keep).strip("_") or "video"


if __name__ == "__main__":
    raise SystemExit(main())
