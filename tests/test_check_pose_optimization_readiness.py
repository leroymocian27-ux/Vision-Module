from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_pose_optimization_readiness import build_readiness_report as _build_readiness_report


def build_readiness_report(**kwargs):
    if "pose_model_quality" not in kwargs:
        model_quality = Path(tempfile.gettempdir()) / "vision_service_valid_pose_model_quality_test.json"
        write_json(model_quality, valid_model_quality())
        kwargs["pose_model_quality"] = model_quality
    return _build_readiness_report(**kwargs)


class CheckPoseOptimizationReadinessTest(unittest.TestCase):
    def test_report_passes_when_all_gates_have_production_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(
                runtime,
                {
                    "summary": {
                        "profile_name": "B",
                        "requested_duration_seconds": 120.0,
                        "ok_samples": 60,
                        "runtime_pose_valid_rate": 0.8,
                        "latest_result_pose_available_ratio": 0.7,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "pose_provider": "yolo11_legacy",
                        "pose_model_path": "models/pose_candidate.pt",
                        "gate": {"passed": True, "blockers": []},
                    }
                },
            )
            write_json(
                provider,
                {
                    "run_config": {
                        "device": "cuda:0",
                        "provider_model_paths": {"yolo11_legacy": "models/pose_candidate.pt"},
                    },
                    "summary": {
                        "yolo11_legacy": {
                            "pose_valid_rate": 0.85,
                            "pose_frame_ratio": 0.75,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 20.0,
                            "avg_skeleton_confidence": 0.82,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    }
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "rows": 1600,
                        "pose_available_true_rows": 1200,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                        "pose_available_missing_provider_rows": 0,
                        "pose_available_missing_model_rows": 0,
                        "dataset_counts": {"ur_fall": 800, "gmdcsa24": 800},
                        "label_counts": {"fall": 800, "non_fall": 800},
                    },
                    "checks": [{"name": "pose_available_ratio", "passed": True}],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "trainable_input_count": 2,
                    "train_command": "python scripts\\train_fall_lstm.py --input-manifest manifest.json",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertTrue(report["summary"]["production_ready"])
        self.assertEqual(report["summary"]["evidence_scope"], "production")
        self.assertEqual(report["summary"]["failed_gates"], [])

    def test_report_blocks_unreachable_runtime_and_cpu_provider_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab_cpu_dev.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(
                runtime,
                {
                    "summary": {
                        "ok_samples": 0,
                        "runtime_pose_valid_rate": 0.0,
                        "latest_result_pose_available_ratio": 0.0,
                        "gate": {"passed": False, "blockers": ["pose_valid_rate_below_0.70"]},
                    }
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cpu"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 40.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    }
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        self.assertIn("runtime", report["summary"]["failed_gates"])
        self.assertIn("provider", report["summary"]["failed_gates"])
        self.assertIn("runtime_status_unreachable", report["checks"]["runtime"]["blockers"])
        self.assertIn("provider_ab_is_cpu_dev_evidence", report["checks"]["provider"]["blockers"])

    def test_replay_runtime_is_blocked_unless_explicitly_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime_replay.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(
                runtime,
                {
                    "profiles": [
                        {
                            "profile_name": "B",
                            "published_frames": 6,
                            "pose_valid_rate": 1.0,
                            "published_pose_available_ratio": 1.0,
                            "inference_success_rate": 1.0,
                            "skip_reasons": {},
                            "settings": {"pose_provider": "yolo11_legacy"},
                            "gate": {"passed": True, "blockers": []},
                        }
                    ]
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo11_legacy": {
                            "pose_valid_rate": 0.85,
                            "pose_frame_ratio": 0.75,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 20.0,
                            "avg_skeleton_confidence": 0.82,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    }
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            blocked = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )
            allowed = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
                allow_replay_runtime=True,
            )

        self.assertFalse(blocked["summary"]["overall_ready"])
        self.assertIn("runtime_profile_is_replay_dev_evidence", blocked["checks"]["runtime"]["blockers"])
        self.assertTrue(allowed["checks"]["runtime"]["passed"])
        self.assertTrue(allowed["summary"]["overall_ready"])
        self.assertFalse(allowed["summary"]["production_ready"])
        self.assertIn("runtime", [item["gate"] for item in allowed["summary"]["non_production_reasons"]])

    def test_allowed_cpu_dev_evidence_passes_overall_but_not_production_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "pose_runtime_profile_B_local_service_cpu.json"
            provider = root / "pose_provider_ab_cpu_dev.json"
            temporal = root / "pose_temporal_sequences_check_dev_smoke.json"
            manifest = root / "lstm_v6_pose_dev_smoke_training_manifest.json"
            comparison = root / "pose_lstm_comparison_dev_smoke.json"
            write_json(
                runtime,
                {
                    "summary": {
                        "profile_name": "B_local_service_cpu",
                        "ok_samples": 9,
                        "runtime_pose_valid_rate": 1.0,
                        "latest_result_pose_available_ratio": 0.7,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "gate": {"passed": True, "blockers": []},
                    }
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cpu"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    }
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
                allow_cpu_provider=True,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        self.assertEqual(report["summary"]["evidence_scope"], "development")
        self.assertIn("provider", [item["gate"] for item in report["summary"]["non_production_reasons"]])

    def test_provider_ab_blocks_tiny_sample_even_when_quality_ratios_look_good(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 20,
                            "inference_attempt_count": 20,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("provider", report["summary"]["failed_gates"])
        blockers = report["checks"]["provider"]["metrics"]["candidates"][0]["blockers"]
        self.assertIn("provider_sampled_frames_below_120", blockers)
        self.assertIn("provider_inference_attempts_below_30", blockers)

    def test_model_quality_failure_blocks_readiness_even_when_runtime_and_data_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            model_quality = root / "pose_model_quality.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(
                model_quality,
                {
                    "summary": {
                        "passed": False,
                        "blockers": ["candidate_pose_map50_95_below_baseline"],
                        "warnings": [],
                    }
                },
            )
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                pose_model_quality=model_quality,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("model_quality", report["summary"]["failed_gates"])
        self.assertIn("candidate_pose_map50_95_below_baseline", report["checks"]["model_quality"]["blockers"])

    def test_provider_ab_blocks_high_latency_even_when_pose_quality_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "slow_pose": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 300.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        blockers = report["checks"]["provider"]["metrics"]["candidates"][0]["blockers"]
        self.assertIn("provider_avg_latency_above_250ms", blockers)

    def test_temporal_check_with_thin_single_dataset_export_is_not_production_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "pose_temporal_sequences_check_20260705.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(provider, valid_provider())
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "rows": 71,
                        "pose_available_true_rows": 64,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                        "dataset_counts": {"ur_fall": 71},
                        "label_counts": {"fall": 36, "non_fall": 35},
                    },
                    "checks": [],
                },
            )
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        reasons = report["checks"]["temporal_data"]["non_production_reasons"]
        self.assertIn("temporal_rows_below_1000", reasons)
        self.assertIn("temporal_pose_available_rows_below_100", reasons)
        self.assertIn("temporal_missing_required_datasets", reasons)
        self.assertEqual(report["checks"]["temporal_data"]["metrics"]["missing_required_datasets"], ["gmdcsa24"])

    def test_short_runtime_probe_with_formal_filename_is_not_production_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "pose_runtime_profile_B_20260705.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "pose_temporal_sequences_check_20260705.json"
            manifest = root / "lstm_v6_pose_training_manifest.json"
            comparison = root / "pose_lstm_comparison_20260705.json"
            write_json(
                runtime,
                {
                    "probe_config": {"duration_seconds": 8.0, "interval_seconds": 1.0},
                    "summary": {
                        "profile_name": "B",
                        "requested_duration_seconds": 8.0,
                        "ok_samples": 9,
                        "runtime_pose_valid_rate": 1.0,
                        "latest_result_pose_available_ratio": 0.7,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "gate": {"passed": True, "blockers": []},
                    },
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        self.assertIn(
            "runtime_probe_duration_below_120s",
            report["checks"]["runtime"]["non_production_reasons"],
        )

    def test_bcpu_runtime_profile_is_not_production_ready_even_with_long_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "pose_runtime_profile_Bcpu_20260705.json"
            provider = root / "pose_provider_ab_20260705.json"
            temporal = root / "pose_temporal_sequences_check_20260705.json"
            manifest = root / "lstm_v6_pose_training_manifest.json"
            comparison = root / "pose_lstm_comparison_20260705.json"
            write_json(
                runtime,
                {
                    "probe_config": {"duration_seconds": 120.0, "interval_seconds": 2.0},
                    "summary": {
                        "profile_name": "Bcpu",
                        "requested_duration_seconds": 120.0,
                        "ok_samples": 60,
                        "runtime_pose_valid_rate": 0.85,
                        "latest_result_pose_available_ratio": 0.8,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "gate": {"passed": True, "blockers": []},
                    },
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        self.assertIn("runtime", [item["gate"] for item in report["summary"]["non_production_reasons"]])
        self.assertIn(
            "runtime_profile_is_bcpu_dev_profile",
            report["checks"]["runtime"]["non_production_reasons"],
        )

    def test_lstm_comparison_blocks_when_pose_lstm_does_not_beat_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(
                runtime,
                {
                    "summary": {
                        "profile_name": "B",
                        "requested_duration_seconds": 120.0,
                        "ok_samples": 60,
                        "runtime_pose_valid_rate": 0.8,
                        "latest_result_pose_available_ratio": 0.7,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "gate": {"passed": True, "blockers": []},
                    }
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(
                comparison,
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.82, "false_positive_count": 2},
                        "pose_lstm": {"f1": 0.81, "false_positive_count": 2},
                    }
                },
            )

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("lstm_comparison", report["summary"]["failed_gates"])
        self.assertIn(
            "pose_lstm_not_better_than_baseline_f1",
            report["checks"]["lstm_comparison"]["blockers"],
        )

    def test_lstm_comparison_preserves_zero_pose_ablation_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(
                runtime,
                {
                    "summary": {
                        "profile_name": "B",
                        "requested_duration_seconds": 120.0,
                        "ok_samples": 60,
                        "runtime_pose_valid_rate": 0.8,
                        "latest_result_pose_available_ratio": 0.7,
                        "runtime_inference_success_rate": 1.0,
                        "skip_reason_delta": {},
                        "gate": {"passed": True, "blockers": []},
                    }
                },
            )
            write_json(
                provider,
                {
                    "run_config": {"device": "cuda:0"},
                    "summary": {
                        "yolo": {
                            "pose_valid_rate": 1.0,
                            "pose_frame_ratio": 1.0,
                            "sampled_frames": 160,
                            "inference_attempt_count": 120,
                            "avg_latency_ms": 80.0,
                            "avg_skeleton_confidence": 0.85,
                            "skip_reasons": {},
                            "errors": {},
                        }
                    },
                },
            )
            write_json(
                temporal,
                {
                    "passed": True,
                    "summary": {
                        "pose_available_true_rows": 10,
                        "known_pose_quality_ratio": 1.0,
                        "mismatch_available_rows": 0,
                    },
                    "checks": [],
                },
            )
            write_json(
                manifest,
                {
                    "require_pose": True,
                    "train_command": "python train",
                    "pose_training_gate": {"passed": True},
                },
            )
            write_json(
                comparison,
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.80, "false_positive_count": 2},
                        "pose_lstm": {"f1": 0.84, "false_positive_count": 2},
                        "pose_lstm_zero_pose_ablation": {"f1": 0.84, "false_positive_count": 2},
                        "comparison": {
                            "passed": False,
                            "blockers": ["pose_lstm_not_better_than_zero_pose_ablation"],
                        },
                    }
                },
            )

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn(
            "pose_lstm_not_better_than_zero_pose_ablation",
            report["checks"]["lstm_comparison"]["blockers"],
        )
        self.assertEqual(
            report["checks"]["lstm_comparison"]["metrics"]["pose_lstm_zero_pose_ablation"]["f1"],
            0.84,
        )

    def test_lstm_comparison_blocks_when_zero_pose_ablation_metrics_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(
                comparison,
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.80, "false_positive_count": 2},
                        "pose_lstm": {"f1": 0.84, "false_positive_count": 2},
                        "comparison": {"passed": True},
                    }
                },
            )

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn(
            "pose_lstm_zero_pose_ablation_metrics_missing",
            report["checks"]["lstm_comparison"]["blockers"],
        )

    def test_lstm_comparison_blocks_old_json_without_manifest_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "provider.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            model_quality = root / "model_quality.json"
            write_json(runtime, valid_runtime())
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            stale_comparison = valid_lstm_comparison()
            stale_comparison["summary"].pop("lstm_manifest")
            write_json(comparison, stale_comparison)
            write_json(model_quality, valid_model_quality())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
                pose_model_quality=model_quality,
            )

        self.assertIn("lstm_comparison", report["summary"]["failed_gates"])
        self.assertIn(
            "lstm_comparison_manifest_provenance_missing",
            report["checks"]["lstm_comparison"]["blockers"],
        )

    def test_lstm_comparison_blocks_when_pose_has_more_false_positives_than_zero_pose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(
                comparison,
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.80, "false_positive_count": 2},
                        "pose_lstm": {"f1": 0.86, "false_positive_count": 3},
                        "pose_lstm_zero_pose_ablation": {"f1": 0.82, "false_positive_count": 2},
                        "comparison": {"passed": True},
                    }
                },
            )

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn(
            "pose_lstm_false_positives_worse_than_baseline",
            report["checks"]["lstm_comparison"]["blockers"],
        )
        self.assertIn(
            "pose_lstm_false_positives_worse_than_zero_pose_ablation",
            report["checks"]["lstm_comparison"]["blockers"],
        )

    def test_evidence_consistency_blocks_when_runtime_provider_did_not_pass_provider_ab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            write_json(runtime, valid_runtime())
            provider_payload = valid_provider()
            provider_payload["summary"]["yolo"]["pose_valid_rate"] = 0.1
            write_json(provider, provider_payload)
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("evidence_consistency", report["summary"]["failed_gates"])
        self.assertIn(
            "runtime_pose_provider_did_not_pass_provider_ab",
            report["checks"]["evidence_consistency"]["blockers"],
        )

    def test_evidence_consistency_marks_missing_runtime_provider_as_non_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            runtime_payload = valid_runtime()
            runtime_payload["summary"].pop("pose_provider", None)
            write_json(runtime, runtime_payload)
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertTrue(report["summary"]["overall_ready"])
        self.assertFalse(report["summary"]["production_ready"])
        self.assertIn(
            "runtime_pose_provider_metadata_missing",
            report["checks"]["evidence_consistency"]["non_production_reasons"],
        )

    def test_evidence_consistency_blocks_when_runtime_model_differs_from_model_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            runtime_payload = valid_runtime()
            runtime_payload["summary"]["pose_model_path"] = "models/other_pose.pt"
            write_json(runtime, runtime_payload)
            write_json(provider, valid_provider())
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("evidence_consistency", report["summary"]["failed_gates"])
        self.assertIn(
            "runtime_pose_model_does_not_match_model_quality",
            report["checks"]["evidence_consistency"]["blockers"],
        )

    def test_evidence_consistency_blocks_when_provider_ab_model_differs_from_model_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            provider_payload = valid_provider()
            provider_payload["run_config"]["provider_model_paths"]["yolo"] = "models/other_pose.pt"
            write_json(runtime, valid_runtime())
            write_json(provider, provider_payload)
            write_json(temporal, valid_temporal())
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        self.assertIn("evidence_consistency", report["summary"]["failed_gates"])
        self.assertIn(
            "provider_ab_pose_model_does_not_match_model_quality",
            report["checks"]["evidence_consistency"]["blockers"],
        )

    def test_temporal_gate_blocks_available_pose_rows_without_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime.json"
            provider = root / "pose_provider_ab.json"
            temporal = root / "temporal.json"
            manifest = root / "manifest.json"
            comparison = root / "comparison.json"
            temporal_payload = valid_temporal()
            temporal_payload["summary"]["pose_available_missing_provider_rows"] = 2
            temporal_payload["summary"]["pose_available_missing_model_rows"] = 3
            write_json(runtime, valid_runtime())
            write_json(provider, valid_provider())
            write_json(temporal, temporal_payload)
            write_json(manifest, valid_manifest())
            write_json(comparison, valid_lstm_comparison())

            report = build_readiness_report(
                runtime_profile=runtime,
                provider_ab=provider,
                temporal_check=temporal,
                lstm_manifest=manifest,
                lstm_comparison=comparison,
            )

        self.assertFalse(report["summary"]["overall_ready"])
        blockers = report["checks"]["temporal_data"]["blockers"]
        self.assertIn("pose_available_missing_provider_metadata", blockers)
        self.assertIn("pose_available_missing_model_metadata", blockers)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def valid_runtime() -> dict:
    return {
        "summary": {
            "profile_name": "B",
            "requested_duration_seconds": 120.0,
            "ok_samples": 60,
            "runtime_pose_valid_rate": 0.8,
            "latest_result_pose_available_ratio": 0.7,
            "runtime_inference_success_rate": 1.0,
            "skip_reason_delta": {},
            "pose_provider": "yolo",
            "pose_model_path": "models/pose_candidate.pt",
            "gate": {"passed": True, "blockers": []},
        }
    }


def valid_provider() -> dict:
    return {
        "run_config": {
            "device": "cuda:0",
            "provider_model_paths": {"yolo": "models/pose_candidate.pt"},
        },
        "summary": {
            "yolo": {
                "pose_valid_rate": 1.0,
                "pose_frame_ratio": 1.0,
                "sampled_frames": 160,
                "inference_attempt_count": 120,
                "avg_latency_ms": 80.0,
                "avg_skeleton_confidence": 0.85,
                "skip_reasons": {},
                "errors": {},
            }
        },
    }


def valid_model_quality() -> dict:
    return {
        "summary": {
            "passed": True,
            "blockers": [],
            "warnings": [],
            "baseline_model": "yolo11n-pose.pt",
            "candidate_model": "models/pose_candidate.pt",
            "configured_model": "models/pose_candidate.pt",
            "baseline_pose_map50_95": 0.88,
            "candidate_pose_map50_95": 0.89,
            "delta_pose_map50_95": 0.01,
            "baseline_pose_recall": 0.95,
            "candidate_pose_recall": 0.95,
            "delta_pose_recall": 0.0,
        }
    }


def valid_temporal() -> dict:
    return {
        "passed": True,
        "summary": {
            "rows": 1600,
            "pose_available_true_rows": 1200,
            "known_pose_quality_ratio": 1.0,
            "mismatch_available_rows": 0,
            "pose_available_missing_provider_rows": 0,
            "pose_available_missing_model_rows": 0,
            "dataset_counts": {"ur_fall": 800, "gmdcsa24": 800},
            "label_counts": {"fall": 800, "non_fall": 800},
        },
        "checks": [],
    }


def valid_manifest() -> dict:
    return {
        "require_pose": True,
        "train_command": "python train",
        "pose_training_gate": {"passed": True},
    }


def valid_lstm_comparison() -> dict:
    return {
        "summary": {
            "baseline_lstm": {"f1": 0.80, "false_positive_count": 2},
            "pose_lstm": {"f1": 0.84, "false_positive_count": 2},
            "pose_lstm_zero_pose_ablation": {"f1": 0.82, "false_positive_count": 2},
            "lstm_manifest": {
                "sha256": "a" * 64,
                "schema_hashes": ["schema123"],
                "pose_provider_counts": {"yolo11_legacy": 100},
                "pose_model_path_counts": {"yolo11n-pose.pt": 100},
                "input_files_match_metrics": True,
                "metric_manifest_sha256s_match_manifest": True,
                "pose_train_config_manifest_sha256s_match_manifest": True,
            },
            "comparison": {"passed": True},
        }
    }


if __name__ == "__main__":
    unittest.main()
