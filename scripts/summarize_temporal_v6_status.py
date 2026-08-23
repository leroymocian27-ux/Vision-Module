from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEW_PACKET = ROOT / "data" / "temporal_v6_review" / "professor_review_packet" / "review_packet_summary.json"
DEFAULT_POST_REVIEW = ROOT / "data" / "temporal_v6_training" / "post_review_pipeline_summary.json"
DEFAULT_CANDIDATE = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_candidate_eval_pipeline.json"
DEFAULT_ACCEPTANCE = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_acceptance_gate.json"
DEFAULT_PROMOTION = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_promotion_readiness.json"
DEFAULT_OUTPUT = ROOT / "evaluations" / "fall_temporal_v6" / "temporal_v6_master_status.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize temporal v6 implementation, review, training, and promotion status.")
    parser.add_argument("--review-packet", default=str(DEFAULT_REVIEW_PACKET))
    parser.add_argument("--post-review", default=str(DEFAULT_POST_REVIEW))
    parser.add_argument("--candidate", default=str(DEFAULT_CANDIDATE))
    parser.add_argument("--acceptance", default=str(DEFAULT_ACCEPTANCE))
    parser.add_argument("--promotion", default=str(DEFAULT_PROMOTION))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    result = summarize_status(
        review_packet_path=Path(args.review_packet),
        post_review_path=Path(args.post_review),
        candidate_path=Path(args.candidate),
        acceptance_path=Path(args.acceptance),
        promotion_path=Path(args.promotion),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["overall_status"] == "complete" else 1


def summarize_status(
    *,
    review_packet_path: Path,
    post_review_path: Path,
    candidate_path: Path,
    acceptance_path: Path,
    promotion_path: Path,
) -> dict[str, Any]:
    review_packet = load_json_if_exists(review_packet_path)
    post_review = load_json_if_exists(post_review_path)
    candidate = load_json_if_exists(candidate_path)
    acceptance = load_json_if_exists(acceptance_path)
    promotion = load_json_if_exists(promotion_path)

    stages = {
        "review_packet": review_stage(review_packet),
        "post_review_training_data": post_review_stage(post_review),
        "candidate_eval": candidate_stage(candidate),
        "acceptance": acceptance_stage(acceptance),
        "promotion": promotion_stage(promotion),
    }
    blocking_stage = first_blocking_stage(stages)
    overall_status = "complete" if blocking_stage is None else "in_progress"
    return {
        "overall_status": overall_status,
        "blocking_stage": blocking_stage,
        "stages": stages,
        "sources": {
            "review_packet": str(review_packet_path.resolve()),
            "post_review": str(post_review_path.resolve()),
            "candidate": str(candidate_path.resolve()),
            "acceptance": str(acceptance_path.resolve()),
            "promotion": str(promotion_path.resolve()),
        },
        "next_step": next_step(blocking_stage),
    }


def review_stage(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "missing", "passed": False}
    missing = payload.get("missing_frame_files") or []
    rows = int(payload.get("review_rows") or 0)
    return {
        "status": "ready" if rows > 0 and not missing else "incomplete",
        "passed": rows > 0 and not missing,
        "review_rows": rows,
        "missing_frame_files": missing,
        "sheet": payload.get("sheet"),
    }


def post_review_stage(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "missing", "passed": False}
    validation = payload.get("review_validation") or {}
    dataset = payload.get("reviewed_training_dataset") or {}
    return {
        "status": "ready" if payload.get("ready_for_training") else "waiting_for_review",
        "passed": bool(payload.get("ready_for_training")),
        "reason": payload.get("reason"),
        "usable_for_training_count": validation.get("usable_for_training_count"),
        "validation_error_count": validation.get("error_count"),
        "trainable_review_rows": dataset.get("trainable_review_rows"),
        "written_sequences": dataset.get("written_sequences"),
    }


def candidate_stage(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "missing", "passed": False}
    acceptance = payload.get("acceptance_gate") or {}
    return {
        "status": payload.get("status"),
        "passed": payload.get("status") == "ok" and acceptance.get("passed") is True,
        "acceptance_passed": acceptance.get("passed"),
        "model_path": payload.get("model_path"),
        "schema_path": payload.get("schema_path"),
    }


def acceptance_stage(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "missing", "passed": False}
    summary = payload.get("summary") or {}
    return {
        "status": "passed" if payload.get("passed") else "failed",
        "passed": payload.get("passed") is True,
        "slow_fall_recall": summary.get("slow_fall_recall"),
        "fp_regression_confusion": summary.get("fp_regression_confusion"),
        "ur_mini_confusion": summary.get("ur_mini_confusion"),
    }


def promotion_stage(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return {"status": "missing", "passed": False}
    failed = [item.get("name") for item in payload.get("checks") or [] if item.get("passed") is not True]
    return {
        "status": "ready" if payload.get("ready") else "not_ready",
        "passed": payload.get("ready") is True,
        "failed_checks": failed,
        "promotion_env": payload.get("promotion_env"),
    }


def first_blocking_stage(stages: dict[str, dict[str, Any]]) -> str | None:
    for name in ["review_packet", "post_review_training_data", "candidate_eval", "acceptance", "promotion"]:
        if stages[name].get("passed") is not True:
            return name
    return None


def next_step(blocking_stage: str | None) -> str:
    mapping = {
        None: "All temporal v6 gates pass; proceed only with operational approval.",
        "review_packet": "Generate or repair the professor review packet.",
        "post_review_training_data": "Complete professor/manual review, apply the sheet, and rerun the post-review pipeline.",
        "candidate_eval": "Train the candidate LSTM v6 model and run the candidate evaluation pipeline.",
        "acceptance": "Inspect failed acceptance checks and retrain or adjust only with reviewed evidence.",
        "promotion": "Resolve missing artifacts/provenance or failed candidate gates before runtime promotion.",
    }
    return mapping[blocking_stage]


def load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
