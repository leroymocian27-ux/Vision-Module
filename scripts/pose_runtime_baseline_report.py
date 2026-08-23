from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

POSE_ENV_KEYS = [
    "ENABLE_POSE",
    "POSE_PROVIDER",
    "POSE_FPS",
    "POSE_WORKER_FPS",
    "POSE_RESULT_TTL_MS",
    "POSE_MAX_TRACKING_FRAME_DELTA",
    "POSE_MAX_FRAME_AGE_MS",
    "POSE_SKIP_WHEN_INFERENCE_BUSY",
    "YOLO_POSE_MODEL_PATH",
    "YOLO11_POSE_MODEL_PATH",
    "YOLO_POSE_CONFIDENCE",
    "YOLO_POSE_IMGSZ",
    "YOLO_POSE_DEVICE",
]

MODEL_ENV_KEYS = [
    "YOLO_MODEL_PATH",
    "YOLO_FALL_MODEL_PATH",
    "TEMPORAL_ONNX_MODEL_PATH",
    "TEMPORAL_FEATURE_SCHEMA_PATH",
]

POSE_FEATURE_NAMES = {
    "pose_available",
    "pose_confidence",
    "torso_angle_norm",
    "head_height_ratio_filled",
    "hip_height_ratio_filled",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the current pose runtime baseline report.")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--pose-metrics", default="models/pose_yolo_batch001_003_yolo11s_metrics.json")
    parser.add_argument("--e2e", default="evaluations/phase9_e2e_acceptance_001.json")
    parser.add_argument("--temporal-dir", default="data/temporal_sequences_phase6d")
    parser.add_argument("--output-json", default="evaluations/pose_runtime_baseline_20260705.json")
    parser.add_argument("--output-md", default="docs/pose_runtime_baseline_20260705.md")
    args = parser.parse_args()

    env = _read_env(ROOT / args.env)
    pose_metrics = _load_json(ROOT / args.pose_metrics)
    e2e = _load_json(ROOT / args.e2e)
    temporal = _scan_temporal_sequences(ROOT / args.temporal_dir)
    model_assets = _model_assets(env)

    baseline = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ROOT),
        "pose_config": {key: env.get(key) for key in POSE_ENV_KEYS if key in env},
        "model_config": {key: env.get(key) for key in MODEL_ENV_KEYS if key in env},
        "model_assets": model_assets,
        "pose_model_metrics": _pose_metric_summary(pose_metrics),
        "e2e_runtime": _e2e_summary(e2e),
        "temporal_pose_data": temporal,
        "diagnosis": _diagnosis(pose_metrics, e2e, temporal, env),
        "next_gates": {
            "pose_valid_rate_target": 0.70,
            "frontend_visible_skeleton_ratio_target": 0.60,
            "pose_track_mismatch_rate_max": 0.05,
            "temporal_pose_rows_required": True,
        },
    }

    output_json = ROOT / args.output_json
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")

    output_md = ROOT / args.output_md
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(_render_markdown(baseline), encoding="utf-8")

    print(json.dumps({"json": str(output_json), "md": str(output_md)}, ensure_ascii=False, indent=2))
    return 0


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"missing": str(path)}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _model_assets(env: dict[str, str]) -> dict[str, dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for key in [*POSE_ENV_KEYS, *MODEL_ENV_KEYS]:
        if not key.endswith("_MODEL_PATH") and key != "TEMPORAL_ONNX_MODEL_PATH":
            continue
        value = env.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = ROOT / path
        assets[key] = _file_fingerprint(path)
    return assets


def _file_fingerprint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _pose_metric_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    baseline = metrics.get("baseline") if isinstance(metrics.get("baseline"), dict) else {}
    candidate = metrics.get("candidate") if isinstance(metrics.get("candidate"), dict) else {}
    delta = metrics.get("delta") if isinstance(metrics.get("delta"), dict) else {}
    return {
        "baseline_model": metrics.get("baseline_model"),
        "candidate_model": metrics.get("candidate_model"),
        "baseline_pose_map50_95": baseline.get("pose_map50_95"),
        "candidate_pose_map50_95": candidate.get("pose_map50_95"),
        "delta_pose_map50_95": delta.get("pose_map50_95"),
        "baseline_inference_ms": (baseline.get("speed_ms") or {}).get("inference"),
        "candidate_inference_ms": (candidate.get("speed_ms") or {}).get("inference"),
    }


def _e2e_summary(e2e: dict[str, Any]) -> dict[str, Any]:
    ratios = e2e.get("ratios") if isinstance(e2e.get("ratios"), dict) else {}
    last_pose = e2e.get("last_pose") if isinstance(e2e.get("last_pose"), dict) else {}
    return {
        "samples": e2e.get("samples"),
        "duration_seconds": e2e.get("duration_seconds"),
        "pose_valid": ratios.get("pose_valid"),
        "person_detected": ratios.get("person_detected"),
        "track_stable": ratios.get("track_stable"),
        "pose_provider": last_pose.get("pose_provider"),
        "pose_fps": last_pose.get("pose_fps"),
        "last_inference_latency_ms": last_pose.get("last_inference_latency_ms"),
        "skipped_due_to_busy": last_pose.get("skipped_due_to_busy"),
        "rejected_reason": last_pose.get("rejected_reason"),
    }


def _scan_temporal_sequences(path: Path) -> dict[str, Any]:
    files = sorted(path.rglob("*.jsonl")) if path.exists() else []
    rows = 0
    pose_field_rows = 0
    pose_available_true = 0
    pose_confidence_nonzero = 0
    pose_quality_counts: dict[str, int] = {}
    pose_rejected_reason_counts: dict[str, int] = {}
    labels: dict[str, int] = {}
    datasets: dict[str, int] = {}

    for file_path in files:
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            labels[str(row.get("label") or "unknown")] = labels.get(str(row.get("label") or "unknown"), 0) + 1
            datasets[str(row.get("source_dataset") or "unknown")] = (
                datasets.get(str(row.get("source_dataset") or "unknown"), 0) + 1
            )
            target_feature = row.get("target_feature") if isinstance(row.get("target_feature"), dict) else {}
            feature_name_list = list(row.get("feature_names") or [])
            feature_names = set(feature_name_list)
            vector = row.get("vector") if isinstance(row.get("vector"), list) else []
            has_pose_fields = bool(POSE_FEATURE_NAMES & set(target_feature.keys())) or bool(POSE_FEATURE_NAMES & feature_names)
            if has_pose_fields:
                pose_field_rows += 1
            row_pose_available = target_feature.get("pose_available") is True
            if not row_pose_available and "pose_available" in feature_names and vector:
                index = feature_name_list.index("pose_available")
                row_pose_available = index < len(vector) and float(vector[index] or 0.0) > 0
            if row_pose_available:
                pose_available_true += 1
            quality_level = str(target_feature.get("pose_quality_level") or "unknown")
            pose_quality_counts[quality_level] = pose_quality_counts.get(quality_level, 0) + 1
            rejected_reason = target_feature.get("pose_rejected_reason")
            if rejected_reason:
                reason = str(rejected_reason)
                pose_rejected_reason_counts[reason] = pose_rejected_reason_counts.get(reason, 0) + 1
            try:
                if float(target_feature.get("pose_confidence") or 0.0) > 0:
                    pose_confidence_nonzero += 1
            except (TypeError, ValueError):
                pass

    return {
        "path": str(path),
        "jsonl_files": len(files),
        "rows": rows,
        "pose_field_rows": pose_field_rows,
        "pose_available_true_rows": pose_available_true,
        "pose_confidence_nonzero_rows": pose_confidence_nonzero,
        "pose_available_true_ratio": round(pose_available_true / rows, 4) if rows else 0.0,
        "pose_quality_counts": pose_quality_counts,
        "pose_rejected_reason_counts": pose_rejected_reason_counts,
        "labels": labels,
        "datasets": datasets,
    }


def _diagnosis(
    pose_metrics: dict[str, Any],
    e2e: dict[str, Any],
    temporal: dict[str, Any],
    env: dict[str, str],
) -> list[str]:
    findings: list[str] = []
    metric_summary = _pose_metric_summary(pose_metrics)
    e2e_summary = _e2e_summary(e2e)

    if (e2e_summary.get("pose_valid") or 0.0) < 0.70:
        findings.append("pose_valid 低于 0.70 门槛；先修运行链路，再谈重训是否有意义。")
    if int(e2e_summary.get("skipped_due_to_busy") or 0) > 0:
        findings.append("存在 busy skip；worker 频率、推理锁竞争和 TTL 是第一嫌疑人。")
    if temporal.get("pose_available_true_rows", 0) == 0:
        findings.append("时序训练数据有姿态字段名，但没有真实可用姿态证据，LSTM 实际没学到姿态。")
    quality_counts = temporal.get("pose_quality_counts") if isinstance(temporal.get("pose_quality_counts"), dict) else {}
    if quality_counts and set(quality_counts.keys()) == {"unknown"}:
        findings.append("时序训练数据缺少 pose_quality_level，无法区分缺失、低质、错绑和高质量姿态。")
    if (metric_summary.get("delta_pose_map50_95") or 0.0) < 0:
        findings.append("当前 yolo11s 候选更快，但 pose mAP50-95 低于 baseline，不能凭感觉上线。")
    if env.get("POSE_RESULT_TTL_MS") == "500":
        findings.append("POSE_RESULT_TTL_MS 只有 500 ms，配合低 worker FPS 非常脆。")
    if env.get("POSE_PROVIDER") and e2e_summary.get("pose_provider") and env.get("POSE_PROVIDER") != e2e_summary.get("pose_provider"):
        findings.append(
            f"当前 .env provider 是 {env.get('POSE_PROVIDER')}，但 E2E 证据 provider 是 {e2e_summary.get('pose_provider')}；后续必须用当前配置重跑基线。"
        )
    return findings


def _render_markdown(baseline: dict[str, Any]) -> str:
    pose = baseline["pose_config"]
    metrics = baseline["pose_model_metrics"]
    e2e = baseline["e2e_runtime"]
    temporal = baseline["temporal_pose_data"]
    diagnosis = "\n".join(f"- {item}" for item in baseline["diagnosis"])
    assets = "\n".join(
        f"- `{key}`: exists={value.get('exists')} size={value.get('size_bytes')} sha256={str(value.get('sha256'))[:12]}"
        for key, value in baseline["model_assets"].items()
    )
    return f"""# 姿态检测当前基线报告

生成时间：`{baseline['generated_at']}`

## 当前配置

- `POSE_PROVIDER`: `{pose.get('POSE_PROVIDER')}`
- `YOLO11_POSE_MODEL_PATH`: `{pose.get('YOLO11_POSE_MODEL_PATH')}`
- `POSE_FPS`: `{pose.get('POSE_FPS')}`
- `POSE_WORKER_FPS`: `{pose.get('POSE_WORKER_FPS')}`
- `POSE_RESULT_TTL_MS`: `{pose.get('POSE_RESULT_TTL_MS')}`
- `POSE_MAX_FRAME_AGE_MS`: `{pose.get('POSE_MAX_FRAME_AGE_MS')}`
- `POSE_MAX_TRACKING_FRAME_DELTA`: `{pose.get('POSE_MAX_TRACKING_FRAME_DELTA')}`
- `POSE_SKIP_WHEN_INFERENCE_BUSY`: `{pose.get('POSE_SKIP_WHEN_INFERENCE_BUSY')}`

## 模型资产

{assets or '- 未找到模型资产信息'}

## 离线姿态指标

- baseline: `{metrics.get('baseline_model')}`, pose mAP50-95 `{metrics.get('baseline_pose_map50_95')}`, inference `{metrics.get('baseline_inference_ms')} ms`
- candidate: `{metrics.get('candidate_model')}`, pose mAP50-95 `{metrics.get('candidate_pose_map50_95')}`, inference `{metrics.get('candidate_inference_ms')} ms`
- delta pose mAP50-95: `{metrics.get('delta_pose_map50_95')}`

## 端到端运行证据

- samples: `{e2e.get('samples')}`
- pose provider: `{e2e.get('pose_provider')}`
- pose_valid: `{e2e.get('pose_valid')}`
- pose_fps: `{e2e.get('pose_fps')}`
- skipped_due_to_busy: `{e2e.get('skipped_due_to_busy')}`
- last inference latency: `{e2e.get('last_inference_latency_ms')} ms`

## LSTM 姿态闭环

- temporal dir: `{temporal.get('path')}`
- jsonl files: `{temporal.get('jsonl_files')}`
- rows: `{temporal.get('rows')}`
- pose field rows: `{temporal.get('pose_field_rows')}`
- pose_available true rows: `{temporal.get('pose_available_true_rows')}`
- pose_available true ratio: `{temporal.get('pose_available_true_ratio')}`
- pose quality counts: `{temporal.get('pose_quality_counts')}`
- pose rejected reasons: `{temporal.get('pose_rejected_reason_counts')}`

## 诊断结论

{diagnosis or '- 暂无明显诊断结论'}

## 下一步门槛

- 姿态链路先把 `pose_valid_rate` 拉到 `>= 0.70`，再进入正式重训。
- 前端骨架可见率目标 `>= 0.60`。
- `pose_track_mismatch_rate` 必须控制到 `<= 0.05`。
- 新 LSTM 数据中 `pose_available_true_rows` 不能再是 0。
"""


if __name__ == "__main__":
    raise SystemExit(main())
