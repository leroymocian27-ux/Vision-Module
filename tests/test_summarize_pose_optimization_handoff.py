from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_pose_optimization_handoff import build_handoff_markdown


class SummarizePoseOptimizationHandoffTest(unittest.TestCase):
    def test_builds_staff_handoff_with_blockers_and_ablation_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(
                root / "preflight.json",
                {
                    "summary": {
                        "passed": False,
                        "blockers": [
                            {"gate": "cuda_device", "blocker": "cuda_unavailable"},
                            {"gate": "live_status", "blocker": "live_status_unreachable"},
                        ],
                    }
                },
            )
            production_pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "status": "error",
                        "stage_count": 13,
                        "completed_stage_count": 1,
                        "failed_stage": "production_preflight",
                    }
                },
            )
            model_quality = write_json(
                root / "model_quality.json",
                {
                    "summary": {
                        "passed": False,
                        "blockers": ["candidate_pose_map50_95_below_baseline"],
                        "warnings": [],
                        "baseline_model": "yolo11n-pose.pt",
                        "candidate_model": "models/pose_yolo_batch001_003_yolo11s_best.pt",
                        "baseline_pose_map50_95": 0.883491,
                        "candidate_pose_map50_95": 0.848643,
                        "delta_pose_map50_95": -0.034848,
                        "next_action": "do not promote this pose model",
                    }
                },
            )
            candidate_model_quality = write_json(
                root / "candidate_model_quality.json",
                {
                    "summary": {
                        "passed": False,
                        "blockers": ["candidate_pose_map50_95_below_baseline"],
                        "warnings": [],
                        "candidate_model": "models/pose_yolo_batch001_003_yolo11s_best.pt",
                        "candidate_pose_map50_95": 0.848643,
                    }
                },
            )
            dev_readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": False,
                        "production_ready": False,
                        "failed_gates": ["lstm_comparison"],
                    },
                    "checks": {
                        "temporal_data": {
                            "metrics": {
                                "pose_available_true_ratio": 0.9014,
                            }
                        }
                    },
                },
            )
            dev_comparison = write_json(
                root / "comparison.json",
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.75, "false_positive_count": 2, "precision": 0.6, "recall": 1.0},
                        "pose_lstm": {"f1": 0.75, "false_positive_count": 2, "precision": 0.6, "recall": 1.0},
                        "pose_lstm_zero_pose_ablation": {
                            "f1": 0.75,
                            "false_positive_count": 2,
                            "precision": 0.6,
                            "recall": 1.0,
                        },
                        "comparison": {
                            "passed": False,
                            "blockers": [
                                "pose_lstm_not_better_than_baseline_f1",
                                "pose_lstm_not_better_than_zero_pose_ablation",
                            ],
                        },
                        "lstm_manifest": {
                            "sha256": "abc123",
                            "metric_manifest_sha256s_match_manifest": True,
                            "pose_train_config_manifest_sha256s_match_manifest": True,
                        },
                    }
                },
            )
            evidence_package = write_json(
                root / "evidence_package.json",
                {
                    "summary": {
                        "handoff_ready": False,
                        "blockers": [
                            {
                                "gate": "preflight",
                                "blockers": [
                                    "preflight_not_passed",
                                    "preflight:cuda_device:cuda_unavailable",
                                ],
                            }
                        ],
                        "warnings": [],
                        "next_action": "fix production preflight first",
                    }
                },
            )
            deployment_guard = write_json(
                root / "deployment_guard.json",
                {
                    "summary": {
                        "deployment_allowed": False,
                        "blockers": [
                            {
                                "gate": "evidence_package",
                                "blockers": ["pose_enabled_without_handoff_ready_evidence"],
                            }
                        ],
                        "warnings": [],
                        "next_action": "run the production pose optimization pipeline",
                    },
                    "checks": {
                        "evidence_package": {
                            "metrics": {
                                "active_pose_provider": "yolo11_legacy",
                                "evidence_pose_provider": "yolo11_legacy",
                                "active_pose_model": "yolo11n-pose.pt",
                                "evidence_pose_model": "yolo11n-pose.pt",
                            }
                        }
                    },
                },
            )
            launch_safety = write_json(
                root / "launch_safety.json",
                {
                    "summary": {
                        "launch_safety_passed": True,
                        "blockers": [],
                        "warnings": [
                            {
                                "script": "scripts\\debug_restart_matrix.py",
                                "warnings": ["debug_pose_launch_not_production_evidence"],
                            }
                        ],
                        "next_action": "launch safety passed with debug warnings",
                    }
                },
            )
            promotion_gate = write_json(
                root / "promotion_gate.json",
                {
                    "summary": {
                        "promotion_allowed": False,
                        "blockers": [
                            {
                                "gate": "evidence_package",
                                "blockers": ["evidence_package_handoff_ready_false"],
                            }
                        ],
                        "warnings": [],
                        "next_action": "generate production-ready evidence first",
                    }
                },
            )
            dry_run = write_json(
                root / "dry_run.json",
                {
                    "stages": [
                        {"name": "production_preflight", "output": "evaluations\\pose_production_preflight_20260705.json"},
                        {"name": "runtime_probe", "output": "evaluations\\pose_runtime_profile_B_20260705.json"},
                    ]
                },
            )

            markdown = build_handoff_markdown(
                preflight_path=preflight,
                production_pipeline_path=production_pipeline,
                dev_readiness_path=dev_readiness,
                dev_comparison_path=dev_comparison,
                model_quality_path=model_quality,
                candidate_model_quality_path=candidate_model_quality,
                evidence_package_path=evidence_package,
                deployment_guard_path=deployment_guard,
                launch_safety_path=launch_safety,
                promotion_gate_path=promotion_gate,
                production_dry_run_path=dry_run,
                dev_smoke_dry_run_path=None,
                dev_live_dry_run_path=None,
            )

        self.assertIn("cuda_unavailable", markdown)
        self.assertIn("live_status_unreachable", markdown)
        self.assertIn("姿态模型质量门", markdown)
        self.assertIn("candidate_pose_map50_95_below_baseline", markdown)
        self.assertIn("0.8486", markdown)
        self.assertIn("0.8835", markdown)
        self.assertIn("候选模型更快不等于更好", markdown)
        self.assertIn("默认生产启动应回退到 `yolo11n-pose.pt` baseline", markdown)
        self.assertIn("候选模型诊断", markdown)
        self.assertIn("python scripts\\check_pose_model_quality.py", markdown)
        self.assertIn("--configured-model yolo11n-pose.pt --output evaluations\\pose_model_quality_20260705.json", markdown)
        self.assertIn(
            "--configured-model models\\pose_yolo_batch001_003_yolo11s_best.pt --output evaluations\\pose_model_quality_yolo11s_candidate_20260705.json",
            markdown,
        )
        self.assertIn("pose_lstm_not_better_than_zero_pose_ablation", markdown)
        self.assertIn("| F1 | 0.75 | 0.75 | 0.75 |", markdown)
        self.assertIn("model quality：`passed=False`", markdown)
        self.assertIn("provider A/B：`passed=False`", markdown)
        self.assertIn("CPU 小样本跑得动，不等于生产性能合格", markdown)
        self.assertIn("LSTM manifest hash：`abc123`", markdown)
        self.assertIn("metrics input manifest 对齐：`True`", markdown)
        self.assertIn("pose/zero-pose train_config manifest 对齐：`True`", markdown)
        self.assertIn("证据链不再散装", markdown)
        self.assertIn("python scripts\\run_pose_optimization_pipeline.py --mode production", markdown)
        self.assertIn("production pipeline 会读取 `.env` 当前 `POSE_PROVIDER` 对应的姿态模型路径", markdown)
        self.assertIn("production pipeline 会在非 dry-run 模式下自动生成并回填后置门禁", markdown)
        self.assertIn("status=ok` stage 的 `output` 文件是否真实存在", markdown)
        self.assertIn("产物修改时间不早于该 stage 的 `started_at`", markdown)
        self.assertIn("拿旧 JSON 冒充本轮新证据", markdown)
        self.assertIn("退出码也受 `promotion_allowed` 约束", markdown)
        self.assertIn("production_preflight", markdown)
        self.assertIn("不能宣布生产可用", markdown)
        self.assertIn("交接包校验", markdown)
        self.assertIn("handoff_ready：`False`", markdown)
        self.assertIn("生产预检必须检查 `.env` active pose provider/model/device", markdown)
        self.assertIn("live `/status` 里的 `pose_provider` 和 `pose_model_path` 必须匹配 `.env` active 配置", markdown)
        self.assertIn("temporal pose check、LSTM manifest、LSTM comparison、readiness 必须是同一轮 production pipeline 对应 stage 的 `output`", markdown)
        self.assertIn("模型质量门默认必须跟随 `.env` 当前 `POSE_PROVIDER` 的 active model", markdown)
        self.assertIn("不能只相信 readiness summary 自称 ready", markdown)
        self.assertIn("runtime pose provider/model、provider device、passing providers、provider model paths、configured model", markdown)
        self.assertIn("python scripts\\check_pose_evidence_package.py", markdown)
        self.assertIn("部署门禁", markdown)
        self.assertIn("deployment_allowed：`False`", markdown)
        self.assertIn("pose_enabled_without_handoff_ready_evidence", markdown)
        self.assertIn("python scripts\\check_pose_deployment_guard.py", markdown)
        self.assertIn("scripts\\start_current_camera.py", markdown)
        self.assertIn("`app\\main.py` 的 FastAPI lifespan 也已接入同一套 deployment guard", markdown)
        self.assertIn("直接 `uvicorn app.main:app` 也不能绕过姿态生产门禁", markdown)
        self.assertIn("scripts\\start_phase5_test.py", markdown)
        self.assertIn("active/evidence provider：`yolo11_legacy` / `yolo11_legacy`", markdown)
        self.assertIn("active/evidence model：`yolo11n-pose.pt` / `yolo11n-pose.pt`", markdown)
        self.assertIn("过审一套、启动另一套会被拦", markdown)
        self.assertIn("`POSE_PROVIDER` 与 handoff evidence 里的 runtime pose provider 一致", markdown)
        self.assertIn("FastAPI 服务本体启动时也必须执行 deployment guard", markdown)
        self.assertIn("--skip-pose-deployment-guard", markdown)
        self.assertIn("启动入口安全审计", markdown)
        self.assertIn("launch_safety_passed：`True`", markdown)
        self.assertIn("debug_pose_launch_not_production_evidence", markdown)
        self.assertIn("python scripts\\check_pose_launch_safety.py", markdown)
        self.assertIn("生产推广总门禁", markdown)
        self.assertIn("promotion_allowed：`False`", markdown)
        self.assertIn("evidence_package_handoff_ready_false", markdown)
        self.assertIn("python scripts\\check_pose_promotion_gate.py", markdown)
        self.assertIn("不能只相信 comparison 文件自称 passed", markdown)
        self.assertIn("采样帧数、姿态推理次数、平均延迟、骨架平均置信度", markdown)
        self.assertIn("runtime、provider A/B、model quality 必须描述同一套姿态配置", markdown)
        self.assertIn("runtime probe 里的 `pose_model_path` 必须和 model quality 的 `configured_model` 一致", markdown)
        self.assertIn("provider A/B 的 `provider_model_paths` 也必须和 model quality 的 `configured_model` 对齐", markdown)
        self.assertIn("可用骨架行是否带 `pose_runtime.pose_provider` 和 `pose_runtime.pose_model_path`", markdown)
        self.assertIn("`--require-pose` 的 LSTM manifest 也必须二次检查可用骨架行", markdown)
        self.assertIn("LSTM comparison 必须记录 `lstm_manifest.sha256`", markdown)
        self.assertIn("三份 metrics 自报的 `input_manifest.sha256` 必须等于 comparison 传入的 manifest", markdown)
        self.assertIn("pose/zero-pose metrics 的 `train_config.input_manifest_sha256` 也必须等于同一份 manifest", markdown)
        self.assertIn("不能是几十行单数据集冒烟样本", markdown)
        self.assertIn("覆盖 `ur_fall`、`gmdcsa24`、`fall`、`non_fall`", markdown)
        self.assertIn("pose mAP50-95 低于 baseline 的候选", markdown)


def write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
