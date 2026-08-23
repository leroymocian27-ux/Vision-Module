from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import run_fall_hint_batch031_refine_pipeline as pipeline


def command_has_script(command: list[str], script_name: str) -> bool:
    return any(Path(part).name == script_name for part in command)


class FallHintBatch031PipelineTest(unittest.TestCase):
    def test_pipeline_waits_when_review_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "pipeline_project"
            calls: list[list[str]] = []

            def fake_run_json(command: list[str], cwd: Path) -> dict[str, object]:
                calls.append(command)
                return {
                    "batch_id": "batch_031_hardcase_audit",
                    "frame_count": 120,
                    "status_counts": {"draft": 120},
                    "reviewed_valid_count": 0,
                    "invalid_review_items": 0,
                    "ready_for_merge": False,
                }

            stdout = io.StringIO()
            with patch.object(pipeline, "run_json_command", side_effect=fake_run_json), patch.object(
                pipeline,
                "train_candidate",
                side_effect=AssertionError("training must not run before review is complete"),
            ), patch.object(
                pipeline,
                "run_command",
                side_effect=AssertionError("eval commands must not run before review is complete"),
            ), patch(
                "sys.argv",
                [
                    "run_fall_hint_batch031_refine_pipeline.py",
                    "--project",
                    str(project),
                    "--prepare-only",
                ],
            ), redirect_stdout(stdout):
                rc = pipeline.main()

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "waiting_for_manual_review")
            self.assertFalse(payload["validate_summary"]["ready_for_merge"])
            self.assertEqual(len(calls), 1)
            self.assertTrue((project / "pipeline_waiting_summary.json").exists())
            self.assertFalse((project / "pipeline_prepare_only_summary.json").exists())

    def test_pipeline_prepare_only_merges_without_training(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "pipeline_project"
            merged = root / "merged_dataset"
            calls: list[list[str]] = []

            def fake_run_json(command: list[str], cwd: Path) -> dict[str, object]:
                calls.append(command)
                if command_has_script(command, "validate_fall_hint_review_batch.py"):
                    return {
                        "batch_id": "batch_031_hardcase_audit",
                        "frame_count": 120,
                        "status_counts": {"reviewed": 120},
                        "reviewed_valid_count": 120,
                        "invalid_review_items": 0,
                        "ready_for_merge": True,
                    }
                if command_has_script(command, "extend_fall_hint_seed_finetune_with_review_batch.py"):
                    return {
                        "output_dataset": str(merged),
                        "added_batch_id": "batch_031_hardcase_audit",
                        "added_train_images": 120,
                        "val_test_preserved_from_base": True,
                    }
                raise AssertionError(f"unexpected command: {command}")

            stdout = io.StringIO()
            with patch.object(pipeline, "run_json_command", side_effect=fake_run_json), patch.object(
                pipeline,
                "train_candidate",
                side_effect=AssertionError("training must not run in prepare-only mode"),
            ), patch.object(
                pipeline,
                "run_command",
                side_effect=AssertionError("eval commands must not run in prepare-only mode"),
            ), patch(
                "sys.argv",
                [
                    "run_fall_hint_batch031_refine_pipeline.py",
                    "--project",
                    str(project),
                    "--merged-dataset",
                    str(merged),
                    "--prepare-only",
                    "--overwrite-merged",
                ],
            ), redirect_stdout(stdout):
                rc = pipeline.main()

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "prepared_only")
            self.assertEqual(payload["merge_summary"]["added_train_images"], 120)
            self.assertEqual(len(calls), 2)
            self.assertTrue((project / "pipeline_prepare_only_summary.json").exists())

    def test_pipeline_completed_runs_eval_and_threshold_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "pipeline_project"
            merged = root / "merged_dataset"
            (merged / "meta").mkdir(parents=True, exist_ok=True)
            (merged / "data.yaml").write_text("path: dummy\n", encoding="utf-8")
            (merged / "meta" / "empty_holdout_manifest.csv").write_text("image,label\n", encoding="utf-8")

            commands: list[list[str]] = []

            def fake_run_json(command: list[str], cwd: Path) -> dict[str, object]:
                if command_has_script(command, "validate_fall_hint_review_batch.py"):
                    return {
                        "batch_id": "batch_031_hardcase_audit",
                        "frame_count": 120,
                        "status_counts": {"reviewed": 120},
                        "reviewed_valid_count": 120,
                        "invalid_review_items": 0,
                        "ready_for_merge": True,
                    }
                if command_has_script(command, "extend_fall_hint_seed_finetune_with_review_batch.py"):
                    return {"added_train_images": 120, "val_test_preserved_from_base": True}
                raise AssertionError(f"unexpected JSON command: {command}")

            def fake_train_candidate(**_: object) -> dict[str, str]:
                run_dir = project / "candidate_d"
                weights = run_dir / "weights"
                weights.mkdir(parents=True, exist_ok=True)
                best = weights / "best.pt"
                best.write_text("fake-model", encoding="utf-8")
                return {
                    "run_dir": str(run_dir),
                    "best": str(best),
                    "last": str(weights / "last.pt"),
                    "model_init": "seed.pt",
                    "data": str(merged / "data.yaml"),
                }

            def fake_run_command(command: list[str], cwd: Path) -> None:
                commands.append(command)
                if command_has_script(command, "evaluate_fall_hint_candidates.py"):
                    eval_project = Path(command[command.index("--project") + 1])
                    eval_project.mkdir(parents=True, exist_ok=True)
                    (eval_project / "acceptance_decision.json").write_text(
                        json.dumps(
                            {
                                "accepted_candidates": [],
                                "recommended_candidate": "",
                            }
                        ),
                        encoding="utf-8",
                    )
                elif command_has_script(command, "evaluate_fall_hint_threshold_sweep.py"):
                    sweep_project = Path(command[command.index("--project") + 1])
                    sweep_project.mkdir(parents=True, exist_ok=True)
                    (sweep_project / "threshold_sweep_summary.json").write_text(
                        json.dumps({"models": {"candidate_d": "best.pt"}}),
                        encoding="utf-8",
                    )
                else:
                    raise AssertionError(f"unexpected command: {command}")

            stdout = io.StringIO()
            with patch.object(pipeline, "run_json_command", side_effect=fake_run_json), patch.object(
                pipeline,
                "train_candidate",
                side_effect=fake_train_candidate,
            ), patch.object(pipeline, "run_command", side_effect=fake_run_command), patch(
                "sys.argv",
                [
                    "run_fall_hint_batch031_refine_pipeline.py",
                    "--project",
                    str(project),
                    "--merged-dataset",
                    str(merged),
                    "--overwrite-merged",
                ],
            ), redirect_stdout(stdout):
                rc = pipeline.main()

            self.assertEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["status"], "completed")
            self.assertFalse(payload["runtime_model_replaced"])
            self.assertIn("candidate_d", payload["threshold_sweep_models"])
            self.assertEqual(len(commands), 2)
            self.assertTrue(command_has_script(commands[0], "evaluate_fall_hint_candidates.py"))
            self.assertTrue(command_has_script(commands[1], "evaluate_fall_hint_threshold_sweep.py"))
            self.assertTrue((project / "pipeline_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
