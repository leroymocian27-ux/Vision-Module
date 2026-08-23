from __future__ import annotations

"""Run one local, text-only Ollama Qwen advisory smoke request.

The endpoint is intentionally fixed to loopback. This script does not load or
write .env, does not start the service, and does not enable a runtime feature.
"""

import argparse
import json
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm_adapter import (
    InvalidVLMOutput,
    OllamaQwenVLMReviewAdapter,
    VLMAdapterError,
    VLMAdapterTimeout,
)


LOOPBACK_ENDPOINT = "http://127.0.0.1:11434/api/chat"
FORBIDDEN_REQUEST_TOKENS = (
    "incident_id",
    "track_id",
    "camera_id",
    "person_id",
    "device_id",
    "image_path",
    "snapshot_url",
    "keyframe_url",
    "keyframe_image_paths",
    "timeline_image_path",
    "base64",
    "data:image",
    "logs/event_archive",
    "c:\\",
    "/tmp/",
)


def synthetic_semantics() -> EventSemantics:
    return EventSemantics(
        incident_id="synthetic-redacted",
        actor={"subject_count": 1},
        scene={"environment": "indoor", "visibility": "adequate"},
        motion={"main_transition": "standing_to_low_posture", "motion_continuity": "sudden"},
        posture={"current_posture": "low_posture", "posture_stability": "uncertain"},
        evidence={"adl_suppression_score": 0.12, "evidence_quality": "structured_only"},
        risk={"event_type": "fallen_confirmed", "risk_level": "critical", "confidence": 0.91},
        uncertainty=["synthetic_smoke_input"],
        degradation_used=["no_media_input"],
    )


def synthetic_evidence() -> EvidencePackage:
    return EvidencePackage(
        incident_id="synthetic-redacted",
        camera_id="redacted",
        trigger_timestamp="2026-07-18T00:00:00+00:00",
        fall_probability=0.91,
        fall_evidence_score=0.88,
        adl_suppression_score=0.12,
        pose_quality="structured_only",
        degradation_used=["no_media_input"],
    )


def _assert_safe_payload(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    if payload.get("stream") is not False or payload.get("format") != "json":
        raise RuntimeError("Ollama smoke payload must use stream=false and format=json")
    if any(token in serialized for token in FORBIDDEN_REQUEST_TOKENS):
        raise RuntimeError("Ollama smoke payload contains prohibited identifier, media, or path data")


def run(model: str, timeout_seconds: float) -> tuple[int, dict[str, Any]]:
    sent_payload: dict[str, Any] = {}
    session = requests.Session()
    session.trust_env = False

    def loopback_transport(payload: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        nonlocal sent_payload
        _assert_safe_payload(payload)
        sent_payload = dict(payload)
        response = session.post(LOOPBACK_ENDPOINT, json=payload, timeout=timeout)
        response.raise_for_status()
        return response.json()

    adapter = OllamaQwenVLMReviewAdapter(
        endpoint_url=LOOPBACK_ENDPOINT,
        model=model,
        timeout_seconds=timeout_seconds,
        transport=loopback_transport,
    )
    started_at = time.perf_counter()
    try:
        result = adapter.analyze(synthetic_semantics(), synthetic_evidence())
        advisory = {
            "schema_version": result.schema_version,
            "scene_summary": result.scene_summary,
            "possible_false_positive_reason": result.possible_false_positive_reason,
            "care_advice": result.care_advice,
            "confidence_explanation": result.confidence_explanation,
            "advisory_confidence": result.advisory_confidence,
        }
        return 0, {
            "status": "PASS",
            "model_name": model,
            "endpoint": LOOPBACK_ENDPOINT,
            "latency_ms": round(result.latency_ms or (time.perf_counter() - started_at) * 1000, 2),
            "advisory": advisory,
            "fallback_used": False,
            "invalid_json": False,
            "image_input": "DISABLED",
            "external_endpoint": "NOT_USED",
            "payload_verified": bool(sent_payload),
        }
    except InvalidVLMOutput as exc:
        return 2, _error_report(model, "invalid_json", exc, started_at)
    except VLMAdapterTimeout as exc:
        return 2, _error_report(model, "timeout", exc, started_at)
    except VLMAdapterError as exc:
        return 2, _error_report(model, "adapter_error", exc, started_at)
    except requests.RequestException as exc:
        return 2, _error_report(model, "request_error", exc, started_at)
    finally:
        session.close()


def _error_report(model: str, error_type: str, error: Exception, started_at: float) -> dict[str, Any]:
    return {
        "status": "REVISE",
        "model_name": model,
        "endpoint": LOOPBACK_ENDPOINT,
        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "advisory": None,
        "fallback_used": False,
        "invalid_json": error_type == "invalid_json",
        "error_type": error_type,
        "error": str(error),
        "image_input": "DISABLED",
        "external_endpoint": "NOT_USED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Ollama Qwen advisory-only smoke test")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    exit_code, report = run(args.model, args.timeout_seconds)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
