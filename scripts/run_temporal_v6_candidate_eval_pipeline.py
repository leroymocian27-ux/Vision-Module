from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_temporal_v6_acceptance import check_acceptance


DEFAULT_OUTPUT_ROOT = ROOT / "evaluations" / "fall_temporal_v6"
DEFAULT_SUMMARY = DEFAULT_OUTPUT_ROOT / "temporal_v6_candidate_eval_pipeline.json"

EVAL_SPECS = {
    "slow_fall": {
        "manifest": ROOT / "evaluations" / "fall_temporal_v6" / "slow_fall_review_manifest.json",
        "output_name": "slow_fall_review_stride8_v6_lstm_candidate",
        "frame_stride": 8,
    },
    "fp_regression": {
        "manifest": ROOT / "evaluations" / "fall_temporal_v6" / "fp_regression_manifest.json",
        "output_name": "fp_regression_stride8_v6_lstm_candidate",
        "frame_stride": 8,
    },
    "ur_mini": {
        "manifest": ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_ur_mini_manifest.json",
        "output_name": "ur_mini_regression_stride4_v6_lstm_candidate",
        "frame_stride": 4,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run temporal v6 candidate LSTM regression and acceptance pipeline.")
    parser.add_argument("--model-path", default="models/fall_lstm_v6.onnx", help="Candidate ONNX model path.")
    parser.add_argument("--schema-path", default="models/fall_lstm_v6_features.json", help="Candidate feature schema path.")
    parser.add_argument("--temporal-provider", default="shadow", choices=["shadow", "onnx_lstm"], help="Candidate temporal provider.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Root output directory for candidate regression runs.")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="Pipeline summary output JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Only print commands and do not run evaluations.")
    parser.add_argument("--skip-eval", action="store_true", help="Skip evaluations and check existing candidate comparison JSON files.")
    args = parser.parse_args()

    result = run_candidate_pipeline(
        model_path=args.model_path,
        schema_path=args.schema_path,
        temporal_provider=args.temporal_provider,
        output_root=Path(args.output_root),
        summary_path=Path(args.summary),
        dry_run=args.dry_run,
        skip_eval=args.skip_eval,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "error":
        return 1
    if result.get("acceptance_gate") and result["acceptance_gate"].get("passed") is False:
        return 1
    return 0


def run_candidate_pipeline(
    *,
    model_path: str,
    schema_path: str,
    temporal_provider: str,
    output_root: Path,
    summary_path: Path,
    dry_run: bool,
    skip_eval: bool,
) -> dict[str, Any]:
    commands = build_commands(
        model_path=model_path,
        schema_path=schema_path,
        temporal_provider=temporal_provider,
        output_root=output_root,
    )
    if dry_run:
        result = {
            "status": "dry_run",
            "model_path": model_path,
            "schema_path": schema_path,
            "temporal_provider": temporal_provider,
            "commands": commands,
            "acceptance_gate": None,
            "next_step": "Run without --dry-run after the candidate ONNX and schema exist.",
        }
        write_summary(summary_path, result)
        return result

    if not skip_eval:
        for command in commands.values():
            subprocess.run(command, check=True, cwd=str(ROOT))

    comparison_paths = candidate_comparison_paths(output_root)
    missing = [str(path) for path in comparison_paths.values() if not path.exists()]
    if missing:
        result = {
            "status": "error",
            "reason": "missing_candidate_comparison_json",
            "missing": missing,
            "commands": commands,
            "acceptance_gate": None,
            "next_step": "Run the candidate regression commands before checking acceptance.",
        }
        write_summary(summary_path, result)
        return result

    acceptance = check_acceptance(
        slow_fall_path=comparison_paths["slow_fall"],
        fp_path=comparison_paths["fp_regression"],
        ur_mini_path=comparison_paths["ur_mini"],
        min_slow_fall_recall=0.80,
        max_fp=0,
        max_duplicates=0,
        max_ur_mini_fp=0,
    )
    result = {
        "status": "ok",
        "model_path": model_path,
        "schema_path": schema_path,
        "temporal_provider": temporal_provider,
        "commands": commands,
        "comparison_paths": {key: str(value.resolve()) for key, value in comparison_paths.items()},
        "acceptance_gate": acceptance,
        "next_step": (
            "Candidate passes acceptance gates; review provenance before promotion."
            if acceptance["passed"]
            else "Candidate does not pass acceptance gates; inspect failed checks before promotion."
        ),
    }
    write_summary(summary_path, result)
    return result


def build_commands(
    *,
    model_path: str,
    schema_path: str,
    temporal_provider: str,
    output_root: Path,
) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}
    for name, spec in EVAL_SPECS.items():
        commands[name] = [
            sys.executable,
            str(ROOT / "scripts" / "run_temporal_v6_regression_eval.py"),
            "--manifest",
            str(spec["manifest"]),
            "--output-dir",
            str(output_root / str(spec["output_name"])),
            "--frame-stride",
            str(spec["frame_stride"]),
            "--temporal-provider",
            temporal_provider,
            "--temporal-model-path",
            model_path,
            "--temporal-schema-path",
            schema_path,
        ]
    return commands


def candidate_comparison_paths(output_root: Path) -> dict[str, Path]:
    return {
        name: output_root / str(spec["output_name"]) / "temporal_v6_regression_comparison.json"
        for name, spec in EVAL_SPECS.items()
    }


def write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
