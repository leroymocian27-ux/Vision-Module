from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_PACKAGE_OUTPUT = Path("evaluations") / "pose_evidence_package_check_20260705.json"
DEFAULT_DEPLOYMENT_GUARD_OUTPUT = Path("evaluations") / "pose_deployment_guard_20260705.json"
DEFAULT_LAUNCH_SAFETY_OUTPUT = Path("evaluations") / "pose_launch_safety_check_20260705.json"
DEFAULT_PROMOTION_GATE_OUTPUT = Path("evaluations") / "pose_promotion_gate_20260705.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the staged pose optimization production gate pipeline.")
    parser.add_argument("--mode", choices=("production", "dev-smoke", "dev-live"), default="production")
    parser.add_argument("--profile-name", default="B")
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    parser.add_argument("--camera-id", default="camera_01")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--providers", default="yolo11_legacy,yolo,branch4_legacy,rtmpose_onnx")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--pose-model-quality-metrics", default="models/pose_yolo_batch001_003_yolo11s_metrics.json")
    parser.add_argument(
        "--configured-pose-model",
        default="__env__",
        help="Pose model to validate. Defaults to the active pose model in .env; pass an explicit path for candidate diagnostics.",
    )
    parser.add_argument("--labels", default="data/phase7_labels/phase7_video_labels.jsonl")
    parser.add_argument("--temporal-output-dir", default="data/temporal_sequences_pose_v1")
    parser.add_argument("--frame-stride", type=int, default=2)
    parser.add_argument("--model-version", default="v6_pose")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--lstm-stride", type=int, default=4)
    parser.add_argument("--baseline-lstm-model", default="models/fall_lstm_v5.onnx")
    parser.add_argument("--baseline-lstm-schema", default="models/fall_lstm_v5_features.json")
    parser.add_argument("--baseline-lstm-threshold", default="models/fall_lstm_v5_threshold_calibration.json")
    parser.add_argument("--baseline-lstm-train-config", default="models/fall_lstm_v5_train_config.json")
    parser.add_argument("--pose-lstm-model", default="models/fall_lstm_v6_pose.onnx")
    parser.add_argument("--pose-lstm-schema", default="models/fall_lstm_v6_pose_features.json")
    parser.add_argument("--pose-lstm-threshold", default="models/fall_lstm_v6_pose_threshold_calibration.json")
    parser.add_argument("--pose-lstm-train-config", default="models/fall_lstm_v6_pose_train_config.json")
    parser.add_argument("--baseline-lstm-metrics", default="evaluations/baseline_lstm_eval_20260705.json")
    parser.add_argument("--pose-lstm-metrics", default="evaluations/pose_lstm_eval_20260705.json")
    parser.add_argument("--pose-lstm-ablation-metrics", default="evaluations/pose_lstm_zero_pose_eval_20260705.json")
    parser.add_argument("--lstm-eval-split", default="test", choices=("train", "val", "test", "all"))
    parser.add_argument("--lstm-eval-stride", type=int, default=4)
    parser.add_argument("--summary", default="evaluations/pose_optimization_pipeline_20260705.json")
    parser.add_argument("--evidence-package-output", default=str(DEFAULT_EVIDENCE_PACKAGE_OUTPUT))
    parser.add_argument("--deployment-guard-output", default=str(DEFAULT_DEPLOYMENT_GUARD_OUTPUT))
    parser.add_argument("--launch-safety-output", default=str(DEFAULT_LAUNCH_SAFETY_OUTPUT))
    parser.add_argument("--promotion-gate-output", default=str(DEFAULT_PROMOTION_GATE_OUTPUT))
    parser.add_argument("--dev-video", default="datasets/ur_fall/videos/fall-01.mp4")
    parser.add_argument("--dev-runtime-profiles", default="B")
    parser.add_argument("--dev-max-sampled-frames", type=int, default=6)
    parser.add_argument("--dev-provider-max-frames", type=int, default=5)
    parser.add_argument("--dev-temporal-frame-stride", type=int, default=4)
    parser.add_argument("--dev-temporal-max-frames", type=int, default=360)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument("--skip-provider", action="store_true")
    parser.add_argument("--skip-temporal-export", action="store_true")
    parser.add_argument("--skip-lstm-manifest", action="store_true")
    parser.add_argument("--skip-lstm-train", action="store_true")
    parser.add_argument("--skip-lstm-eval", action="store_true")
    parser.add_argument("--skip-lstm-comparison", action="store_true")
    args = parser.parse_args()

    stages = build_pipeline_stages(
        profile_name=args.profile_name,
        duration_seconds=args.duration_seconds,
        interval_seconds=args.interval_seconds,
        camera_id=args.camera_id,
        base_url=args.base_url,
        providers=args.providers,
        device=args.device,
        pose_model_quality_metrics=Path(args.pose_model_quality_metrics),
        configured_pose_model=resolve_configured_pose_model(args.configured_pose_model),
        labels=Path(args.labels),
        temporal_output_dir=Path(args.temporal_output_dir),
        frame_stride=args.frame_stride,
        model_version=args.model_version,
        epochs=args.epochs,
        lstm_stride=args.lstm_stride,
        baseline_lstm_model=Path(args.baseline_lstm_model),
        baseline_lstm_schema=Path(args.baseline_lstm_schema),
        baseline_lstm_threshold=Path(args.baseline_lstm_threshold),
        baseline_lstm_train_config=Path(args.baseline_lstm_train_config),
        pose_lstm_model=Path(args.pose_lstm_model),
        pose_lstm_schema=Path(args.pose_lstm_schema),
        pose_lstm_threshold=Path(args.pose_lstm_threshold),
        pose_lstm_train_config=Path(args.pose_lstm_train_config),
        baseline_lstm_metrics=Path(args.baseline_lstm_metrics),
        pose_lstm_metrics=Path(args.pose_lstm_metrics),
        pose_lstm_ablation_metrics=Path(args.pose_lstm_ablation_metrics),
        lstm_eval_split=args.lstm_eval_split,
        lstm_eval_stride=args.lstm_eval_stride,
        skip_preflight=args.skip_preflight,
        skip_runtime=args.skip_runtime,
        skip_provider=args.skip_provider,
        skip_temporal_export=args.skip_temporal_export,
        skip_lstm_manifest=args.skip_lstm_manifest,
        skip_lstm_train=args.skip_lstm_train,
        skip_lstm_eval=args.skip_lstm_eval,
        skip_lstm_comparison=args.skip_lstm_comparison,
        mode=args.mode,
        dev_video=Path(args.dev_video),
        dev_runtime_profiles=args.dev_runtime_profiles,
        dev_max_sampled_frames=args.dev_max_sampled_frames,
        dev_provider_max_frames=args.dev_provider_max_frames,
        dev_temporal_frame_stride=args.dev_temporal_frame_stride,
        dev_temporal_max_frames=args.dev_temporal_max_frames,
    )
    result = run_pipeline(stages, dry_run=args.dry_run, mode=args.mode)
    summary_path = ROOT / effective_summary_path(args.summary, args.mode)
    result = write_pipeline_summary(
        result,
        summary_path=summary_path,
        mode=args.mode,
        dry_run=args.dry_run,
        evidence_package_output=Path(args.evidence_package_output),
        deployment_guard_output=Path(args.deployment_guard_output),
        launch_safety_output=Path(args.launch_safety_output),
        promotion_gate_output=Path(args.promotion_gate_output),
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return pipeline_exit_code(result, mode=args.mode, dry_run=args.dry_run)


def build_pipeline_stages(
    *,
    profile_name: str,
    duration_seconds: float,
    interval_seconds: float,
    camera_id: str,
    base_url: str,
    providers: str,
    device: str,
    labels: Path,
    temporal_output_dir: Path,
    frame_stride: int,
    model_version: str,
    epochs: int,
    lstm_stride: int,
    baseline_lstm_model: Path = Path("models/fall_lstm_v5.onnx"),
    baseline_lstm_schema: Path = Path("models/fall_lstm_v5_features.json"),
    baseline_lstm_threshold: Path = Path("models/fall_lstm_v5_threshold_calibration.json"),
    baseline_lstm_train_config: Path = Path("models/fall_lstm_v5_train_config.json"),
    pose_lstm_model: Path = Path("models/fall_lstm_v6_pose.onnx"),
    pose_lstm_schema: Path = Path("models/fall_lstm_v6_pose_features.json"),
    pose_lstm_threshold: Path = Path("models/fall_lstm_v6_pose_threshold_calibration.json"),
    pose_lstm_train_config: Path = Path("models/fall_lstm_v6_pose_train_config.json"),
    baseline_lstm_metrics: Path = Path("evaluations/baseline_lstm_eval_20260705.json"),
    pose_lstm_metrics: Path = Path("evaluations/pose_lstm_eval_20260705.json"),
    pose_lstm_ablation_metrics: Path = Path("evaluations/pose_lstm_zero_pose_eval_20260705.json"),
    lstm_eval_split: str = "test",
    lstm_eval_stride: int = 4,
    skip_preflight: bool = False,
    skip_runtime: bool,
    skip_provider: bool,
    skip_temporal_export: bool,
    skip_lstm_manifest: bool,
    skip_lstm_train: bool = False,
    skip_lstm_eval: bool = False,
    skip_lstm_comparison: bool = False,
    mode: str = "production",
    dev_video: Path | None = None,
    dev_runtime_profiles: str = "B",
    dev_max_sampled_frames: int = 6,
    dev_provider_max_frames: int = 5,
    dev_temporal_frame_stride: int = 4,
    dev_temporal_max_frames: int = 360,
    pose_model_quality_metrics: Path = Path("models/pose_yolo_batch001_003_yolo11s_metrics.json"),
    configured_pose_model: str = "__env__",
) -> list[dict[str, Any]]:
    configured_pose_model = resolve_configured_pose_model(configured_pose_model)
    if mode == "dev-smoke":
        return build_dev_smoke_pipeline_stages(
            labels=labels,
            temporal_output_dir=temporal_output_dir,
            model_version=model_version,
            epochs=epochs,
            lstm_stride=lstm_stride,
            skip_runtime=skip_runtime,
            skip_provider=skip_provider,
            skip_temporal_export=skip_temporal_export,
            skip_lstm_manifest=skip_lstm_manifest,
            skip_lstm_train=skip_lstm_train,
            skip_lstm_eval=skip_lstm_eval,
            skip_lstm_comparison=skip_lstm_comparison,
            dev_video=dev_video or Path("datasets/ur_fall/videos/fall-01.mp4"),
            dev_runtime_profiles=dev_runtime_profiles,
            dev_max_sampled_frames=dev_max_sampled_frames,
            dev_provider_max_frames=dev_provider_max_frames,
            dev_temporal_frame_stride=dev_temporal_frame_stride,
            dev_temporal_max_frames=dev_temporal_max_frames,
            configured_pose_model=configured_pose_model,
        )
    if mode == "dev-live":
        return build_dev_live_pipeline_stages(
            profile_name=profile_name,
            duration_seconds=duration_seconds,
            interval_seconds=interval_seconds,
            camera_id=camera_id,
            base_url=base_url,
            skip_runtime=skip_runtime,
            configured_pose_model=configured_pose_model,
        )

    runtime_profile = Path("evaluations") / f"pose_runtime_profile_{profile_name}_20260705.json"
    provider_ab = Path("evaluations") / "pose_provider_ab_20260705.json"
    preflight = Path("evaluations") / "pose_production_preflight_20260705.json"
    model_quality = Path("evaluations") / "pose_model_quality_20260705.json"
    temporal_check = Path("evaluations") / "pose_temporal_sequences_check_20260705.json"
    lstm_manifest = Path("data") / "temporal_v6_training" / "lstm_v6_pose_training_manifest.json"
    lstm_comparison = Path("evaluations") / "pose_lstm_comparison_20260705.json"
    stages: list[dict[str, Any]] = []
    stages.append(
        stage(
            "pose_model_quality",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_model_quality.py"),
                "--metrics",
                str(pose_model_quality_metrics),
                "--configured-model",
                configured_pose_model,
                "--output",
                str(model_quality),
            ],
            output=model_quality,
        )
    )
    if not skip_preflight:
        stages.append(
            stage(
                "production_preflight",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_pose_production_preflight.py"),
                    "--base-url",
                    base_url,
                    "--camera-id",
                    camera_id,
                    "--device",
                    device,
                    "--duration-seconds",
                    str(duration_seconds),
                    "--labels",
                    str(labels),
                    "--temporal-output-dir",
                    str(temporal_output_dir),
                    "--lstm-eval-split",
                    lstm_eval_split,
                    "--baseline-lstm-model",
                    str(baseline_lstm_model),
                    "--baseline-lstm-schema",
                    str(baseline_lstm_schema),
                    "--baseline-lstm-threshold",
                    str(baseline_lstm_threshold),
                    "--output",
                    str(preflight),
                ],
                output=preflight,
            )
        )
    if not skip_runtime:
        stages.append(
            stage(
                "runtime_probe",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "probe_pose_runtime_status.py"),
                    "--profile-name",
                    profile_name,
                    "--duration-seconds",
                    str(duration_seconds),
                    "--interval-seconds",
                    str(interval_seconds),
                    "--camera-id",
                    camera_id,
                    "--base-url",
                    base_url,
                    "--output",
                    str(runtime_profile),
                ],
                output=runtime_profile,
            )
        )
    if not skip_provider:
        stages.append(
            stage(
                "provider_ab",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "benchmark_pose_providers.py"),
                    "--providers",
                    providers,
                    "--device",
                    device,
                    "--output",
                    str(provider_ab),
                ],
                output=provider_ab,
            )
        )
    if not skip_temporal_export:
        for dataset in ("ur_fall", "gmdcsa24"):
            stages.append(
                stage(
                    f"temporal_export_{dataset}",
                    [
                        sys.executable,
                        str(ROOT / "scripts" / "export_dataset_temporal_sequences.py"),
                        "--dataset",
                        dataset,
                        "--labels",
                        str(labels),
                        "--output-dir",
                        str(temporal_output_dir),
                        "--frame-stride",
                        str(frame_stride),
                        "--enable-pose",
                        "--device",
                        device,
                    ],
                    output=temporal_output_dir / dataset / "export_summary.json",
                )
            )
        stages.append(
            stage(
                "temporal_pose_check",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_pose_temporal_sequences.py"),
                    "--input-dir",
                    str(temporal_output_dir),
                    "--output",
                    str(temporal_check),
                ],
                output=temporal_check,
            )
        )
    if not skip_lstm_manifest:
        stages.append(
            stage(
                "lstm_pose_manifest",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_temporal_v6_lstm_training_manifest.py"),
                    "--base-dir",
                    str(temporal_output_dir),
                    "--residual-dir",
                    str(Path("data") / "temporal_v6_training" / "residual_reviewed"),
                    "--output",
                    str(lstm_manifest),
                    "--model-version",
                    model_version,
                    "--epochs",
                    str(epochs),
                    "--stride",
                    str(lstm_stride),
                    "--require-pose",
                ],
                output=lstm_manifest,
            )
        )
    if not skip_lstm_train:
        stages.append(
            lstm_train_stage(
                name="pose_lstm_train",
                input_manifest=lstm_manifest,
                output_dir=Path("models"),
                model_version=model_version,
                epochs=epochs,
                stride=lstm_stride,
                output=pose_lstm_model,
            )
        )
    if not skip_lstm_eval:
        stages.extend(
            lstm_eval_stages(
                input_manifest=lstm_manifest,
                baseline_model=baseline_lstm_model,
                baseline_schema=baseline_lstm_schema,
                baseline_threshold=baseline_lstm_threshold,
                baseline_train_config=baseline_lstm_train_config,
                baseline_metrics=baseline_lstm_metrics,
                pose_model=pose_lstm_model,
                pose_schema=pose_lstm_schema,
                pose_threshold=pose_lstm_threshold,
                pose_train_config=pose_lstm_train_config,
                pose_metrics=pose_lstm_metrics,
                pose_ablation_metrics=pose_lstm_ablation_metrics,
                split=lstm_eval_split,
                stride=lstm_eval_stride,
                suffix="",
            )
        )
    if not skip_lstm_comparison:
        stages.append(
            gate_stage(
                "lstm_pose_comparison",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_pose_lstm_comparison.py"),
                    "--baseline-metrics",
                    str(baseline_lstm_metrics),
                    "--pose-metrics",
                    str(pose_lstm_metrics),
                    "--pose-ablation-metrics",
                    str(pose_lstm_ablation_metrics),
                    "--lstm-manifest",
                    str(lstm_manifest),
                    "--output",
                    str(lstm_comparison),
                ],
                output=lstm_comparison,
            )
        )
    stages.append(
        stage(
            "readiness",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_optimization_readiness.py"),
                "--runtime-profile",
                str(runtime_profile),
                "--provider-ab",
                str(provider_ab),
                "--pose-model-quality",
                str(model_quality),
                "--temporal-check",
                str(temporal_check),
                "--lstm-manifest",
                str(lstm_manifest),
                "--lstm-comparison",
                str(lstm_comparison),
                "--output",
                str(Path("evaluations") / "pose_optimization_readiness_20260705.json"),
            ],
            output=Path("evaluations") / "pose_optimization_readiness_20260705.json",
        )
    )
    return stages


def build_dev_smoke_pipeline_stages(
    *,
    labels: Path,
    temporal_output_dir: Path,
    model_version: str,
    epochs: int,
    lstm_stride: int,
    skip_runtime: bool,
    skip_provider: bool,
    skip_temporal_export: bool,
    skip_lstm_manifest: bool,
    skip_lstm_train: bool,
    skip_lstm_eval: bool,
    skip_lstm_comparison: bool,
    dev_video: Path,
    dev_runtime_profiles: str,
    dev_max_sampled_frames: int,
    dev_provider_max_frames: int,
    dev_temporal_frame_stride: int,
    dev_temporal_max_frames: int,
    configured_pose_model: str,
) -> list[dict[str, Any]]:
    runtime_profile = Path("evaluations") / "pose_runtime_replay_dev_smoke_20260705.json"
    model_quality = Path("evaluations") / "pose_model_quality_dev_smoke_20260705.json"
    provider_ab = Path("evaluations") / "pose_provider_ab_dev_smoke_20260705.json"
    effective_temporal_dir = (
        Path("data") / "temporal_sequences_pose_dev_smoke"
        if temporal_output_dir == Path("data/temporal_sequences_pose_v1")
        else temporal_output_dir
    )
    temporal_check = Path("evaluations") / "pose_temporal_sequences_check_dev_smoke_20260705.json"
    lstm_manifest = Path("data") / "temporal_v6_training" / "lstm_v6_pose_dev_smoke_training_manifest.json"
    lstm_comparison = Path("evaluations") / "pose_lstm_comparison_dev_smoke_20260705.json"
    baseline_lstm_metrics = Path("evaluations") / "baseline_lstm_eval_dev_smoke_20260705.json"
    pose_lstm_metrics = Path("evaluations") / "pose_lstm_eval_dev_smoke_20260705.json"
    pose_lstm_ablation_metrics = Path("evaluations") / "pose_lstm_zero_pose_eval_dev_smoke_20260705.json"
    baseline_lstm_model = Path("models") / "fall_lstm_v5.onnx"
    baseline_lstm_schema = Path("models") / "fall_lstm_v5_features.json"
    baseline_lstm_threshold = Path("models") / "fall_lstm_v5_threshold_calibration.json"
    baseline_lstm_train_config = Path("models") / "fall_lstm_v5_train_config.json"
    pose_lstm_model = Path("models") / f"fall_lstm_{model_version}_dev_smoke.onnx"
    pose_lstm_schema = Path("models") / f"fall_lstm_{model_version}_dev_smoke_features.json"
    pose_lstm_threshold = Path("models") / f"fall_lstm_{model_version}_dev_smoke_threshold_calibration.json"
    pose_lstm_train_config = Path("models") / f"fall_lstm_{model_version}_dev_smoke_train_config.json"
    readiness = Path("evaluations") / "pose_optimization_readiness_dev_smoke_20260705.json"
    stages: list[dict[str, Any]] = []
    stages.append(
        gate_stage(
            "pose_model_quality_dev_smoke",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_model_quality.py"),
                "--metrics",
                str(Path("models") / "pose_yolo_batch001_003_yolo11s_metrics.json"),
                "--configured-model",
                configured_pose_model,
                "--output",
                str(model_quality),
            ],
            output=model_quality,
        )
    )
    if not skip_runtime:
        stages.append(
            stage(
                "runtime_replay_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "replay_pose_runtime_profiles.py"),
                    "--video",
                    str(dev_video),
                    "--profiles",
                    dev_runtime_profiles,
                    "--device",
                    "cpu",
                    "--frame-stride",
                    str(dev_temporal_frame_stride),
                    "--max-sampled-frames",
                    str(dev_max_sampled_frames),
                    "--replay-fps",
                    "2.5",
                    "--output",
                    str(runtime_profile),
                ],
                output=runtime_profile,
            )
        )
    if not skip_provider:
        stages.append(
            stage(
                "provider_ab_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "benchmark_pose_providers.py"),
                    "--providers",
                    "yolo11_legacy,yolo",
                    "--device",
                    "cpu",
                    "--limit-fall",
                    "1",
                    "--limit-non-fall",
                    "1",
                    "--max-frames-per-video",
                    str(dev_provider_max_frames),
                    "--output",
                    str(provider_ab),
                ],
                output=provider_ab,
            )
        )
    if not skip_temporal_export:
        stages.append(
            stage(
                "temporal_export_ur_fall_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "export_dataset_temporal_sequences.py"),
                    "--dataset",
                    "ur_fall",
                    "--labels",
                    str(labels),
                    "--split-override",
                    "unassigned",
                    "--output-dir",
                    str(effective_temporal_dir),
                    "--frame-stride",
                    str(dev_temporal_frame_stride),
                    "--max-frames",
                    str(dev_temporal_max_frames),
                    "--video-id",
                    "ur_fall/fall-01.mp4",
                    "--video-id",
                    "ur_fall/adl-01.mp4",
                    "--enable-pose",
                    "--device",
                    "cpu",
                ],
                output=effective_temporal_dir / "ur_fall" / "export_summary.json",
            )
        )
        stages.append(
            stage(
                "temporal_pose_check_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_pose_temporal_sequences.py"),
                    "--input-dir",
                    str(effective_temporal_dir),
                    "--output",
                    str(temporal_check),
                    "--min-pose-available-ratio",
                    "0.05",
                ],
                output=temporal_check,
            )
        )
    if not skip_lstm_manifest:
        stages.append(
            stage(
                "lstm_pose_manifest_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_temporal_v6_lstm_training_manifest.py"),
                    "--base-dir",
                    str(effective_temporal_dir),
                    "--residual-dir",
                    str(Path("data") / "temporal_v6_training" / "residual_reviewed"),
                    "--output",
                    str(lstm_manifest),
                    "--model-version",
                    f"{model_version}_dev_smoke",
                    "--epochs",
                    str(min(epochs, 1)),
                    "--stride",
                    str(min(lstm_stride, 2)),
                    "--require-pose",
                    "--skip-residual",
                ],
                output=lstm_manifest,
            )
        )
    if not skip_lstm_train:
        stages.append(
            lstm_train_stage(
                name="pose_lstm_train_dev_smoke",
                input_manifest=lstm_manifest,
                output_dir=Path("models"),
                model_version=f"{model_version}_dev_smoke",
                epochs=min(epochs, 1),
                stride=min(lstm_stride, 2),
                output=pose_lstm_model,
            )
        )
    if not skip_lstm_eval:
        stages.extend(
            lstm_eval_stages(
                input_manifest=lstm_manifest,
                baseline_model=baseline_lstm_model,
                baseline_schema=baseline_lstm_schema,
                baseline_threshold=baseline_lstm_threshold,
                baseline_train_config=baseline_lstm_train_config,
                baseline_metrics=baseline_lstm_metrics,
                pose_model=pose_lstm_model,
                pose_schema=pose_lstm_schema,
                pose_threshold=pose_lstm_threshold,
                pose_train_config=pose_lstm_train_config,
                pose_metrics=pose_lstm_metrics,
                pose_ablation_metrics=pose_lstm_ablation_metrics,
                split="all",
                stride=2,
                suffix="_dev_smoke",
            )
        )
    if not skip_lstm_comparison:
        stages.append(
            gate_stage(
                "lstm_pose_comparison_dev_smoke",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_pose_lstm_comparison.py"),
                    "--baseline-metrics",
                    str(baseline_lstm_metrics),
                    "--pose-metrics",
                    str(pose_lstm_metrics),
                    "--pose-ablation-metrics",
                    str(pose_lstm_ablation_metrics),
                    "--lstm-manifest",
                    str(lstm_manifest),
                    "--output",
                    str(lstm_comparison),
                ],
                output=lstm_comparison,
            )
        )
    stages.append(
        stage(
            "readiness_dev_smoke",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_optimization_readiness.py"),
                "--runtime-profile",
                str(runtime_profile),
                "--provider-ab",
                str(provider_ab),
                "--pose-model-quality",
                str(model_quality),
                "--temporal-check",
                str(temporal_check),
                "--lstm-manifest",
                str(lstm_manifest),
                "--lstm-comparison",
                str(lstm_comparison),
                "--allow-cpu-provider",
                "--allow-replay-runtime",
                "--output",
                str(readiness),
            ],
            output=readiness,
        )
    )
    return stages


def build_dev_live_pipeline_stages(
    *,
    profile_name: str,
    duration_seconds: float,
    interval_seconds: float,
    camera_id: str,
    base_url: str,
    skip_runtime: bool,
    configured_pose_model: str,
) -> list[dict[str, Any]]:
    runtime_profile = Path("evaluations") / f"pose_runtime_profile_{profile_name}_dev_live_20260705.json"
    model_quality = Path("evaluations") / "pose_model_quality_dev_live_20260705.json"
    provider_ab = Path("evaluations") / "pose_provider_ab_dev_smoke_20260705.json"
    temporal_check = Path("evaluations") / "pose_temporal_sequences_check_dev_smoke_20260705.json"
    lstm_manifest = Path("data") / "temporal_v6_training" / "lstm_v6_pose_dev_smoke_training_manifest.json"
    lstm_comparison = Path("evaluations") / "pose_lstm_comparison_dev_smoke_20260705.json"
    readiness = Path("evaluations") / f"pose_optimization_readiness_{profile_name}_dev_live_20260705.json"
    stages: list[dict[str, Any]] = []
    stages.append(
        gate_stage(
            "pose_model_quality_dev_live",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_model_quality.py"),
                "--metrics",
                str(Path("models") / "pose_yolo_batch001_003_yolo11s_metrics.json"),
                "--configured-model",
                configured_pose_model,
                "--output",
                str(model_quality),
            ],
            output=model_quality,
        )
    )
    if not skip_runtime:
        stages.append(
            stage(
                "runtime_probe_dev_live",
                [
                    sys.executable,
                    str(ROOT / "scripts" / "probe_pose_runtime_status.py"),
                    "--profile-name",
                    profile_name,
                    "--duration-seconds",
                    str(duration_seconds),
                    "--interval-seconds",
                    str(interval_seconds),
                    "--camera-id",
                    camera_id,
                    "--base-url",
                    base_url,
                    "--output",
                    str(runtime_profile),
                ],
                output=runtime_profile,
            )
        )
    stages.append(
        stage(
            "readiness_dev_live",
            [
                sys.executable,
                str(ROOT / "scripts" / "check_pose_optimization_readiness.py"),
                "--runtime-profile",
                str(runtime_profile),
                "--provider-ab",
                str(provider_ab),
                "--pose-model-quality",
                str(model_quality),
                "--temporal-check",
                str(temporal_check),
                "--lstm-manifest",
                str(lstm_manifest),
                "--lstm-comparison",
                str(lstm_comparison),
                "--allow-cpu-provider",
                "--output",
                str(readiness),
            ],
            output=readiness,
        )
    )
    return stages


def stage(name: str, command: list[str], *, output: Path) -> dict[str, Any]:
    return {
        "name": name,
        "command": command,
        "output": str(output),
    }


def gate_stage(name: str, command: list[str], *, output: Path) -> dict[str, Any]:
    item = stage(name, command, output=output)
    item["continue_on_failure"] = True
    return item


def lstm_train_stage(
    *,
    name: str,
    input_manifest: Path,
    output_dir: Path,
    model_version: str,
    epochs: int,
    stride: int,
    output: Path,
) -> dict[str, Any]:
    return stage(
        name,
        [
            sys.executable,
            str(ROOT / "scripts" / "train_fall_lstm.py"),
            "--input-manifest",
            str(input_manifest),
            "--output-dir",
            str(output_dir),
            "--model-version",
            model_version,
            "--epochs",
            str(epochs),
            "--stride",
            str(stride),
        ],
        output=output,
    )


def lstm_eval_stages(
    *,
    input_manifest: Path,
    baseline_model: Path,
    baseline_schema: Path,
    baseline_threshold: Path,
    baseline_train_config: Path,
    baseline_metrics: Path,
    pose_model: Path,
    pose_schema: Path,
    pose_threshold: Path,
    pose_train_config: Path,
    pose_metrics: Path,
    pose_ablation_metrics: Path,
    split: str,
    stride: int,
    suffix: str,
) -> list[dict[str, Any]]:
    return [
        stage(
            f"baseline_lstm_eval{suffix}",
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_fall_lstm_metrics.py"),
                "--input-manifest",
                str(input_manifest),
                "--model",
                str(baseline_model),
                "--schema",
                str(baseline_schema),
                "--train-config",
                str(baseline_train_config),
                "--threshold-calibration",
                str(baseline_threshold),
                "--split",
                split,
                "--stride",
                str(stride),
                "--output",
                str(baseline_metrics),
            ],
            output=baseline_metrics,
        ),
        stage(
            f"pose_lstm_eval{suffix}",
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_fall_lstm_metrics.py"),
                "--input-manifest",
                str(input_manifest),
                "--model",
                str(pose_model),
                "--schema",
                str(pose_schema),
                "--train-config",
                str(pose_train_config),
                "--threshold-calibration",
                str(pose_threshold),
                "--split",
                split,
                "--stride",
                str(stride),
                "--output",
                str(pose_metrics),
            ],
            output=pose_metrics,
        ),
        stage(
            f"pose_lstm_zero_pose_eval{suffix}",
            [
                sys.executable,
                str(ROOT / "scripts" / "evaluate_fall_lstm_metrics.py"),
                "--input-manifest",
                str(input_manifest),
                "--model",
                str(pose_model),
                "--schema",
                str(pose_schema),
                "--train-config",
                str(pose_train_config),
                "--threshold-calibration",
                str(pose_threshold),
                "--split",
                split,
                "--stride",
                str(stride),
                "--zero-pose-features",
                "--output",
                str(pose_ablation_metrics),
            ],
            output=pose_ablation_metrics,
        ),
    ]


def run_pipeline(stages: list[dict[str, Any]], *, dry_run: bool, mode: str = "production") -> dict[str, Any]:
    stage_results: list[dict[str, Any]] = []
    status = "dry_run" if dry_run else "ok"
    failed_stage = None
    for index, item in enumerate(stages):
        if dry_run:
            stage_results.append(
                {
                    **item,
                    "status": "planned",
                    "returncode": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_seconds": None,
                }
            )
            continue
        started_at = datetime.now(timezone.utc)
        completed = subprocess.run(item["command"], cwd=str(ROOT))
        finished_at = datetime.now(timezone.utc)
        stage_status = "ok" if completed.returncode == 0 else "failed"
        stage_results.append(
            {
                **item,
                "status": stage_status,
                "returncode": completed.returncode,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "duration_seconds": round((finished_at - started_at).total_seconds(), 6),
            }
        )
        if completed.returncode != 0:
            status = "error"
            if failed_stage is None:
                failed_stage = item["name"]
            if not item.get("continue_on_failure"):
                for skipped in stages[index + 1 :]:
                    stage_results.append(
                        {
                            **skipped,
                            "status": "skipped",
                            "returncode": None,
                            "started_at": None,
                            "finished_at": None,
                            "duration_seconds": None,
                            "skipped_due_to": item["name"],
                        }
                    )
                break
    production_ready = False
    if mode == "production" and status == "ok":
        production_ready = readiness_production_ready(stage_results)
    completed_stage_count = sum(1 for item in stage_results if item.get("status") != "skipped")
    skipped_stage_count = sum(1 for item in stage_results if item.get("status") == "skipped")
    executed_stage_count = sum(1 for item in stage_results if item.get("started_at"))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "mode": mode,
            "status": status,
            "stage_count": len(stages),
            "completed_stage_count": completed_stage_count,
            "executed_stage_count": executed_stage_count,
            "skipped_stage_count": skipped_stage_count,
            "failed_stage": failed_stage,
            "next_action": next_action(status, failed_stage, mode=mode),
            "production_ready": production_ready,
        },
        "stages": stage_results,
    }


def write_pipeline_summary(
    result: dict[str, Any],
    *,
    summary_path: Path,
    mode: str,
    dry_run: bool,
    evidence_package_output: Path = DEFAULT_EVIDENCE_PACKAGE_OUTPUT,
    deployment_guard_output: Path = DEFAULT_DEPLOYMENT_GUARD_OUTPUT,
    launch_safety_output: Path = DEFAULT_LAUNCH_SAFETY_OUTPUT,
    promotion_gate_output: Path = DEFAULT_PROMOTION_GATE_OUTPUT,
) -> dict[str, Any]:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if mode == "production" and not dry_run:
        post_gates = build_and_write_post_pipeline_gates(
            pipeline_path=summary_path,
            evidence_package_output=evidence_package_output,
            deployment_guard_output=deployment_guard_output,
            launch_safety_output=launch_safety_output,
            promotion_gate_output=promotion_gate_output,
        )
        result["summary"]["post_pipeline_gates"] = post_gates
        result["summary"]["evidence_package"] = post_gates["evidence_package"]
        summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def pipeline_exit_code(result: dict[str, Any], *, mode: str, dry_run: bool) -> int:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    status = summary.get("status")
    if dry_run:
        return 0 if status == "dry_run" else 1
    if mode == "production":
        promotion = nested_dict(summary, "post_pipeline_gates", "promotion_gate")
        if promotion:
            return 0 if status == "ok" and promotion.get("promotion_allowed") is True else 1
        return 0 if status == "ok" and summary.get("production_ready") is True else 1
    return 0 if status in {"ok", "dry_run"} else 1


def resolve_configured_pose_model(value: str | None, *, env_file: Path = Path(".env")) -> str:
    text = str(value or "").strip()
    if text and text.lower() not in {"__env__", "env", "auto"}:
        return text
    env = load_env_file(env_file)
    provider = str(env.get("POSE_PROVIDER") or "yolo11_legacy").strip().lower()
    if provider in {"yolo11_legacy", "branch4_legacy"}:
        return env.get("YOLO11_POSE_MODEL_PATH") or "yolo11n-pose.pt"
    if provider == "yolo":
        return env.get("YOLO_POSE_MODEL_PATH") or "yolov8n-pose.pt"
    if provider == "rtmpose_onnx":
        return env.get("RTMPOSE_ONNX_MODEL_PATH") or ""
    if provider == "mmpose":
        return env.get("RTMPOSE_CHECKPOINT_PATH") or ""
    return (
        env.get("YOLO11_POSE_MODEL_PATH")
        or env.get("YOLO_POSE_MODEL_PATH")
        or env.get("RTMPOSE_ONNX_MODEL_PATH")
        or "yolo11n-pose.pt"
    )


def load_env_file(path: Path) -> dict[str, str]:
    resolved = path if path.is_absolute() else ROOT / path
    if not resolved.exists():
        return {}
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
    return values


def nested_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def build_and_write_post_pipeline_gates(
    *,
    pipeline_path: Path,
    evidence_package_output: Path,
    deployment_guard_output: Path = DEFAULT_DEPLOYMENT_GUARD_OUTPUT,
    launch_safety_output: Path = DEFAULT_LAUNCH_SAFETY_OUTPUT,
    promotion_gate_output: Path = DEFAULT_PROMOTION_GATE_OUTPUT,
) -> dict[str, Any]:
    evidence_report = build_and_write_evidence_package(
        pipeline_path=pipeline_path,
        evidence_package_output=evidence_package_output,
    )
    deployment_report = build_and_write_deployment_guard(
        evidence_package_path=evidence_package_output,
        deployment_guard_output=deployment_guard_output,
    )
    launch_report = build_and_write_launch_safety(launch_safety_output=launch_safety_output)
    promotion_report = build_and_write_promotion_gate(
        evidence_package_path=evidence_package_output,
        deployment_guard_path=deployment_guard_output,
        launch_safety_path=launch_safety_output,
        promotion_gate_output=promotion_gate_output,
    )
    return {
        "evidence_package": gate_summary(
            evidence_package_output,
            evidence_report,
            result_key="handoff_ready",
            label="handoff_ready",
        ),
        "deployment_guard": gate_summary(
            deployment_guard_output,
            deployment_report,
            result_key="deployment_allowed",
            label="deployment_allowed",
        ),
        "launch_safety": gate_summary(
            launch_safety_output,
            launch_report,
            result_key="launch_safety_passed",
            label="launch_safety_passed",
        ),
        "promotion_gate": gate_summary(
            promotion_gate_output,
            promotion_report,
            result_key="promotion_allowed",
            label="promotion_allowed",
        ),
    }


def build_and_write_evidence_package(*, pipeline_path: Path, evidence_package_output: Path) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.check_pose_evidence_package import build_evidence_package_report

    report = build_evidence_package_report(
        preflight_path=Path("evaluations") / "pose_production_preflight_20260705.json",
        pipeline_path=pipeline_path,
        temporal_check_path=Path("evaluations") / "pose_temporal_sequences_check_20260705.json",
        lstm_manifest_path=Path("data") / "temporal_v6_training" / "lstm_v6_pose_training_manifest.json",
        readiness_path=Path("evaluations") / "pose_optimization_readiness_20260705.json",
        comparison_path=Path("evaluations") / "pose_lstm_comparison_20260705.json",
        model_quality_path=Path("evaluations") / "pose_model_quality_20260705.json",
    )
    output = evidence_package_output if evidence_package_output.is_absolute() else ROOT / evidence_package_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_and_write_deployment_guard(
    *,
    evidence_package_path: Path,
    deployment_guard_output: Path,
) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.check_pose_deployment_guard import build_deployment_guard_report

    report = build_deployment_guard_report(
        env_file=Path(".env"),
        evidence_package_path=evidence_package_path,
        mode="production",
    )
    output = deployment_guard_output if deployment_guard_output.is_absolute() else ROOT / deployment_guard_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_and_write_launch_safety(*, launch_safety_output: Path) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.check_pose_launch_safety import build_launch_safety_report

    report = build_launch_safety_report()
    output = launch_safety_output if launch_safety_output.is_absolute() else ROOT / launch_safety_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_and_write_promotion_gate(
    *,
    evidence_package_path: Path,
    deployment_guard_path: Path,
    launch_safety_path: Path,
    promotion_gate_output: Path,
) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.check_pose_promotion_gate import build_promotion_gate_report

    report = build_promotion_gate_report(
        evidence_package_path=evidence_package_path,
        deployment_guard_path=deployment_guard_path,
        launch_safety_path=launch_safety_path,
    )
    output = promotion_gate_output if promotion_gate_output.is_absolute() else ROOT / promotion_gate_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def evidence_package_summary(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    return gate_summary(path, report, result_key="handoff_ready", label="handoff_ready")


def gate_summary(path: Path, report: dict[str, Any], *, result_key: str, label: str) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    blockers = summary.get("blockers") if isinstance(summary.get("blockers"), list) else []
    result = {
        "path": str(path),
        "blocker_gate_count": len(blockers),
        "next_action": summary.get("next_action"),
    }
    result[label] = bool(summary.get(result_key))
    return result


def next_action(status: str, failed_stage: str | None, *, mode: str = "production") -> str:
    if status == "dry_run":
        if mode == "dev-smoke":
            return "review planned local smoke commands, then run without --dry-run to generate baseline/pose/zero-pose LSTM evidence; production still requires live/CUDA/full-data gates"
        if mode == "dev-live":
            return "start the local service with the selected dev-live env profile, then run without --dry-run; production still requires CUDA/full-data and LSTM comparison gates"
        return "review planned commands, then run without --dry-run on a live service/CUDA environment"
    if status == "ok":
        if mode == "dev-smoke":
            return "dev smoke passed; do not promote until live runtime, CUDA provider A/B, full temporal data, and LSTM baseline/zero-pose comparison pass"
        if mode == "dev-live":
            return "dev-live gates passed; keep production_ready=false until CUDA runtime/provider/full-data and LSTM comparison gates pass"
        return "review readiness output and proceed only if production_ready=true"
    return {
        "runtime_probe": "start/restart the live service with the B pose profile and rerun runtime probe",
        "production_preflight": "fix production preflight blockers before running live runtime/provider/data/LSTM gates",
        "runtime_probe_dev_live": "start/restart the local live service with the requested dev-live pose profile and rerun runtime probe",
        "runtime_replay_dev_smoke": "fix replay runtime evidence before trusting local smoke checks",
        "pose_model_quality": "do not continue production promotion until the configured pose model matches metrics and beats the baseline quality gate",
        "pose_model_quality_dev_smoke": "dev model quality gate failed; keep using dev smoke only for chain diagnostics, not production model promotion",
        "pose_model_quality_dev_live": "dev-live model quality gate failed; keep using live probe only for runtime diagnostics, not production model promotion",
        "provider_ab": "run provider A/B on a CUDA-capable machine before selecting a production provider",
        "provider_ab_dev_smoke": "fix CPU provider smoke before continuing local pipeline checks",
        "temporal_export_ur_fall": "fix pose-aware UR Fall export before continuing",
        "temporal_export_gmdcsa24": "fix pose-aware GMDCSA24 export before continuing",
        "temporal_export_ur_fall_dev_smoke": "fix small pose-aware UR Fall export before continuing local checks",
        "temporal_pose_check": "fix exported pose-aware temporal sequences before building the LSTM manifest",
        "temporal_pose_check_dev_smoke": "fix dev-smoke pose-aware temporal sequences before building the manifest",
        "lstm_pose_manifest": "fix pose training gate before LSTM training",
        "lstm_pose_manifest_dev_smoke": "fix dev-smoke pose training gate before local readiness",
        "pose_lstm_train": "install/check ONNX export dependencies, then train/export the pose LSTM ONNX before evaluation",
        "pose_lstm_train_dev_smoke": "install/check ONNX export dependencies, then train/export the dev-smoke pose LSTM ONNX before local evaluation",
        "baseline_lstm_eval": "evaluate the bbox+motion baseline LSTM before building the pose comparison",
        "pose_lstm_eval": "train/evaluate the bbox+motion+pose LSTM before building the pose comparison",
        "baseline_lstm_eval_dev_smoke": "generate dev-smoke baseline LSTM metrics before local comparison",
        "pose_lstm_eval_dev_smoke": "train/evaluate dev-smoke pose LSTM metrics before local comparison",
        "lstm_pose_comparison": "inspect LSTM comparison blockers; do not promote pose LSTM until it beats baseline and zero-pose ablation without increasing false positives",
        "lstm_pose_comparison_dev_smoke": "inspect dev-smoke LSTM comparison blockers; equal zero-pose ablation metrics mean pose features are not yet helping the temporal model",
        "readiness": "inspect readiness blockers and resolve gates in order",
        "readiness_dev_smoke": "inspect dev-smoke readiness blockers; production still requires live/CUDA/full-data gates",
        "readiness_dev_live": "inspect dev-live readiness blockers; production still requires CUDA/full-data gates",
    }.get(str(failed_stage), "inspect failed stage output and rerun the pipeline")


def readiness_production_ready(stage_results: list[dict[str, Any]]) -> bool:
    readiness_stage = next((item for item in reversed(stage_results) if item.get("name") == "readiness"), None)
    if not readiness_stage:
        return False
    output = readiness_stage.get("output")
    if not output:
        return False
    path = ROOT / str(output)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return bool(summary.get("production_ready"))


def effective_summary_path(summary: str, mode: str) -> str:
    if mode == "dev-smoke" and summary == "evaluations/pose_optimization_pipeline_20260705.json":
        return "evaluations/pose_optimization_pipeline_dev_smoke_20260705.json"
    if mode == "dev-live" and summary == "evaluations/pose_optimization_pipeline_20260705.json":
        return "evaluations/pose_optimization_pipeline_dev_live_20260705.json"
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
