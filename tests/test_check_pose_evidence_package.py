from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.check_pose_evidence_package import REQUIRED_PRODUCTION_STAGES, build_evidence_package_report


class CheckPoseEvidencePackageTest(unittest.TestCase):
    def test_package_passes_when_all_production_evidence_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    },
                    "checks": {
                        "evidence_consistency": {
                            "metrics": {
                                "runtime_pose_provider": "yolo",
                                "runtime_pose_model": "models/pose_candidate.pt",
                                "provider_device": "cuda:0",
                                "provider_candidates": ["yolo"],
                                "passing_providers": ["yolo"],
                                "provider_model_paths": {"yolo": "models/pose_candidate.pt"},
                                "configured_pose_model": "models/pose_candidate.pt",
                            }
                        }
                    },
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())
            stage_outputs = {
                "production_preflight": preflight,
                "pose_model_quality": model_quality,
                "readiness": readiness,
                "lstm_pose_comparison": comparison,
            }
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": [
                        {
                            "name": name,
                            "status": "ok",
                            "output": str(stage_outputs.get(name, root / "evaluations" / f"{name}.json")),
                            "started_at": "2026-07-05T00:00:00+00:00",
                        }
                        for name in REQUIRED_PRODUCTION_STAGES
                    ],
                },
            )
            for name in REQUIRED_PRODUCTION_STAGES:
                if name not in stage_outputs:
                    write_json(root / "evaluations" / f"{name}.json", {"stage": name})

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        self.assertTrue(report["summary"]["handoff_ready"])
        self.assertEqual(report["summary"]["blockers"], [])
        consistency = report["checks"]["readiness"]["metrics"]["evidence_consistency"]
        self.assertEqual(consistency["runtime_pose_provider"], "yolo")
        self.assertEqual(consistency["runtime_pose_model"], "models/pose_candidate.pt")
        self.assertEqual(consistency["provider_device"], "cuda:0")
        self.assertEqual(consistency["passing_providers"], ["yolo"])

    def test_package_blocks_when_evidence_file_is_not_pipeline_stage_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            pipeline_readiness = write_json(
                root / "pipeline_readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            old_readiness = write_json(
                root / "old_readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())
            stage_outputs = {
                "production_preflight": preflight,
                "pose_model_quality": model_quality,
                "readiness": pipeline_readiness,
                "lstm_pose_comparison": comparison,
            }
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": [
                        {
                            "name": name,
                            "status": "ok",
                            "output": str(stage_outputs.get(name, root / "evaluations" / f"{name}.json")),
                            "started_at": "2026-07-05T00:00:00+00:00",
                        }
                        for name in REQUIRED_PRODUCTION_STAGES
                    ],
                },
            )
            for name in REQUIRED_PRODUCTION_STAGES:
                if name not in stage_outputs:
                    write_json(root / "evaluations" / f"{name}.json", {"stage": name})

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=old_readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("pipeline_evidence_output_mismatch:readiness", blockers)
        linked = report["checks"]["pipeline_evidence_links"]["metrics"]["linked_evidence"]
        readiness_link = next(item for item in linked if item["stage"] == "readiness")
        self.assertFalse(readiness_link["linked"])

    def test_package_blocks_fake_ready_readiness_without_consistency_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())
            pipeline = write_complete_pipeline(root, {
                "production_preflight": preflight,
                "pose_model_quality": model_quality,
                "readiness": readiness,
                "lstm_pose_comparison": comparison,
            })

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("readiness_evidence_consistency_runtime_pose_provider_missing", blockers)
        self.assertIn("readiness_evidence_consistency_runtime_pose_model_missing", blockers)
        self.assertIn("readiness_evidence_consistency_provider_device_missing", blockers)
        self.assertIn("readiness_evidence_consistency_passing_providers_missing", blockers)

    def test_package_blocks_when_readiness_consistency_provider_or_model_is_mismatched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    },
                    "checks": {
                        "evidence_consistency": {
                            "metrics": {
                                "runtime_pose_provider": "yolo",
                                "runtime_pose_model": "models/other_pose.pt",
                                "provider_device": "cuda:0",
                                "provider_candidates": ["yolo"],
                                "passing_providers": ["yolo11_legacy"],
                                "provider_model_paths": {"yolo": "models/other_pose.pt"},
                                "configured_pose_model": "models/pose_candidate.pt",
                            }
                        }
                    },
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())
            pipeline = write_complete_pipeline(root, {
                "production_preflight": preflight,
                "pose_model_quality": model_quality,
                "readiness": readiness,
                "lstm_pose_comparison": comparison,
            })

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("readiness_evidence_consistency_runtime_provider_not_in_passing_providers", blockers)
        self.assertIn("readiness_evidence_consistency_runtime_model_does_not_match_configured_model", blockers)
        self.assertIn("readiness_evidence_consistency_provider_model_does_not_match_configured_model", blockers)

    def test_package_blocks_when_temporal_or_manifest_are_not_pipeline_stage_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())
            pipeline_temporal = write_json(root / "pipeline_temporal.json", {"summary": {"rows": 1000}})
            old_temporal = write_json(root / "old_temporal.json", {"summary": {"rows": 1000}})
            pipeline_manifest = write_json(root / "pipeline_manifest.json", {"require_pose": True})
            old_manifest = write_json(root / "old_manifest.json", {"require_pose": True})
            stage_outputs = {
                "production_preflight": preflight,
                "pose_model_quality": model_quality,
                "temporal_pose_check": pipeline_temporal,
                "lstm_pose_manifest": pipeline_manifest,
                "readiness": readiness,
                "lstm_pose_comparison": comparison,
            }
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": [
                        {
                            "name": name,
                            "status": "ok",
                            "output": str(stage_outputs.get(name, root / "evaluations" / f"{name}.json")),
                            "started_at": "2026-07-05T00:00:00+00:00",
                        }
                        for name in REQUIRED_PRODUCTION_STAGES
                    ],
                },
            )
            for name in REQUIRED_PRODUCTION_STAGES:
                if name not in stage_outputs:
                    write_json(root / "evaluations" / f"{name}.json", {"stage": name})

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                temporal_check_path=old_temporal,
                lstm_manifest_path=old_manifest,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("pipeline_evidence_output_mismatch:temporal_pose_check", blockers)
        self.assertIn("pipeline_evidence_output_mismatch:lstm_pose_manifest", blockers)

    def test_current_style_blockers_are_preserved_for_handoff(self) -> None:
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
            model_quality = write_json(
                root / "model_quality.json",
                {
                    "summary": {
                        "passed": False,
                        "blockers": ["candidate_pose_map50_95_below_baseline"],
                        "warnings": [],
                    }
                },
            )
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "error",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": 1,
                        "failed_stage": "production_preflight",
                        "production_ready": False,
                    },
                    "stages": [{"name": "production_preflight", "status": "failed"}],
                },
            )
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": False,
                        "production_ready": False,
                        "evidence_scope": "development",
                        "blocking_reasons": [
                            {"gate": "runtime", "blockers": ["runtime_profile_missing"]},
                        ],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(
                root / "pose_lstm_comparison_dev_smoke.json",
                {
                    "summary": {
                        "baseline_lstm": {"f1": 0.75},
                        "pose_lstm": {"f1": 0.75},
                        "pose_lstm_zero_pose_ablation": {"f1": 0.75},
                        "comparison": {
                            "passed": False,
                            "blockers": ["pose_lstm_not_better_than_zero_pose_ablation"],
                        },
                    }
                },
            )

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("preflight:cuda_device:cuda_unavailable", blockers)
        self.assertIn("preflight:live_status:live_status_unreachable", blockers)
        self.assertIn("pose_model_quality_not_passed", blockers)
        self.assertIn("candidate_pose_map50_95_below_baseline", blockers)
        self.assertIn("pipeline_status_not_ok", blockers)
        self.assertIn("readiness_evidence_scope_is_not_production", blockers)
        self.assertIn("runtime_profile_missing", " ".join(blockers))
        self.assertIn("lstm_comparison_path_looks_like_dev_evidence", blockers)
        self.assertIn("pose_lstm_not_better_than_zero_pose_ablation", blockers)

    def test_pipeline_blocks_when_successful_stage_output_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            missing_output = root / "missing_runtime.json"
            stages = [
                {
                    "name": name,
                    "status": "ok",
                    "output": str(missing_output if name == "runtime_probe" else root / f"{name}.json"),
                    "started_at": "2026-07-05T00:00:00+00:00",
                }
                for name in REQUIRED_PRODUCTION_STAGES
            ]
            for item in stages:
                if item["name"] != "runtime_probe":
                    write_json(Path(item["output"]), {"stage": item["name"]})
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": stages,
                },
            )
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        pipeline_metrics = report["checks"]["pipeline"]["metrics"]
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("pipeline_stage_outputs_missing", blockers)
        self.assertEqual(pipeline_metrics["missing_stage_outputs"][0]["stage"], "runtime_probe")

    def test_pipeline_blocks_when_successful_stage_output_is_older_than_stage_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            stale_output = root / "runtime_probe.json"
            stage_started_at = datetime.now(timezone.utc)
            stale_mtime = stage_started_at - timedelta(seconds=60)
            stages = [
                {
                    "name": name,
                    "status": "ok",
                    "output": str(stale_output if name == "runtime_probe" else root / f"{name}.json"),
                    "started_at": stage_started_at.isoformat(),
                }
                for name in REQUIRED_PRODUCTION_STAGES
            ]
            for item in stages:
                output = write_json(Path(item["output"]), {"stage": item["name"]})
                if item["name"] == "runtime_probe":
                    os.utime(output, (stale_mtime.timestamp(), stale_mtime.timestamp()))
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": stages,
                },
            )
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        pipeline_metrics = report["checks"]["pipeline"]["metrics"]
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("pipeline_stage_outputs_stale", blockers)
        self.assertEqual(pipeline_metrics["stale_stage_outputs"][0]["stage"], "runtime_probe")

    def test_pipeline_blocks_when_successful_stage_has_no_start_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": True, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            stages = [
                {
                    "name": name,
                    "status": "ok",
                    "output": str(root / f"{name}.json"),
                    "started_at": None if name == "runtime_probe" else "2026-07-05T00:00:00+00:00",
                }
                for name in REQUIRED_PRODUCTION_STAGES
            ]
            for item in stages:
                write_json(Path(item["output"]), {"stage": item["name"]})
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "ok",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "failed_stage": None,
                        "production_ready": True,
                    },
                    "stages": stages,
                },
            )
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": True,
                        "production_ready": True,
                        "evidence_scope": "production",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        pipeline_metrics = report["checks"]["pipeline"]["metrics"]
        self.assertFalse(report["summary"]["handoff_ready"])
        self.assertIn("pipeline_stage_timestamps_missing", blockers)
        self.assertEqual(pipeline_metrics["missing_stage_timestamps"][0]["stage"], "runtime_probe")

    def test_pipeline_reports_skipped_stages_separately_from_missing_required_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preflight = write_json(root / "preflight.json", {"summary": {"passed": False, "blockers": []}})
            model_quality = write_json(root / "model_quality.json", valid_model_quality())
            stages = []
            for name in REQUIRED_PRODUCTION_STAGES:
                if name == "pose_model_quality":
                    stages.append({"name": name, "status": "ok", "output": str(model_quality), "started_at": "2026-07-05T00:00:00+00:00"})
                elif name == "production_preflight":
                    stages.append({"name": name, "status": "failed", "output": str(preflight)})
                else:
                    stages.append(
                        {
                            "name": name,
                            "status": "skipped",
                            "output": str(root / f"{name}.json"),
                            "skipped_due_to": "production_preflight",
                        }
                    )
            pipeline = write_json(
                root / "pipeline.json",
                {
                    "summary": {
                        "mode": "production",
                        "status": "error",
                        "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                        "completed_stage_count": 2,
                        "executed_stage_count": 2,
                        "skipped_stage_count": len(REQUIRED_PRODUCTION_STAGES) - 2,
                        "failed_stage": "production_preflight",
                        "production_ready": False,
                    },
                    "stages": stages,
                },
            )
            readiness = write_json(
                root / "readiness.json",
                {
                    "summary": {
                        "overall_ready": False,
                        "production_ready": False,
                        "evidence_scope": "development",
                        "blocking_reasons": [],
                        "non_production_reasons": [],
                    }
                },
            )
            comparison = write_json(root / "comparison.json", valid_comparison())

            report = build_evidence_package_report(
                preflight_path=preflight,
                model_quality_path=model_quality,
                pipeline_path=pipeline,
                readiness_path=readiness,
                comparison_path=comparison,
            )

        blockers = flatten_blockers(report)
        pipeline_metrics = report["checks"]["pipeline"]["metrics"]
        self.assertIn("pipeline_has_skipped_stages", blockers)
        self.assertNotIn("pipeline_missing_required_stages", blockers)
        self.assertEqual(pipeline_metrics["skipped_stage_count"], len(REQUIRED_PRODUCTION_STAGES) - 2)
        self.assertEqual(pipeline_metrics["skipped_stages"][0], "runtime_probe")


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
        }
    }


def valid_comparison() -> dict:
    return {
        "summary": {
            "baseline_lstm": {"f1": 0.80, "false_positive_count": 2},
            "pose_lstm": {"f1": 0.86, "false_positive_count": 2},
            "pose_lstm_zero_pose_ablation": {"f1": 0.82, "false_positive_count": 2},
            "comparison": {
                "passed": True,
                "blockers": [],
                "false_positive_delta": 0,
                "zero_pose_ablation_false_positive_delta": 0,
            },
        }
    }


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_complete_pipeline(root: Path, stage_outputs: dict[str, Path]) -> Path:
    pipeline = write_json(
        root / "pipeline.json",
        {
            "summary": {
                "mode": "production",
                "status": "ok",
                "stage_count": len(REQUIRED_PRODUCTION_STAGES),
                "completed_stage_count": len(REQUIRED_PRODUCTION_STAGES),
                "failed_stage": None,
                "production_ready": True,
            },
            "stages": [
                {
                    "name": name,
                    "status": "ok",
                    "output": str(stage_outputs.get(name, root / "evaluations" / f"{name}.json")),
                    "started_at": "2026-07-05T00:00:00+00:00",
                }
                for name in REQUIRED_PRODUCTION_STAGES
            ],
        },
    )
    for name in REQUIRED_PRODUCTION_STAGES:
        if name not in stage_outputs:
            write_json(root / "evaluations" / f"{name}.json", {"stage": name})
    return pipeline


def flatten_blockers(report: dict) -> list[str]:
    result: list[str] = []
    for item in report["summary"]["blockers"]:
        result.extend(item["blockers"])
    return result


if __name__ == "__main__":
    unittest.main()
