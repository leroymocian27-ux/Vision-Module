from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "models" / "fall_lstm_v6.onnx"
DEFAULT_SCHEMA = ROOT / "models" / "fall_lstm_v6_features.json"
DEFAULT_METRICS = ROOT / "models" / "fall_lstm_v6_metrics.json"
DEFAULT_TRAIN_CONFIG = ROOT / "models" / "fall_lstm_v6_train_config.json"
DEFAULT_CANDIDATE_SUMMARY = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_candidate_eval_pipeline.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_promotion_readiness.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether temporal v6 LSTM candidate is safe to promote.")
    parser.add_argument("--model", default=str(DEFAULT_MODEL))
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    parser.add_argument("--metrics", default=str(DEFAULT_METRICS))
    parser.add_argument("--train-config", default=str(DEFAULT_TRAIN_CONFIG))
    parser.add_argument("--candidate-summary", default=str(DEFAULT_CANDIDATE_SUMMARY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    result = check_readiness(
        model_path=Path(args.model),
        schema_path=Path(args.schema),
        metrics_path=Path(args.metrics),
        train_config_path=Path(args.train_config),
        candidate_summary_path=Path(args.candidate_summary),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


def check_readiness(
    *,
    model_path: Path,
    schema_path: Path,
    metrics_path: Path,
    train_config_path: Path,
    candidate_summary_path: Path,
) -> dict[str, Any]:
    checks = [
        file_check("model_exists", model_path),
        file_check("schema_exists", schema_path),
        file_check("metrics_exists", metrics_path),
        file_check("train_config_exists", train_config_path),
        file_check("candidate_summary_exists", candidate_summary_path),
    ]
    metrics = load_json(metrics_path) if metrics_path.exists() else {}
    train_config = load_json(train_config_path) if train_config_path.exists() else {}
    candidate = load_json(candidate_summary_path) if candidate_summary_path.exists() else {}

    checks.append(metrics_provenance_check(metrics))
    checks.append(train_config_manifest_check(train_config))
    checks.append(candidate_eval_completed_check(candidate))
    checks.append(candidate_acceptance_check(candidate))

    ready = all(check["passed"] for check in checks)
    return {
        "ready": ready,
        "checks": checks,
        "artifacts": {
            "model": str(model_path.resolve()),
            "schema": str(schema_path.resolve()),
            "metrics": str(metrics_path.resolve()),
            "train_config": str(train_config_path.resolve()),
            "candidate_summary": str(candidate_summary_path.resolve()),
        },
        "promotion_env": promotion_env(model_path, schema_path) if ready else None,
        "next_step": (
            "Candidate is promotion-ready; apply env only after operational approval."
            if ready
            else "Do not promote. Complete missing artifacts, training provenance, candidate regression, and acceptance gates first."
        ),
    }


def file_check(name: str, path: Path) -> dict[str, Any]:
    return {
        "name": name,
        "passed": path.exists() and path.is_file(),
        "path": str(path.resolve()),
    }


def metrics_provenance_check(metrics: dict[str, Any]) -> dict[str, Any]:
    trained_from = metrics.get("trained_from_inputs")
    onnx_validation = metrics.get("onnx_validation") or {}
    return {
        "name": "metrics_training_provenance",
        "passed": isinstance(trained_from, list) and bool(trained_from) and onnx_validation.get("passed") is True,
        "trained_from_input_count": len(trained_from) if isinstance(trained_from, list) else 0,
        "onnx_validation": onnx_validation,
    }


def train_config_manifest_check(train_config: dict[str, Any]) -> dict[str, Any]:
    manifest = train_config.get("input_manifest")
    input_count = train_config.get("input_count")
    return {
        "name": "train_config_input_manifest",
        "passed": bool(manifest) and isinstance(input_count, int) and input_count > 0,
        "input_manifest": manifest,
        "input_count": input_count,
    }


def candidate_eval_completed_check(candidate: dict[str, Any]) -> dict[str, Any]:
    status = candidate.get("status")
    comparisons = candidate.get("comparison_paths") or {}
    return {
        "name": "candidate_regression_completed",
        "passed": status == "ok" and all(comparisons.get(key) for key in ["slow_fall", "fp_regression", "ur_mini"]),
        "status": status,
        "comparison_paths": comparisons,
    }


def candidate_acceptance_check(candidate: dict[str, Any]) -> dict[str, Any]:
    acceptance = candidate.get("acceptance_gate") or {}
    return {
        "name": "candidate_acceptance_passed",
        "passed": acceptance.get("passed") is True,
        "acceptance_passed": acceptance.get("passed"),
        "slow_fall_recall": ((acceptance.get("summary") or {}).get("slow_fall_recall")),
    }


def promotion_env(model_path: Path, schema_path: Path) -> dict[str, str]:
    return {
        "TEMPORAL_MODEL_PROVIDER": "shadow",
        "TEMPORAL_ONNX_MODEL_PATH": str(model_path),
        "TEMPORAL_FEATURE_SCHEMA_PATH": str(schema_path),
        "FALL_V6_SCORING_ENABLED": "true",
        "FALL_V6_DECISION_ENABLED": "true",
    }


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
