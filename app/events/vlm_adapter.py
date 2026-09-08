from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any, Union
from urllib.parse import urlsplit

import requests
from pydantic import ValidationError

from app.core.config import Settings
from app.events.schemas import EvidencePackage, EventSemantics
from app.events.vlm import (
    VLMProvider,
    VLMReviewInput,
    VLMReviewResult,
    adl_likelihood_from_score,
    build_vlm_input,
)
from app.events.vlm_prompt import OLLAMA_QWEN_ADVISORY_PROMPT


class VLMAdapterError(RuntimeError):
    """Base error for optional VLM adapter failures."""


class VLMAdapterTimeout(VLMAdapterError):
    """Raised when an optional VLM provider times out."""


class VLMAdapterSkipped(VLMAdapterError):
    """Raised when a provider is intentionally skipped before any request."""


class InvalidVLMOutput(VLMAdapterError):
    """Raised when a provider response does not match the output contract."""


VLMTransport = Callable[[VLMReviewInput, float], Union[Mapping[str, Any], VLMReviewResult, str]]
OllamaTransport = Callable[[Mapping[str, Any], float], Union[Mapping[str, Any], str]]
_MAX_TITLE_LENGTH = 80
_MAX_BODY_LENGTH = 300
_MAX_ACTION_LENGTH = 220
_MAX_INTERPRETATION_LENGTH = 500
_EXPECTED_PROVIDER_FIELDS = {
    "support_fall_alarm",
    "semantic_event_type",
    "observed_process",
    "adl_likelihood",
    "uncertainty",
    "risk_interpretation",
    "alarm_title",
    "alarm_body",
    "recommended_action",
}

# Compact PFV2 Qwen schema mapping. Keep this as the single source of truth:
# e=semantic_event, s=posture_state, d=visible_distress,
# f=VLM direct true-fall/risk judgement, c=confidence, t=last_frame_description.
EVENT_MAP = {
    "fall": "confirmed_fall",
    "non_fall": "non_fall",
    "risk": "possible_fall_or_distress",
    "phone": "lying_using_phone",
    "reading": "lying_reading",
    "normal": "normal_activity",
    "uncertain": "uncertain",
}


class BaseVLMReviewAdapter:
    """Optional provider adapter for event-level semantic review.

    The adapter is side-channel only: callers run rules first and treat VLM
    output as advisory text/enrichment, never as a fall alarm authority.
    """

    def __init__(
        self,
        *,
        provider: VLMProvider = "disabled",
        endpoint_url: str = "",
        timeout_seconds: float = 2.0,
        prompt_version: str = "fall_event_review_v1",
        output_schema_version: str = "vlm_review_result_v1",
        http_headers: Mapping[str, str] | None = None,
        transport: VLMTransport | None = None,
    ) -> None:
        self.provider = provider
        self.endpoint_url = endpoint_url
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.prompt_version = prompt_version
        self.output_schema_version = output_schema_version
        self.http_headers = dict(http_headers or {})
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> "EventVLMAdapter | None":
        adapter = build_vlm_adapter_from_config(settings)
        return adapter if isinstance(adapter, EventVLMAdapter) or adapter is None else cls(
            provider=adapter.provider,
            endpoint_url=adapter.endpoint_url,
            timeout_seconds=adapter.timeout_seconds,
            prompt_version=adapter.prompt_version,
            output_schema_version=adapter.output_schema_version,
            http_headers=adapter.http_headers,
            transport=adapter._transport,
        )

    def build_request(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewInput:
        return build_vlm_input(
            semantics,
            evidence,
            prompt_version=self.prompt_version,
            output_schema_version=self.output_schema_version,
        )

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewResult | None:
        if self.provider == "disabled":
            return None
        request = self.build_request(semantics, evidence)
        started_at = time.perf_counter()
        if self.provider == "dummy":
            result = self._dummy_response(request)
            return _normalize_result(result.model_copy(update={"latency_ms": _elapsed_ms(started_at)}))
        if self.provider in {"http_mock", "http", "qwen_http"}:
            return self._http_response(request, started_at)
        raise VLMAdapterError(f"unsupported VLM provider: {self.provider}")

    def _dummy_response(self, request: VLMReviewInput) -> VLMReviewResult:
        risk = request.event_semantics.get("risk") if isinstance(request.event_semantics.get("risk"), dict) else {}
        event_type = str(risk.get("event_type") or "fall_candidate")
        confidence = _safe_float(risk.get("confidence"), default=0.0)
        adl_score = _safe_float(request.feature_json.get("adl_suppression_score"), default=0.0)
        support = event_type == "fallen_confirmed" or (confidence >= 0.7 and adl_score < 0.65)
        return VLMReviewResult(
            support_fall_alarm=support,
            semantic_event_type=event_type,
            observed_process="dummy_provider_rule_echo",
            adl_likelihood=adl_likelihood_from_score(adl_score),
            uncertainty=list(request.feature_json.get("degradation_used") or []),
            risk_interpretation="dummy provider echoes rule semantics for contract testing",
            alarm_title="VLM advisory review",
            alarm_body="Dummy VLM provider returned a deterministic advisory response.",
            recommended_action=str(risk.get("advice") or "Review event evidence and live stream."),
            provider="dummy",
        )

    def _http_response(self, request: VLMReviewInput, started_at: float) -> VLMReviewResult:
        if self.provider in {"http", "qwen_http"} and not _has_review_image(request):
            raise VLMAdapterSkipped("vlm_skipped_no_images")
        try:
            if self._transport is not None:
                payload = self._transport(request, self.timeout_seconds)
            else:
                if not self.endpoint_url:
                    raise VLMAdapterError(f"EVENT_VLM_ENDPOINT is required for {self.provider} provider")
                response = requests.post(
                    self.endpoint_url,
                    json=request.model_dump(mode="json"),
                    headers=self.http_headers or None,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
        except requests.Timeout as exc:
            raise VLMAdapterTimeout(str(exc)) from exc
        except requests.RequestException as exc:
            raise VLMAdapterError(str(exc)) from exc
        except TimeoutError as exc:
            raise VLMAdapterTimeout(str(exc)) from exc
        except ValueError as exc:
            raise InvalidVLMOutput("VLM provider returned invalid JSON") from exc

        raw_response = payload if isinstance(payload, str) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise InvalidVLMOutput("VLM provider returned invalid JSON") from exc

        if isinstance(payload, VLMReviewResult):
            if payload.schema_version not in _accepted_schema_versions(request.output_schema_version):
                raise InvalidVLMOutput(f"unexpected schema_version: {payload.schema_version}")
            return _normalize_result(
                payload.model_copy(
                    update={
                        "provider": self.provider,
                        "latency_ms": _elapsed_ms(started_at),
                        "raw_response": raw_response or payload.raw_response,
                    }
                )
            )
        try:
            if isinstance(payload, Mapping) and payload.get("schema_version") not in _accepted_schema_versions(request.output_schema_version):
                raise InvalidVLMOutput(f"unexpected schema_version: {payload.get('schema_version')}")
            missing_fields = _missing_provider_fields(payload)
            result = VLMReviewResult.model_validate(payload)
            parse_error = _with_schema_warning(result.parse_error, missing_fields)
            return _normalize_result(
                result.model_copy(
                    update={
                        "provider": self.provider,
                        "latency_ms": _elapsed_ms(started_at),
                        "raw_response": raw_response or result.raw_response,
                        "parse_error": parse_error,
                    }
                )
            )
        except ValidationError as exc:
            raise InvalidVLMOutput(str(exc)) from exc


class EventVLMAdapter(BaseVLMReviewAdapter):
    """Backward-compatible adapter entry point used by existing pipeline code."""


class DummyVLMReviewAdapter(BaseVLMReviewAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider="dummy", **kwargs)


class HttpVLMReviewAdapter(BaseVLMReviewAdapter):
    def __init__(self, *, provider: VLMProvider = "http", **kwargs: Any) -> None:
        if provider not in {"http", "http_mock", "qwen_http"}:
            raise ValueError("HttpVLMReviewAdapter provider must be http, http_mock, or qwen_http")
        super().__init__(provider=provider, **kwargs)


class QwenHttpVLMReviewAdapter(HttpVLMReviewAdapter):
    """Legacy direct-use shell retained for test compatibility; Settings rejects it."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider="qwen_http", **kwargs)


class OllamaVLMReviewAdapter(BaseVLMReviewAdapter):
    """Local, structured-semantics-only Ollama adapter for advisory review."""

    def __init__(
        self,
        *,
        provider: VLMProvider = "ollama",
        endpoint_url: str,
        model: str,
        timeout_seconds: float,
        fallback_model: str = "",
        text_only: bool = True,
        include_images: bool = False,
        allow_non_localhost: bool = False,
        transport: OllamaTransport | None = None,
    ) -> None:
        if provider not in {"ollama", "qwen_ollama", "ollama_qwen"}:
            raise ValueError("OllamaVLMReviewAdapter provider must be ollama, qwen_ollama, or ollama_qwen")
        super().__init__(provider=provider, endpoint_url=endpoint_url, timeout_seconds=timeout_seconds)
        self.model = model
        self.fallback_model = fallback_model
        self.text_only = bool(text_only)
        self.include_images = bool(include_images)
        self.allow_non_localhost = allow_non_localhost
        self._ollama_transport = transport

    def analyze(self, semantics: EventSemantics, evidence: EvidencePackage) -> VLMReviewResult:
        if not self.text_only or self.include_images:
            raise VLMAdapterError("Ollama image input is not supported by this text-only adapter")
        if not self.endpoint_url:
            raise VLMAdapterError("EVENT_VLM_OLLAMA_ENDPOINT is required for Ollama provider")
        if not _is_local_ollama_url(self.endpoint_url) and not self.allow_non_localhost:
            raise VLMAdapterError("EVENT_VLM_OLLAMA_ENDPOINT must use localhost unless explicitly allowed")
        request = self.build_request(semantics, evidence)
        ollama_payload = build_text_only_ollama_review_payload(semantics, evidence, request, model=self.model)
        started_at = time.perf_counter()
        try:
            if self._ollama_transport is not None:
                payload = self._ollama_transport(ollama_payload, self.timeout_seconds)
            else:
                response = requests.post(
                    self.endpoint_url,
                    json=ollama_payload,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
        except requests.Timeout as exc:
            raise VLMAdapterTimeout(str(exc)) from exc
        except requests.RequestException as exc:
            raise VLMAdapterError(str(exc)) from exc
        except TimeoutError as exc:
            raise VLMAdapterTimeout(str(exc)) from exc
        except ConnectionError as exc:
            raise VLMAdapterError(str(exc)) from exc
        except ValueError as exc:
            raise InvalidVLMOutput("Ollama returned invalid advisory JSON") from exc

        result = _ollama_result_from_payload(payload, provider=self.provider, expected_schema=request.output_schema_version)
        return _normalize_result(result.model_copy(update={"latency_ms": _elapsed_ms(started_at)}))


class QwenOllamaReviewAdapter(OllamaVLMReviewAdapter):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(provider="qwen_ollama", **kwargs)


class OllamaQwenVLMReviewAdapter(QwenOllamaReviewAdapter):
    """Backward-compatible name for the first local-Ollama audit."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        endpoint_url: str | None = None,
        model: str,
        timeout_seconds: float,
        allow_non_localhost: bool = False,
        transport: OllamaTransport | None = None,
    ) -> None:
        endpoint = endpoint_url or _ollama_endpoint_from_base_url(base_url or "")
        super().__init__(
            endpoint_url=endpoint,
            model=model,
            timeout_seconds=timeout_seconds,
            allow_non_localhost=allow_non_localhost,
            transport=transport,
        )
        self.provider = "ollama_qwen"


def build_vlm_adapter_from_config(settings: Settings) -> BaseVLMReviewAdapter | None:
    if not settings.event_vlm_enabled:
        return None
    provider = settings.event_vlm_provider
    if provider == "disabled":
        return EventVLMAdapter(provider="disabled")
    if provider == "dummy":
        return DummyVLMReviewAdapter(
            endpoint_url=settings.event_vlm_http_mock_url,
            timeout_seconds=settings.event_vlm_timeout_seconds,
            prompt_version=settings.event_vlm_prompt_version,
            output_schema_version=settings.event_vlm_output_schema_version,
        )
    if provider == "qwen_http":
        return QwenHttpVLMReviewAdapter(
            endpoint_url=settings.event_vlm_http_mock_url,
            timeout_seconds=settings.event_vlm_timeout_seconds,
            prompt_version=settings.event_vlm_prompt_version,
            output_schema_version=settings.event_vlm_output_schema_version,
            http_headers=_parse_http_headers(settings.event_vlm_http_headers_json),
        )
    if provider in {"http_mock", "http"}:
        return HttpVLMReviewAdapter(
            provider=provider,  # type: ignore[arg-type]
            endpoint_url=settings.event_vlm_http_mock_url,
            timeout_seconds=settings.event_vlm_timeout_seconds,
            prompt_version=settings.event_vlm_prompt_version,
            output_schema_version=settings.event_vlm_output_schema_version,
            http_headers=_parse_http_headers(settings.event_vlm_http_headers_json),
        )
    if provider in {"ollama", "qwen_ollama", "ollama_qwen"}:
        if settings.event_vlm_ollama_include_images or not settings.event_vlm_ollama_text_only:
            raise VLMAdapterError("Ollama provider is text-only; image input is disabled")
        adapter_cls = QwenOllamaReviewAdapter if provider in {"qwen_ollama", "ollama_qwen"} else OllamaVLMReviewAdapter
        kwargs = {
            "endpoint_url": settings.event_vlm_ollama_endpoint,
            "model": settings.event_vlm_ollama_model,
            "fallback_model": settings.event_vlm_ollama_fallback_model,
            "timeout_seconds": settings.event_vlm_ollama_timeout_seconds,
            "text_only": settings.event_vlm_ollama_text_only,
            "include_images": settings.event_vlm_ollama_include_images,
            "allow_non_localhost": settings.event_vlm_ollama_allow_non_localhost,
        }
        if adapter_cls is OllamaVLMReviewAdapter:
            return adapter_cls(provider="ollama", **kwargs)
        adapter = adapter_cls(**kwargs)
        if provider == "ollama_qwen":
            adapter.provider = "ollama_qwen"
        return adapter
    raise VLMAdapterError(f"unsupported VLM provider: {provider}")


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


def _normalize_result(result: VLMReviewResult) -> VLMReviewResult:
    return result.model_copy(
        update={
            "alarm_title": _truncate(_sanitize_advisory_text(result.alarm_title), _MAX_TITLE_LENGTH),
            "alarm_body": _truncate(_sanitize_advisory_text(result.alarm_body), _MAX_BODY_LENGTH),
            "recommended_action": _truncate(_sanitize_advisory_text(result.recommended_action), _MAX_ACTION_LENGTH),
            "risk_interpretation": _truncate(_sanitize_advisory_text(result.risk_interpretation), _MAX_INTERPRETATION_LENGTH),
        }
    )


def _missing_provider_fields(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    return sorted(field for field in _EXPECTED_PROVIDER_FIELDS if field not in payload)


def _with_schema_warning(parse_error: str | None, missing_fields: list[str]) -> str | None:
    if not missing_fields:
        return parse_error
    warning = "schema_warning_missing_fields:" + ",".join(missing_fields)
    if not parse_error:
        return warning
    return f"{parse_error};{warning}"


def _has_review_image(request: VLMReviewInput) -> bool:
    return bool(request.timeline_image_path or request.keyframe_image_paths)


def _is_local_ollama_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def build_text_only_ollama_review_payload(
    semantics: EventSemantics,
    evidence: EvidencePackage,
    request: VLMReviewInput,
    *,
    model: str,
) -> dict[str, Any]:
    keyframes = evidence.keyframes or []
    safe_input = {
        "schema_version": "ollama_text_review_input.v1",
        "event_type": semantics.risk.get("event_type"),
        "fall_state": semantics.risk.get("event_type"),
        "risk_level": semantics.risk.get("risk_level"),
        "confidence": semantics.risk.get("confidence"),
        "event_semantics": {
            "actor": _safe_json_value(semantics.actor),
            "scene": _safe_json_value(semantics.scene),
            "motion": _safe_json_value(semantics.motion),
            "posture": _safe_json_value(semantics.posture),
            "evidence": _safe_json_value(semantics.evidence),
            "risk": _safe_json_value(semantics.risk),
            "uncertainty": list(semantics.uncertainty),
            "degradation_used": list(semantics.degradation_used),
        },
        "feature_json": {
            "fall_probability": evidence.fall_probability,
            "fall_evidence_score": evidence.fall_evidence_score,
            "adl_suppression_score": evidence.adl_suppression_score,
            "pose_quality": evidence.pose_quality,
            "bbox_sequence": _safe_json_value(evidence.bbox_sequence),
            "fall_state_sequence": _safe_json_value(evidence.fall_state_sequence),
            "degradation_used": list(evidence.degradation_used),
        },
        "evidence_summary": {
            "keyframe_count": sum(1 for frame in keyframes if not frame.missing_reason),
            "missing_frame_count": sum(1 for frame in keyframes if frame.missing_reason),
        },
        "prompt_version": request.prompt_version,
        "output_schema_version": request.output_schema_version,
        "media_policy": {
            "text_only": True,
            "include_images": False,
            "media_references_allowed": False,
            "path_refs": False,
        },
    }
    _assert_no_forbidden_ollama_content(safe_input)
    return {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": OLLAMA_QWEN_ADVISORY_PROMPT},
            {"role": "user", "content": json.dumps(safe_input, ensure_ascii=False, separators=(",", ":"))},
        ],
    }


def _ollama_result_from_payload(payload: Any, *, provider: VLMProvider, expected_schema: str) -> VLMReviewResult:
    raw_response = payload if isinstance(payload, str) else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidVLMOutput("Ollama returned invalid JSON") from exc
    if isinstance(payload, VLMReviewResult):
        return payload.model_copy(update={"provider": provider, "raw_response": raw_response or payload.raw_response})
    if not isinstance(payload, Mapping):
        raise InvalidVLMOutput("Ollama returned non-object JSON")
    content: Any = payload
    if "message" in payload:
        message = payload.get("message")
        if not isinstance(message, Mapping):
            raise InvalidVLMOutput("Ollama response missing message object")
        content = message.get("content")
    if isinstance(content, str):
        raw_response = content
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise InvalidVLMOutput("Ollama message content is invalid JSON") from exc
    if not isinstance(content, Mapping):
        raise InvalidVLMOutput("Ollama advisory content is not an object")
    if content.get("schema_version") == "ollama_qwen_advisory.v1":
        content = _legacy_ollama_advisory_to_vlm_result(content)
    if content.get("schema_version") not in _accepted_schema_versions(expected_schema):
        raise InvalidVLMOutput(f"unexpected schema_version: {content.get('schema_version')}")
    forbidden_output = set(content) & {"risk_level", "fall_state", "delivery_status", "endpoint", "token", "keyframe_image_paths", "timeline_image_path"}
    if forbidden_output:
        raise InvalidVLMOutput(f"Ollama advisory output contains forbidden fields: {sorted(forbidden_output)}")
    try:
        result = VLMReviewResult.model_validate(content)
    except ValidationError as exc:
        raise InvalidVLMOutput(str(exc)) from exc
    return result.model_copy(update={"provider": provider, "raw_response": raw_response or result.raw_response})


def _legacy_ollama_advisory_to_vlm_result(content: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "vlm_review_result_v1",
        "support_fall_alarm": None,
        "semantic_event_type": "unknown",
        "observed_process": str(content.get("scene_summary") or ""),
        "adl_likelihood": "unknown",
        "uncertainty": ["ollama_text_only"],
        "risk_interpretation": str(content.get("confidence_explanation") or ""),
        "alarm_title": "Local Ollama advisory review",
        "alarm_body": str(content.get("scene_summary") or ""),
        "recommended_action": str(content.get("care_advice") or ""),
        "scene_summary": str(content.get("scene_summary") or ""),
        "possible_false_positive_reason": str(content.get("possible_false_positive_reason") or ""),
        "care_advice": str(content.get("care_advice") or ""),
        "confidence_explanation": str(content.get("confidence_explanation") or ""),
        "advisory_confidence": content.get("advisory_confidence"),
    }


def _ollama_endpoint_from_base_url(value: str) -> str:
    if not value:
        return ""
    return value.rstrip("/") if value.rstrip("/").endswith("/api/chat") else f"{value.rstrip('/')}/api/chat"


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_json_value(item)
            for key, item in value.items()
            if not _is_redacted_ollama_key(str(key))
        }
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    return value


def _is_redacted_ollama_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in {
        "image_path",
        "snapshot_url",
        "keyframe_image_paths",
        "timeline_image_path",
        "payload_json",
        "lock_token",
        "incident_id",
        "track_id",
        "camera_id",
        "person_id",
        "device_id",
        "subject_id",
    } or normalized.endswith("_id")


def _assert_no_forbidden_ollama_content(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    lowered = serialized.lower()
    forbidden = (
        "keyframe_image_paths",
        "timeline_image_path",
        "image_path",
        "snapshot_url",
        "local_path",
        "payload_json",
        "lock_token",
        "incident_id",
        "track_id",
        "camera_id",
        "person_id",
        "device_id",
        "base64",
        "data:image",
        "logs/event_archive",
        "/workspace",
        "\\workspace",
    )
    if any(token in lowered for token in forbidden) or _looks_like_absolute_path(serialized):
        raise VLMAdapterError("Ollama text-only payload contains forbidden media/path metadata")


def _looks_like_absolute_path(value: str) -> bool:
    normalized = value.replace("\\\\", "\\")
    return ":\\" in normalized or ":/" in normalized or "/var/" in normalized or "/tmp/" in normalized


def _accepted_schema_versions(expected: str) -> set[str | None]:
    return {None, expected, "event_vlm_output.v1", "vlm_review_result_v1"}


def _parse_http_headers(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VLMAdapterError("EVENT_VLM_HTTP_HEADERS_JSON must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise VLMAdapterError("EVENT_VLM_HTTP_HEADERS_JSON must be a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def _sanitize_advisory_text(value: str) -> str:
    text = str(value or "")
    lowered = text.lower()
    blocked = ("medical diagnosis", "diagnosis:", "diagnose", "fracture", "stroke", "诊断", "骨折", "中风")
    return "" if any(token in lowered for token in blocked) else text


def _truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
