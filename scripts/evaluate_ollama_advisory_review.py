from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Mapping, Union
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.events.analysis_engine import IntelligentAnalysisEngine
from app.events.schemas import EvidenceKeyframe, EvidencePackage, EventSemantics, TrustedEventResult
from app.events.vlm import build_vlm_input
from app.events.vlm_adapter import QwenOllamaReviewAdapter, build_text_only_ollama_review_payload


DEFAULT_CASES = (
    "fall_candidate_support",
    "fallen_confirmed_high",
    "adl_suppressed_review",
    "missing_keyframes",
    "vlm_timeout_fallback",
    "vlm_invalid_json_fallback",
)
FORBIDDEN_TEXT_TOKENS = (
    "keyframe_image_paths",
    "timeline_image_path",
    "image_path",
    "snapshot_url",
    "base64",
    "data:image",
    "d:\\",
    "/workspace",
    "\\workspace",
    "logs/event_archive",
    "token",
    "lock_token",
    "payload_json",
)
POLICY_FIELDS = {"risk_level", "fall_state", "confirmed", "delivery_status", "decision"}
READY_MIN_SAMPLES = 5


OllamaTransport = Callable[[Mapping[str, Any], float], Union[Mapping[str, Any], str]]


@dataclass(frozen=True)
class EvaluationConfig:
    model: str
    fallback_model: str
    endpoint: str
    timeout: float
    cases: tuple[str, ...]
    max_cases: int
    output: Path
    jsonl: Path
    allow_local_ollama: bool = False
    dry_run: bool = False
    provider: str = "qwen_ollama"

    @property
    def effective_dry_run(self) -> bool:
        return self.dry_run or not self.allow_local_ollama


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = EvaluationConfig(
        model=args.model,
        fallback_model=args.fallback_model,
        endpoint=args.endpoint,
        timeout=args.timeout,
        cases=tuple(_split_cases(args.cases)),
        max_cases=args.max_cases,
        output=Path(args.output),
        jsonl=Path(args.jsonl),
        allow_local_ollama=args.allow_local_ollama,
        dry_run=args.dry_run,
        provider=args.provider,
    )
    try:
        report = evaluate(config)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    write_report(report, config.output, config.jsonl)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate local Ollama/Qwen text-only advisory review on synthetic events.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--fallback-model", default="qwen3.5:4b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--cases", default=",".join(DEFAULT_CASES))
    parser.add_argument("--max-cases", type=int, default=6)
    parser.add_argument("--output", default="tmp_qwen_ollama_eval/ollama_advisory_eval.json")
    parser.add_argument("--jsonl", default="tmp_qwen_ollama_eval/ollama_advisory_eval.jsonl")
    parser.add_argument("--provider", choices=("ollama", "qwen_ollama", "ollama_qwen"), default="qwen_ollama")
    parser.add_argument("--allow-local-ollama", action="store_true", help="Allow a real local 127.0.0.1/localhost Ollama call.")
    parser.add_argument("--dry-run", action="store_true", help="Force synthetic dry-run even when --allow-local-ollama is present.")
    return parser.parse_args(argv)


def evaluate(config: EvaluationConfig, *, transport: OllamaTransport | None = None) -> dict[str, Any]:
    _validate_endpoint(config.endpoint)
    selected_cases = _selected_cases(config.cases, config.max_cases)
    results = [
        evaluate_case(case_id=index + 1, scenario=scenario, config=config, transport=transport)
        for index, scenario in enumerate(selected_cases)
    ]
    summary = summarize(results)
    report = {
        "schema_version": "ollama_advisory_eval_report.v1",
        "dry_run": config.effective_dry_run,
        "allow_local_ollama": config.allow_local_ollama,
        "endpoint": config.endpoint,
        "provider": config.provider,
        "model": config.model,
        "fallback_model": config.fallback_model,
        "timeout_seconds": config.timeout,
        "cases": results,
        "summary": summary,
    }
    return report


def evaluate_case(
    *,
    case_id: int,
    scenario: str,
    config: EvaluationConfig,
    transport: OllamaTransport | None = None,
) -> dict[str, Any]:
    semantics, evidence = build_synthetic_case(scenario)
    baseline = IntelligentAnalysisEngine().analyze(semantics, evidence)
    leak_detected = _safe_payload_has_leak(semantics, evidence, config.model)
    called_ollama = bool(config.allow_local_ollama and not config.effective_dry_run)
    adapter_transport = transport
    if config.effective_dry_run:
        adapter_transport = _dry_run_transport_for_scenario(scenario)
    adapter = QwenOllamaReviewAdapter(
        endpoint_url=config.endpoint,
        model=config.model,
        fallback_model=config.fallback_model,
        timeout_seconds=config.timeout,
        transport=adapter_transport,
    )
    adapter.provider = config.provider

    started_at = time.perf_counter()
    result = IntelligentAnalysisEngine(vlm_analyzer=adapter).analyze(semantics, evidence)
    measured_latency_ms = round((time.perf_counter() - started_at) * 1000, 3)
    latency_ms = result.vlm_latency_ms if result.vlm_latency_ms is not None else measured_latency_ms
    degradation = list(result.degradation_used)
    fallback_used = any(item.startswith("vlm_") or item.startswith("ollama_") for item in degradation)
    parse_success = bool(result.vlm_provider) and "vlm_invalid_json" not in degradation
    policy_violation = _policy_violation_detected(scenario, result, baseline)

    return {
        "case_id": f"case_{case_id:02d}",
        "scenario": scenario,
        "model": config.model,
        "provider": config.provider,
        "called_ollama": called_ollama,
        "latency_ms": latency_ms,
        "success": isinstance(result, TrustedEventResult),
        "parse_success": parse_success,
        "fallback_used": fallback_used,
        "degradation_used": degradation,
        "observed_process": result.observed_process or "",
        "risk_interpretation": result.risk_interpretation or "",
        "adl_likelihood": result.adl_likelihood or "unknown",
        "uncertainty": list(result.uncertainty),
        "recommended_action": result.recommended_action,
        "policy_violation_detected": policy_violation,
        "local_path_leak_detected": leak_detected,
        "changed_decision": False,
        "changed_risk_level": result.final_risk_level != baseline.final_risk_level,
        "changed_fall_state": result.final_event_type != baseline.final_event_type,
        "changed_delivery_status": False,
        "support_fall_alarm": result.support_fall_alarm,
        "final_event_type": result.final_event_type,
        "final_risk_level": result.final_risk_level,
        "review_result": result.review_result,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item["latency_ms"]) for item in results if item.get("latency_ms") is not None]
    timeout_count = sum(1 for item in results if "vlm_timeout" in item.get("degradation_used", []) or "ollama_timeout" in item.get("degradation_used", []))
    invalid_json_count = sum(1 for item in results if "vlm_invalid_json" in item.get("degradation_used", []))
    local_path_leak_count = sum(1 for item in results if item.get("local_path_leak_detected"))
    policy_violation_count = sum(1 for item in results if item.get("policy_violation_detected"))
    parse_success_count = sum(1 for item in results if item.get("parse_success"))
    recommended_status = recommend_status(
        total_cases=len(results),
        parse_success_count=parse_success_count,
        timeout_count=timeout_count,
        average_latency_ms=mean(latencies) if latencies else None,
        max_latency_ms=max(latencies) if latencies else None,
        policy_violation_count=policy_violation_count,
        local_path_leak_count=local_path_leak_count,
    )
    return {
        "total_cases": len(results),
        "success_count": sum(1 for item in results if item.get("success")),
        "parse_success_count": parse_success_count,
        "timeout_count": timeout_count,
        "invalid_json_count": invalid_json_count,
        "average_latency_ms": round(mean(latencies), 3) if latencies else None,
        "p95_latency_ms": _p95(latencies) if len(latencies) >= READY_MIN_SAMPLES else "not_enough_samples",
        "local_path_leak_count": local_path_leak_count,
        "policy_violation_count": policy_violation_count,
        "recommended_status": recommended_status,
    }


def recommend_status(
    *,
    total_cases: int,
    parse_success_count: int,
    timeout_count: int,
    average_latency_ms: float | None,
    max_latency_ms: float | None,
    policy_violation_count: int,
    local_path_leak_count: int,
) -> str:
    if total_cases < READY_MIN_SAMPLES:
        return "KEEP_DISABLED"
    if timeout_count > 0:
        return "ALLOW_DEMO_ONLY"
    if policy_violation_count or local_path_leak_count:
        return "KEEP_DISABLED"
    parse_ratio = parse_success_count / max(1, total_cases)
    if parse_ratio < 0.8:
        return "KEEP_DISABLED"
    if average_latency_ms is None or max_latency_ms is None:
        return "KEEP_DISABLED"
    if average_latency_ms <= 8000 and max_latency_ms <= 15000:
        return "READY_FOR_STAGING"
    return "ALLOW_DEMO_ONLY"


def write_report(report: dict[str, Any], output_path: Path, jsonl_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in report["cases"]:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def build_synthetic_case(scenario: str) -> tuple[EventSemantics, EvidencePackage]:
    if scenario not in DEFAULT_CASES:
        raise ValueError(f"unknown evaluation scenario: {scenario}")
    incident_id = f"ollama-eval-{scenario}"
    profile = _scenario_profile(scenario)
    missing = scenario == "missing_keyframes"
    keyframes = [
        EvidenceKeyframe(
            role=role,
            offset_ms=offset,
            frame_seq=None if missing else 100 + index,
            fall_state=profile["fall_state"],
            missing_reason="not_collected_for_text_only_eval" if missing else None,
        )
        for index, (role, offset) in enumerate(
            (
                ("pre_context", -3000),
                ("pre_fall", -1000),
                ("trigger", 0),
                ("post_fall", 1000),
                ("post_check", 3000),
                ("post_check", 5000),
            )
        )
    ]
    evidence = EvidencePackage(
        incident_id=incident_id,
        camera_id="camera_01",
        track_id=1,
        trigger_frame_seq=100,
        trigger_timestamp="2026-07-18T09:30:00+00:00",
        keyframes=keyframes,
        bbox_sequence=[[100.0, 120.0, 310.0, 340.0], [102.0, 168.0, 326.0, 356.0]],
        fall_state_sequence=profile["fall_state_sequence"],
        fall_probability=profile["fall_probability"],
        fall_evidence_score=profile["fall_evidence_score"],
        adl_suppression_score=profile["adl_suppression_score"],
        pose_quality=profile["pose_quality"],
        degradation_used=list(profile["degradation_used"]),
    )
    semantics = EventSemantics(
        incident_id=incident_id,
        actor={"track_id": 1, "identity_known": False},
        scene={"source": "synthetic_text_only_eval", "camera_zone": "indoor_common_area"},
        motion={"main_transition": profile["motion"], "vertical_drop_detected": profile["vertical_drop"]},
        posture={"pre_state": "standing", "trigger_state": "low_posture", "post_state": profile["fall_state"]},
        evidence={
            "fall_probability": profile["fall_probability"],
            "fall_evidence_score": profile["fall_evidence_score"],
            "adl_suppression_score": profile["adl_suppression_score"],
            "missing_keyframes": missing,
        },
        risk={
            "event_type": profile["event_type"],
            "risk_level": profile["risk_level"],
            "confidence": profile["confidence"],
            "decision": profile["decision"],
            "advice": profile["rule_action"],
        },
        uncertainty=list(profile["uncertainty"]),
        degradation_used=list(profile["degradation_used"]),
    )
    return semantics, evidence


def _scenario_profile(scenario: str) -> dict[str, Any]:
    base = {
        "event_type": "fall_candidate",
        "fall_state": "fallen_candidate",
        "risk_level": "high",
        "confidence": 0.86,
        "fall_probability": 0.86,
        "fall_evidence_score": 0.84,
        "adl_suppression_score": 0.12,
        "decision": "need_attention",
        "motion": "standing_to_low_posture",
        "vertical_drop": True,
        "pose_quality": "medium",
        "fall_state_sequence": ["standing", "falling", "fallen_candidate"],
        "uncertainty": [],
        "degradation_used": [],
        "rule_action": "Review live stream and confirm onsite.",
    }
    if scenario == "fallen_confirmed_high":
        base.update(
            event_type="fallen_confirmed",
            fall_state="fallen_confirmed",
            risk_level="critical",
            confidence=0.94,
            fall_probability=0.93,
            fall_evidence_score=0.92,
            adl_suppression_score=0.08,
            decision="urgent_attention",
            pose_quality="high",
            fall_state_sequence=["standing", "falling", "fallen_confirmed"],
        )
    elif scenario == "adl_suppressed_review":
        base.update(
            risk_level="medium",
            confidence=0.72,
            fall_probability=0.74,
            fall_evidence_score=0.7,
            adl_suppression_score=0.88,
            decision="need_review",
            motion="standing_to_bending_or_sitting",
            vertical_drop=False,
            uncertainty=["adl_like_motion_possible"],
            rule_action="Review keyframes before treating as a fall alarm.",
        )
    elif scenario == "missing_keyframes":
        base.update(degradation_used=["missing_demo_keyframes"], uncertainty=["missing_keyframes"])
    elif scenario == "vlm_timeout_fallback":
        base.update(degradation_used=[])
    elif scenario == "vlm_invalid_json_fallback":
        base.update(degradation_used=[])
    return base


def _dry_run_transport_for_scenario(scenario: str) -> OllamaTransport:
    def transport(payload: Mapping[str, Any], timeout_seconds: float) -> Mapping[str, Any] | str:
        del payload, timeout_seconds
        if scenario == "vlm_timeout_fallback":
            raise TimeoutError("dry-run simulated Ollama timeout")
        if scenario == "vlm_invalid_json_fallback":
            return {"message": {"content": "{not valid json"}}
        return {"message": {"content": json.dumps(_dry_run_advisory_content(scenario), ensure_ascii=False)}}

    return transport


def _dry_run_advisory_content(scenario: str) -> dict[str, Any]:
    adl = "high" if scenario == "adl_suppressed_review" else "unknown" if scenario == "missing_keyframes" else "low"
    support = False if scenario == "adl_suppressed_review" else True
    if scenario == "fallen_confirmed_high":
        support = False
    uncertainty = ["dry_run_text_only"]
    if scenario == "missing_keyframes":
        uncertainty.append("missing_keyframes")
    return {
        "schema_version": "vlm_review_result_v1",
        "support_fall_alarm": support,
        "semantic_event_type": "fall_candidate" if scenario != "fallen_confirmed_high" else "fallen_confirmed",
        "observed_process": f"dry-run structured semantic review for {scenario}",
        "adl_likelihood": adl,
        "uncertainty": uncertainty,
        "risk_interpretation": "Dry-run advisory based only on structured event semantics.",
        "alarm_title": "Local advisory dry-run",
        "alarm_body": "No image or local path was sent.",
        "recommended_action": "Use rule result as authoritative and review live context if needed.",
    }


def _safe_payload_has_leak(semantics: EventSemantics, evidence: EvidencePackage, model: str) -> bool:
    try:
        request = build_vlm_input(semantics, evidence)
        payload = build_text_only_ollama_review_payload(semantics, evidence, request, model=model)
    except Exception:
        return True
    return _contains_forbidden_text(payload)


def _contains_forbidden_text(value: Any) -> bool:
    if isinstance(value, Mapping) and isinstance(value.get("messages"), list):
        user_parts = [
            str(item.get("content") or "")
            for item in value["messages"]
            if isinstance(item, Mapping) and item.get("role") == "user"
        ]
        text = "\n".join(user_parts).lower()
    else:
        text = json.dumps(value, ensure_ascii=False).lower()
    return any(token in text for token in FORBIDDEN_TEXT_TOKENS)


def _policy_violation_detected(scenario: str, result: TrustedEventResult, baseline: TrustedEventResult) -> bool:
    if result.final_event_type != baseline.final_event_type or result.final_risk_level != baseline.final_risk_level:
        return True
    if result.support_fall_alarm != baseline.support_fall_alarm:
        return True
    if "medical diagnosis" in result.recommended_action.lower() or "diagnosis:" in result.recommended_action.lower():
        return True
    if scenario == "fall_candidate_support" and result.final_event_type == "fallen_confirmed":
        return True
    if scenario == "fallen_confirmed_high" and result.final_risk_level not in {"high", "critical"}:
        return True
    return False


def _validate_endpoint(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Ollama evaluation endpoint must be http://127.0.0.1, http://localhost, or loopback ::1")
    if not parsed.path.rstrip("/").endswith("/api/chat"):
        raise ValueError("Ollama evaluation endpoint must target /api/chat")


def _selected_cases(cases: tuple[str, ...], max_cases: int) -> tuple[str, ...]:
    if max_cases <= 0:
        return ()
    unknown = [case for case in cases if case not in DEFAULT_CASES]
    if unknown:
        raise ValueError(f"unknown evaluation scenario(s): {', '.join(unknown)}")
    return tuple(cases[:max_cases])


def _split_cases(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 3)


if __name__ == "__main__":
    raise SystemExit(main())
