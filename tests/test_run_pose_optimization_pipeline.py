from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts.run_pose_optimization_pipeline import (
    build_and_write_post_pipeline_gates,
    build_pipeline_stages,
    pipeline_exit_code,
    resolve_configured_pose_model,
    run_pipeline,
    write_pipeline_summary,
)


class RunPoseOptimizationPipelineTest(unittest.TestCase):
    def test_resolves_configured_pose_model_from_active_env_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "POSE_PROVIDER=yolo",
                        "YOLO_POSE_MODEL_PATH=models/custom_yolo_pose.pt",
                        "YOLO11_POSE_MODEL_PATH=models/should_not_use.pt",
                    ]
                ),
                encoding="utf-8",
            )

            resolved = resolve_configured_pose_model("__env__", env_file=env_file)

        self.assertEqual(resolved, "models/custom_yolo_pose.pt")

    def test_explicit_configured_pose_model_overrides_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "POSE_PROVIDER=yolo11_legacy",
                        "YOLO11_POSE_MODEL_PATH=models/env_pose.pt",
                    ]
                ),
                encoding="utf-8",
            )

            resolved = resolve_configured_pose_model("models/explicit_pose.pt", env_file=env_file)

        self.assertEqual(resolved, "models/explicit_pose.pt")

    def test_build_pipeline_stages_includes_production_gates_in_order(self) -> None:
        stages = build_pipeline_stages(
            profile_name="B",
            duration_seconds=120,
            interval_seconds=2,
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
            providers="yolo11_legacy,yolo",
            device="cuda:0",
            labels=Path("labels.jsonl"),
            temporal_output_dir=Path("data/pose"),
            frame_stride=2,
            model_version="v6_pose",
            epochs=20,
            lstm_stride=4,
            skip_runtime=False,
            skip_provider=False,
            skip_temporal_export=False,
            skip_lstm_manifest=False,
        )

        self.assertEqual(
            [item["name"] for item in stages],
            [
                "pose_model_quality",
                "production_preflight",
                "runtime_probe",
                "provider_ab",
                "temporal_export_ur_fall",
                "temporal_export_gmdcsa24",
                "temporal_pose_check",
                "lstm_pose_manifest",
                "pose_lstm_train",
                "baseline_lstm_eval",
                "pose_lstm_eval",
                "pose_lstm_zero_pose_eval",
                "lstm_pose_comparison",
                "readiness",
            ],
        )
        model_quality = command_for(stages, "pose_model_quality")
        self.assertIn("check_pose_model_quality.py", model_quality[1])
        self.assertIn("--configured-model", model_quality)
        self.assertIn("yolo11n-pose.pt", model_quality)
        preflight = command_for(stages, "production_preflight")
        self.assertIn("check_pose_production_preflight.py", preflight[1])
        self.assertIn("--device", preflight)
        self.assertIn("cuda:0", preflight)
        self.assertEqual(preflight[preflight.index("--duration-seconds") + 1], "120")
        self.assertEqual(preflight[preflight.index("--temporal-output-dir") + 1], "data\\pose")
        self.assertEqual(preflight[preflight.index("--lstm-eval-split") + 1], "test")
        provider = command_for(stages, "provider_ab")
        self.assertIn("--device", provider)
        self.assertIn("cuda:0", provider)
        manifest = command_for(stages, "lstm_pose_manifest")
        self.assertIn("--require-pose", manifest)
        train = command_for(stages, "pose_lstm_train")
        self.assertIn("train_fall_lstm.py", train[1])
        self.assertIn("--model-version", train)
        self.assertIn("v6_pose", train)
        baseline_eval = command_for(stages, "baseline_lstm_eval")
        self.assertIn("evaluate_fall_lstm_metrics.py", baseline_eval[1])
        self.assertIn("fall_lstm_v5.onnx", " ".join(baseline_eval))
        self.assertIn("--train-config", baseline_eval)
        self.assertIn("fall_lstm_v5_train_config.json", " ".join(baseline_eval))
        pose_eval = command_for(stages, "pose_lstm_eval")
        self.assertIn("evaluate_fall_lstm_metrics.py", pose_eval[1])
        self.assertIn("fall_lstm_v6_pose.onnx", " ".join(pose_eval))
        self.assertIn("--train-config", pose_eval)
        self.assertIn("fall_lstm_v6_pose_train_config.json", " ".join(pose_eval))
        pose_ablation = command_for(stages, "pose_lstm_zero_pose_eval")
        self.assertIn("--zero-pose-features", pose_ablation)
        self.assertIn("pose_lstm_zero_pose_eval_20260705.json", " ".join(pose_ablation))
        self.assertIn("--train-config", pose_ablation)
        comparison = command_for(stages, "lstm_pose_comparison")
        self.assertIn("build_pose_lstm_comparison.py", comparison[1])
        self.assertIn("baseline_lstm_eval_20260705.json", " ".join(comparison))
        self.assertIn("pose_lstm_eval_20260705.json", " ".join(comparison))
        self.assertIn("--pose-ablation-metrics", comparison)
        self.assertIn("pose_lstm_zero_pose_eval_20260705.json", " ".join(comparison))
        self.assertIn("--lstm-manifest", comparison)
        self.assertIn("lstm_v6_pose_training_manifest.json", " ".join(comparison))
        readiness = stages[-1]["command"]
        self.assertIn("--pose-model-quality", readiness)
        self.assertIn("pose_model_quality_20260705.json", " ".join(readiness))
        self.assertIn("--lstm-comparison", readiness)
        self.assertIn("pose_lstm_comparison_20260705.json", " ".join(readiness))

    def test_dry_run_marks_all_stages_planned(self) -> None:
        stages = [
            {"name": "runtime_probe", "command": ["python", "probe.py"], "output": "runtime.json"},
            {"name": "readiness", "command": ["python", "ready.py"], "output": "ready.json"},
        ]

        result = run_pipeline(stages, dry_run=True)

        self.assertEqual(result["summary"]["status"], "dry_run")
        self.assertEqual(result["summary"]["mode"], "production")
        self.assertEqual(result["summary"]["completed_stage_count"], 2)
        self.assertTrue(all(item["status"] == "planned" for item in result["stages"]))
        self.assertTrue(all(item["started_at"] is None for item in result["stages"]))
        self.assertTrue(all(item["finished_at"] is None for item in result["stages"]))
        self.assertTrue(all(item["duration_seconds"] is None for item in result["stages"]))

    def test_production_exit_code_requires_promotion_gate(self) -> None:
        result = {
            "summary": {
                "status": "ok",
                "production_ready": True,
                "post_pipeline_gates": {
                    "promotion_gate": {
                        "promotion_allowed": False,
                    }
                },
            }
        }

        self.assertEqual(pipeline_exit_code(result, mode="production", dry_run=False), 1)

        result["summary"]["post_pipeline_gates"]["promotion_gate"]["promotion_allowed"] = True
        self.assertEqual(pipeline_exit_code(result, mode="production", dry_run=False), 0)

    def test_non_production_exit_code_uses_stage_status(self) -> None:
        self.assertEqual(pipeline_exit_code({"summary": {"status": "ok"}}, mode="dev-smoke", dry_run=False), 0)
        self.assertEqual(pipeline_exit_code({"summary": {"status": "error"}}, mode="dev-smoke", dry_run=False), 1)

    def test_write_pipeline_summary_skips_evidence_package_for_dry_run(self) -> None:
        result = {
            "generated_at": "now",
            "summary": {"mode": "production", "status": "dry_run", "production_ready": False},
            "stages": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "pipeline.json"
            evidence_path = root / "evidence.json"

            written = write_pipeline_summary(
                result,
                summary_path=summary_path,
                mode="production",
                dry_run=True,
                evidence_package_output=evidence_path,
            )

            payload = json.loads(summary_path.read_text(encoding="utf-8"))

        self.assertIs(written, result)
        self.assertNotIn("evidence_package", payload["summary"])
        self.assertFalse(evidence_path.exists())

    def test_write_pipeline_summary_attaches_production_evidence_package(self) -> None:
        result = {
            "generated_at": "now",
            "summary": {"mode": "production", "status": "error", "production_ready": False},
            "stages": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "pipeline.json"
            evidence_path = root / "evidence.json"
            post_gates = {
                "evidence_package": {
                    "path": str(evidence_path),
                    "handoff_ready": False,
                    "blocker_gate_count": 1,
                    "next_action": "fix production preflight first",
                },
                "deployment_guard": {
                    "path": str(root / "deployment.json"),
                    "deployment_allowed": False,
                    "blocker_gate_count": 1,
                    "next_action": "fix deployment guard",
                },
                "launch_safety": {
                    "path": str(root / "launch.json"),
                    "launch_safety_passed": True,
                    "blocker_gate_count": 0,
                    "next_action": "launch safety passed",
                },
                "promotion_gate": {
                    "path": str(root / "promotion.json"),
                    "promotion_allowed": False,
                    "blocker_gate_count": 2,
                    "next_action": "generate production-ready evidence first",
                },
            }

            with patch(
                "scripts.run_pose_optimization_pipeline.build_and_write_post_pipeline_gates",
                return_value=post_gates,
            ) as mocked:
                written = write_pipeline_summary(
                    result,
                    summary_path=summary_path,
                    mode="production",
                    dry_run=False,
                    evidence_package_output=evidence_path,
                    deployment_guard_output=root / "deployment.json",
                    launch_safety_output=root / "launch.json",
                    promotion_gate_output=root / "promotion.json",
                )

            payload = json.loads(summary_path.read_text(encoding="utf-8"))

        mocked.assert_called_once_with(
            pipeline_path=summary_path,
            evidence_package_output=evidence_path,
            deployment_guard_output=root / "deployment.json",
            launch_safety_output=root / "launch.json",
            promotion_gate_output=root / "promotion.json",
        )
        self.assertIs(written, result)
        self.assertFalse(payload["summary"]["evidence_package"]["handoff_ready"])
        self.assertEqual(payload["summary"]["evidence_package"]["blocker_gate_count"], 1)
        self.assertEqual(payload["summary"]["evidence_package"]["path"], str(evidence_path))
        self.assertFalse(payload["summary"]["post_pipeline_gates"]["promotion_gate"]["promotion_allowed"])
        self.assertTrue(payload["summary"]["post_pipeline_gates"]["launch_safety"]["launch_safety_passed"])

    def test_post_pipeline_gates_pass_custom_output_paths_between_gates(self) -> None:
        calls = {}

        def fake_evidence(*, pipeline_path, evidence_package_output):
            calls["evidence"] = (pipeline_path, evidence_package_output)
            return {"summary": {"handoff_ready": False, "blockers": [{"gate": "preflight"}]}}

        def fake_deployment(*, evidence_package_path, deployment_guard_output):
            calls["deployment"] = (evidence_package_path, deployment_guard_output)
            return {"summary": {"deployment_allowed": False, "blockers": [{"gate": "evidence_package"}]}}

        def fake_launch(*, launch_safety_output):
            calls["launch"] = (launch_safety_output,)
            return {"summary": {"launch_safety_passed": True, "blockers": []}}

        def fake_promotion(*, evidence_package_path, deployment_guard_path, launch_safety_path, promotion_gate_output):
            calls["promotion"] = (
                evidence_package_path,
                deployment_guard_path,
                launch_safety_path,
                promotion_gate_output,
            )
            return {"summary": {"promotion_allowed": False, "blockers": [{"gate": "evidence_package"}]}}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pipeline = root / "custom_pipeline.json"
            evidence = root / "custom_evidence.json"
            deployment = root / "custom_deployment.json"
            launch = root / "custom_launch.json"
            promotion = root / "custom_promotion.json"

            with (
                patch("scripts.run_pose_optimization_pipeline.build_and_write_evidence_package", side_effect=fake_evidence),
                patch("scripts.run_pose_optimization_pipeline.build_and_write_deployment_guard", side_effect=fake_deployment),
                patch("scripts.run_pose_optimization_pipeline.build_and_write_launch_safety", side_effect=fake_launch),
                patch("scripts.run_pose_optimization_pipeline.build_and_write_promotion_gate", side_effect=fake_promotion),
            ):
                result = build_and_write_post_pipeline_gates(
                    pipeline_path=pipeline,
                    evidence_package_output=evidence,
                    deployment_guard_output=deployment,
                    launch_safety_output=launch,
                    promotion_gate_output=promotion,
                )

        self.assertEqual(calls["evidence"], (pipeline, evidence))
        self.assertEqual(calls["deployment"], (evidence, deployment))
        self.assertEqual(calls["launch"], (launch,))
        self.assertEqual(calls["promotion"], (evidence, deployment, launch, promotion))
        self.assertEqual(result["promotion_gate"]["path"], str(promotion))

    def test_build_dev_smoke_pipeline_uses_replay_cpu_and_dev_readiness(self) -> None:
        stages = build_pipeline_stages(
            profile_name="B",
            duration_seconds=120,
            interval_seconds=2,
            camera_id="camera_01",
            base_url="http://127.0.0.1:8000/api/v1",
            providers="yolo11_legacy,yolo",
            device="cuda:0",
            labels=Path("labels.jsonl"),
            temporal_output_dir=Path("data/temporal_sequences_pose_v1"),
            frame_stride=2,
            model_version="v6_pose",
            epochs=20,
            lstm_stride=4,
            skip_runtime=False,
            skip_provider=False,
            skip_temporal_export=False,
            skip_lstm_manifest=False,
            mode="dev-smoke",
            dev_video=Path("datasets/ur_fall/videos/fall-01.mp4"),
            dev_runtime_profiles="B",
            dev_max_sampled_frames=6,
            dev_provider_max_frames=5,
        )

        self.assertEqual(
            [item["name"] for item in stages],
            [
                "pose_model_quality_dev_smoke",
                "runtime_replay_dev_smoke",
                "provider_ab_dev_smoke",
                "temporal_export_ur_fall_dev_smoke",
                "temporal_pose_check_dev_smoke",
                "lstm_pose_manifest_dev_smoke",
                "pose_lstm_train_dev_smoke",
                "baseline_lstm_eval_dev_smoke",
                "pose_lstm_eval_dev_smoke",
                "pose_lstm_zero_pose_eval_dev_smoke",
                "lstm_pose_comparison_dev_smoke",
                "readiness_dev_smoke",
            ],
        )
        model_quality = command_for(stages, "pose_model_quality_dev_smoke")
        self.assertIn("check_pose_model_quality.py", model_quality[1])
        self.assertIn("--configured-model", model_quality)
        self.assertIn("yolo11n-pose.pt", model_quality)
        self.assertNotIn("models/pose_yolo_batch001_003_yolo11s_best.pt", model_quality)
        self.assertTrue(next(item for item in stages if item["name"] == "pose_model_quality_dev_smoke")["continue_on_failure"])
        runtime = command_for(stages, "runtime_replay_dev_smoke")
        self.assertIn("replay_pose_runtime_profiles.py", runtime[1])
        self.assertIn("--device", runtime)
        self.assertIn("cpu", runtime)
        temporal_export = command_for(stages, "temporal_export_ur_fall_dev_smoke")
        self.assertIn("--labels", temporal_export)
        self.assertIn("--split-override", temporal_export)
        self.assertEqual(temporal_export[temporal_export.index("--split-override") + 1], "unassigned")
        max_frames = int(temporal_export[temporal_export.index("--max-frames") + 1])
        frame_stride = int(temporal_export[temporal_export.index("--frame-stride") + 1])
        self.assertEqual(frame_stride, 4)
        self.assertGreaterEqual(max_frames // frame_stride, 80)
        self.assertEqual(temporal_export.count("--video-id"), 2)
        readiness = stages[-1]["command"]
        self.assertIn("--pose-model-quality", readiness)
        self.assertIn("pose_model_quality_dev_smoke_20260705.json", " ".join(readiness))
        self.assertIn("--allow-cpu-provider", readiness)
        self.assertIn("--allow-replay-runtime", readiness)
        self.assertIn("--lstm-comparison", readiness)
        self.assertIn("pose_lstm_comparison_dev_smoke_20260705.json", " ".join(readiness))
        train = command_for(stages, "pose_lstm_train_dev_smoke")
        self.assertIn("train_fall_lstm.py", train[1])
        self.assertIn("v6_pose_dev_smoke", " ".join(train))
        baseline_eval = command_for(stages, "baseline_lstm_eval_dev_smoke")
        self.assertIn("evaluate_fall_lstm_metrics.py", baseline_eval[1])
        self.assertIn("baseline_lstm_eval_dev_smoke_20260705.json", " ".join(baseline_eval))
        self.assertIn("--train-config", baseline_eval)
        pose_eval = command_for(stages, "pose_lstm_eval_dev_smoke")
        self.assertIn("evaluate_fall_lstm_metrics.py", pose_eval[1])
        self.assertIn("pose_lstm_eval_dev_smoke_20260705.json", " ".join(pose_eval))
        self.assertIn("--train-config", pose_eval)
        self.assertIn("fall_lstm_v6_pose_dev_smoke_train_config.json", " ".join(pose_eval))
        pose_ablation = command_for(stages, "pose_lstm_zero_pose_eval_dev_smoke")
        self.assertIn("--zero-pose-features", pose_ablation)
        self.assertIn("pose_lstm_zero_pose_eval_dev_smoke_20260705.json", " ".join(pose_ablation))
        self.assertIn("--train-config", pose_ablation)
        comparison = command_for(stages, "lstm_pose_comparison_dev_smoke")
        self.assertIn("build_pose_lstm_comparison.py", comparison[1])
        self.assertIn("baseline_lstm_eval_dev_smoke_20260705.json", " ".join(comparison))
        self.assertIn("pose_lstm_eval_dev_smoke_20260705.json", " ".join(comparison))
        self.assertIn("--pose-ablation-metrics", comparison)
        self.assertIn("pose_lstm_zero_pose_eval_dev_smoke_20260705.json", " ".join(comparison))
        self.assertIn("--lstm-manifest", comparison)
        self.assertIn("lstm_v6_pose_dev_smoke_training_manifest.json", " ".join(comparison))
        manifest = command_for(stages, "lstm_pose_manifest_dev_smoke")
        self.assertIn("--require-pose", manifest)
        self.assertIn("--skip-residual", manifest)

    def test_dev_smoke_summary_is_not_production_ready(self) -> None:
        stages = [{"name": "readiness_dev_smoke", "command": ["python", "ready.py"], "output": "ready.json"}]

        result = run_pipeline(stages, dry_run=True, mode="dev-smoke")

        self.assertEqual(result["summary"]["mode"], "dev-smoke")
        self.assertFalse(result["summary"]["production_ready"])
        self.assertIn("zero-pose", result["summary"]["next_action"])

    def test_gate_stage_failure_continues_to_readiness(self) -> None:
        stages = [
            {
                "name": "lstm_pose_comparison_dev_smoke",
                "command": ["python", "comparison.py"],
                "output": "comparison.json",
                "continue_on_failure": True,
            },
            {"name": "readiness_dev_smoke", "command": ["python", "ready.py"], "output": "ready.json"},
        ]
        completed = []

        def fake_run(command, cwd):
            completed.append(command)
            return type("Completed", (), {"returncode": 1 if "comparison.py" in command else 0})()

        with patch("scripts.run_pose_optimization_pipeline.subprocess.run", side_effect=fake_run):
            result = run_pipeline(stages, dry_run=False, mode="dev-smoke")

        self.assertEqual(result["summary"]["status"], "error")
        self.assertEqual(result["summary"]["failed_stage"], "lstm_pose_comparison_dev_smoke")
        self.assertIn("zero-pose ablation", result["summary"]["next_action"])
        self.assertEqual(result["summary"]["completed_stage_count"], 2)
        self.assertEqual(len(completed), 2)
        for item in result["stages"]:
            self.assertIsInstance(datetime.fromisoformat(item["started_at"]), datetime)
            self.assertIsInstance(datetime.fromisoformat(item["finished_at"]), datetime)
            self.assertIsInstance(item["duration_seconds"], float)
            self.assertGreaterEqual(item["duration_seconds"], 0.0)

    def test_non_continue_failure_marks_remaining_stages_skipped(self) -> None:
        stages = [
            {"name": "production_preflight", "command": ["python", "preflight.py"], "output": "preflight.json"},
            {"name": "runtime_probe", "command": ["python", "runtime.py"], "output": "runtime.json"},
            {"name": "readiness", "command": ["python", "ready.py"], "output": "ready.json"},
        ]
        completed = []

        def fake_run(command, cwd):
            completed.append(command)
            return type("Completed", (), {"returncode": 1})()

        with patch("scripts.run_pose_optimization_pipeline.subprocess.run", side_effect=fake_run):
            result = run_pipeline(stages, dry_run=False, mode="production")

        self.assertEqual(result["summary"]["status"], "error")
        self.assertEqual(result["summary"]["completed_stage_count"], 1)
        self.assertEqual(result["summary"]["executed_stage_count"], 1)
        self.assertEqual(result["summary"]["skipped_stage_count"], 2)
        self.assertEqual(len(completed), 1)
        self.assertEqual([item["status"] for item in result["stages"]], ["failed", "skipped", "skipped"])
        self.assertEqual(result["stages"][1]["skipped_due_to"], "production_preflight")
        self.assertIsNone(result["stages"][1]["started_at"])

    def test_build_dev_live_pipeline_uses_live_probe_and_cpu_readiness_without_replay(self) -> None:
        stages = build_pipeline_stages(
            profile_name="Bcpu",
            duration_seconds=12,
            interval_seconds=1,
            camera_id="camera_01",
            base_url="http://127.0.0.1:8010",
            providers="yolo11_legacy,yolo",
            device="cuda:0",
            labels=Path("labels.jsonl"),
            temporal_output_dir=Path("data/temporal_sequences_pose_v1"),
            frame_stride=2,
            model_version="v6_pose",
            epochs=20,
            lstm_stride=4,
            skip_runtime=False,
            skip_provider=False,
            skip_temporal_export=False,
            skip_lstm_manifest=False,
            mode="dev-live",
        )

        self.assertEqual(
            [item["name"] for item in stages],
            ["pose_model_quality_dev_live", "runtime_probe_dev_live", "readiness_dev_live"],
        )
        self.assertTrue(next(item for item in stages if item["name"] == "pose_model_quality_dev_live")["continue_on_failure"])
        model_quality = command_for(stages, "pose_model_quality_dev_live")
        self.assertIn("--configured-model", model_quality)
        self.assertIn("yolo11n-pose.pt", model_quality)
        self.assertNotIn("models/pose_yolo_batch001_003_yolo11s_best.pt", model_quality)
        runtime = command_for(stages, "runtime_probe_dev_live")
        self.assertIn("probe_pose_runtime_status.py", runtime[1])
        self.assertIn("--profile-name", runtime)
        self.assertIn("Bcpu", runtime)
        readiness = stages[-1]["command"]
        self.assertIn("--pose-model-quality", readiness)
        self.assertIn("pose_model_quality_dev_live_20260705.json", " ".join(readiness))
        self.assertIn("--allow-cpu-provider", readiness)
        self.assertNotIn("--allow-replay-runtime", readiness)
        self.assertIn("--lstm-comparison", readiness)
        self.assertIn("pose_lstm_comparison_dev_smoke_20260705.json", " ".join(readiness))
        self.assertIn("pose_provider_ab_dev_smoke_20260705.json", " ".join(readiness))

    def test_dev_live_summary_is_not_production_ready(self) -> None:
        stages = [{"name": "readiness_dev_live", "command": ["python", "ready.py"], "output": "ready.json"}]

        result = run_pipeline(stages, dry_run=True, mode="dev-live")

        self.assertEqual(result["summary"]["mode"], "dev-live")
        self.assertFalse(result["summary"]["production_ready"])
        self.assertIn("local service", result["summary"]["next_action"])

def command_for(stages: list[dict], name: str) -> list[str]:
    return next(item["command"] for item in stages if item["name"] == name)


if __name__ == "__main__":
    unittest.main()
