from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any, Union
from urllib.parse import urlsplit

import requests
from pydantic import ValidationError

from app.events.schemas import EventSemantics, QwenKeyframeAdvisory, event_now_iso


class QwenKeyframeError(RuntimeError):
    """Base error for the optional local keyframe-analysis sidecar."""


class QwenKeyframeTimeout(QwenKeyframeError):
    pass


class QwenKeyframeInvalidOutput(QwenKeyframeError):
    pass


class QwenKeyframeNonChineseOutput(QwenKeyframeInvalidOutput):
    pass


@dataclass(frozen=True)
class QwenImageInput:
    offset_ms: int
    role: str
    image_bytes: bytes


@dataclass(frozen=True)
class QwenPostFallDetail:
    posture: str
    movement_level: str
    attempt_to_stand: str
    persistent_ground_state: str
    possible_help_gesture: str
    visibility: str
    occlusion: str
    scene_risks: list[str]
    summary: str
    review_points: list[str]
    confidence: float | None
    latency_ms: float


QwenTransport = Callable[[Mapping[str, Any], float], Union[Mapping[str, Any], str]]

_FORBIDDEN_OUTPUT_FIELDS = {
    "incident_id", "track_id", "camera_id", "elder_id", "person_id", "image_path",
    "keyframe_url", "snapshot_url", "file_path", "path", "url", "rtsp", "token",
    "authorization", "endpoint", "raw_response",
}
_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:tmp|var|home|workspace|data)/)")
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_LATIN_PATTERN = re.compile(r"[A-Za-z]")
_MAX_TEXT_LENGTH = 600
_JSON_FENCE_PATTERN = re.compile(r"```(?:json|JSON)?\s*(.*?)\s*```", re.DOTALL)
_MEDICAL_DIAGNOSIS_PATTERN = re.compile(
    r"骨折|脑出血|脑卒中|中风|昏迷|死亡|心脏病|心肌梗死|心脏骤停|疾病|诊断|意识|呼吸|生命体征",
    re.IGNORECASE,
)
_POST_FALL_FIELD_ALIASES = {
    "activity_level": "movement_level",
    "movement": "movement_level",
    "attempting_to_stand": "attempt_to_stand",
    "trying_to_stand": "attempt_to_stand",
    "ground_state": "persistent_ground_state",
    "persistent_ground": "persistent_ground_state",
    "help_gesture": "possible_help_gesture",
    "visibility_level": "visibility",
    "occlusion_level": "occlusion",
    "scene_risk": "scene_risks",
    "risks": "scene_risks",
    "review_point": "review_points",
    "confidence_score": "confidence",
    "posture_description": "posture",
    "scene_summary": "summary",
}
_POST_FALL_ENUM_ALIASES = {
    "movement_level": {
        "none": "none_observed",
        "no_movement": "none_observed",
        "none_observed": "none_observed",
        "静止": "none_observed",
        "无明显动作": "none_observed",
        "未见明显动作": "none_observed",
        "slight": "slight",
        "minor": "slight",
        "轻微": "slight",
        "轻微活动": "slight",
        "active": "active",
        "明显活动": "active",
        "活动": "active",
    },
    "attempt_to_stand": {
        "yes": "observed",
        "true": "observed",
        "observed": "observed",
        "尝试起身": "observed",
        "有尝试起身": "observed",
        "no": "not_observed",
        "false": "not_observed",
        "not_observed": "not_observed",
        "未见尝试起身": "not_observed",
        "无尝试起身": "not_observed",
    },
    "persistent_ground_state": {
        "yes": "observed",
        "true": "observed",
        "observed": "observed",
        "持续倒地": "observed",
        "仍在地面": "observed",
        "no": "not_observed",
        "false": "not_observed",
        "not_observed": "not_observed",
        "未持续倒地": "not_observed",
    },
    "possible_help_gesture": {
        "yes": "observed",
        "true": "observed",
        "observed": "observed",
        "求助手势": "observed",
        "no": "not_observed",
        "false": "not_observed",
        "not_observed": "not_observed",
        "未见求助手势": "not_observed",
    },
    "visibility": {
        "good": "good",
        "clear": "good",
        "清晰": "good",
        "良好": "good",
        "limited": "limited",
        "poor": "limited",
        "受限": "limited",
        "较差": "limited",
    },
    "occlusion": {
        "none": "none",
        "无遮挡": "none",
        "partial": "partial",
        "部分遮挡": "partial",
        "severe": "severe",
        "heavy": "severe",
        "严重遮挡": "severe",
    },
}
_UNKNOWN_ENUM_VALUES = {
    "unknown",
    "unclear",
    "uncertain",
    "n/a",
    "na",
    "insufficient_visual_evidence",
    "未知",
    "不清楚",
    "无法判断",
    "画面不足",
}


class QwenKeyframeAnalyzer:
    """Calls a localhost-only Ollama vision model with image bytes, never paths."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        model_name: str,
        timeout_seconds: float,
        transport: QwenTransport | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self._transport = transport
        self._diagnostic_lock = Lock()
        self._last_post_fall_diagnostic: dict[str, Any] | None = None

    @property
    def last_post_fall_diagnostic(self) -> dict[str, Any] | None:
        with self._diagnostic_lock:
            return dict(self._last_post_fall_diagnostic) if self._last_post_fall_diagnostic else None

    def analyze(
        self,
        *,
        semantics: EventSemantics | None,
        images: Sequence[QwenImageInput],
        missing_reasons: Sequence[str] = (),
    ) -> QwenKeyframeAdvisory:
        if not images:
            return self._advisory("degraded", missing_reasons=missing_reasons, error_code="no_archived_keyframes")
        if not _is_local_ollama_url(self.endpoint_url):
            raise QwenKeyframeError("Qwen keyframe analysis endpoint must be localhost")
        payload = self.build_payload(semantics=semantics, images=images)
        started = time.perf_counter()
        try:
            if self._transport is not None:
                response_payload = self._transport(payload, self.timeout_seconds)
            else:
                response = requests.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
                response.raise_for_status()
                response_payload = response.json()
        except requests.Timeout as exc:
            self._record_post_fall_diagnostic(
                status="timeout",
                raw_response=None,
                normalized_response=None,
                failure_reason=str(exc),
            )
            raise QwenKeyframeTimeout(str(exc)) from exc
        except requests.RequestException as exc:
            self._record_post_fall_diagnostic(
                status="failed",
                raw_response=None,
                normalized_response=None,
                failure_reason=str(exc),
            )
            raise QwenKeyframeError(str(exc)) from exc
        except TimeoutError as exc:
            self._record_post_fall_diagnostic(
                status="timeout",
                raw_response=None,
                normalized_response=None,
                failure_reason=str(exc),
            )
            raise QwenKeyframeTimeout(str(exc)) from exc
        except ValueError as exc:
            self._record_post_fall_diagnostic(
                status="parse_failed",
                raw_response=None,
                normalized_response=None,
                failure_reason="Ollama returned invalid response JSON",
            )
            raise QwenKeyframeInvalidOutput("Ollama returned invalid response JSON") from exc

        content = _response_content(response_payload)
        advisory = _parse_advisory(content)
        return advisory.model_copy(update={
            "analysis_status": "completed",
            "provider": "ollama_qwen",
            "model_name": self.model_name,
            "image_count": len(images),
            "analyzed_offsets_ms": [image.offset_ms for image in images],
            "missing_reasons": _bounded_strings(missing_reasons),
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "error_code": None,
            "completed_at": event_now_iso(),
        })

    def analyze_post_fall(
        self,
        *,
        images: Sequence[QwenImageInput],
        keyframe_status: str,
        missing_offsets_ms: Sequence[int] = (),
    ) -> QwenPostFallDetail:
        """Describe an already confirmed fall; this method never re-decides the event."""
        if not images:
            raise QwenKeyframeError("post-fall analysis requires at least one keyframe image")
        if not _is_local_ollama_url(self.endpoint_url):
            raise QwenKeyframeError("Qwen keyframe analysis endpoint must be localhost")
        payload = self.build_post_fall_payload(
            images=images,
            keyframe_status=keyframe_status,
            missing_offsets_ms=missing_offsets_ms,
        )
        started = time.perf_counter()
        try:
            if self._transport is not None:
                response_payload = self._transport(payload, self.timeout_seconds)
            else:
                response = requests.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
                response.raise_for_status()
                response_payload = response.json()
        except requests.Timeout as exc:
            raise QwenKeyframeTimeout(str(exc)) from exc
        except requests.RequestException as exc:
            raise QwenKeyframeError(str(exc)) from exc
        except TimeoutError as exc:
            raise QwenKeyframeTimeout(str(exc)) from exc
        except ValueError as exc:
            raise QwenKeyframeInvalidOutput("Ollama returned invalid response JSON") from exc
        raw_response = _bounded_raw_response(response_payload)
        try:
            parsed = _parse_post_fall_detail(_response_content(response_payload))
        except QwenKeyframeInvalidOutput as exc:
            self._record_post_fall_diagnostic(
                status="parse_failed",
                raw_response=raw_response,
                normalized_response=None,
                failure_reason=str(exc),
            )
            raise
        normalized_response = {
            **parsed.__dict__,
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        self._record_post_fall_diagnostic(
            status="completed",
            raw_response=raw_response,
            normalized_response=normalized_response,
            failure_reason=None,
        )
        return QwenPostFallDetail(
            **normalized_response
        )

    def _record_post_fall_diagnostic(
        self,
        *,
        status: str,
        raw_response: str | None,
        normalized_response: Mapping[str, Any] | None,
        failure_reason: str | None,
    ) -> None:
        with self._diagnostic_lock:
            self._last_post_fall_diagnostic = {
                "status": status,
                "parse_status": _parse_status_for_raw_response(status, raw_response),
                "raw_response": raw_response,
                "normalized_response": dict(normalized_response) if normalized_response is not None else None,
                "failure_reason": failure_reason,
            }

    def build_payload(self, *, semantics: EventSemantics | None, images: Sequence[QwenImageInput]) -> dict[str, Any]:
        image_slots = [{"offset_ms": image.offset_ms, "role": image.role} for image in images]
        safe_context = {
            "fall_state": _safe_event_value(semantics.risk.get("event_type")) if semantics else None,
            "risk_level": _safe_event_value(semantics.risk.get("risk_level")) if semantics else None,
            "keyframe_slots": image_slots,
        }
        content = {
            "schema_version": "qwen_keyframe_analysis_input.v1",
            "task": "仅依据提供的事件关键帧，描述可观察到的姿态、动作、场景和不确定性。",
            "context": safe_context,
            "constraints": [
                "只返回符合给定结构的 JSON 对象，不要输出解释、Markdown 或额外文字。",
                "scene_summary、posture_description、movement_description、possible_false_positive_reasons、care_advice、confidence_explanation 的所有描述值必须使用简体中文，不得出现英文单词。",
                "直接返回结果对象，不要复述本请求或上下文。",
                "不得推断身份、姓名、年龄、诊断、位置或房间。",
                "不得输出机器狗指令，也不得修改跌倒判定。",
                "不得输出路径、URL、RTSP 地址、凭据或任何标识符。",
            ],
        }
        serialized = json.dumps(content, ensure_ascii=False)
        if _PATH_PATTERN.search(serialized):
            raise QwenKeyframeError("keyframe analysis payload contains forbidden metadata")
        return {
            "model": self.model_name,
            "stream": False,
            "think": False,
            "format": _ollama_advisory_json_schema(),
            "messages": [
                {
                    "role": "system",
                    "content": "你是本机事件关键帧语义辅助模型。只返回请求的 JSON 对象。所有自然语言描述必须为简体中文，不能输出英文描述。",
                },
                {
                    "role": "user",
                    "content": serialized,
                    "images": [base64.b64encode(image.image_bytes).decode("ascii") for image in images],
                },
            ],
        }

    def build_post_fall_payload(
        self,
        *,
        images: Sequence[QwenImageInput],
        keyframe_status: str,
        missing_offsets_ms: Sequence[int] = (),
    ) -> dict[str, Any]:
        content = {
            "schema_version": "pfv2_post_fall_input.v1",
            "task": (
                "前级视觉二分类系统已经确认存在跌倒事件。你的任务不是重新判断是否跌倒，"
                "而是依据事件前后的多张关键帧，分析跌倒后的人员状态和场景风险。"
            ),
            "keyframes": [
                {"offset_ms": image.offset_ms, "role": image.role}
                for image in images
            ],
            "keyframe_status": _safe_event_value(keyframe_status),
            "missing_offsets_ms": [int(value) for value in missing_offsets_ms],
            "constraints": [
                "只返回符合给定结构的 JSON 对象，不要输出解释、Markdown 或额外文字。",
                "所有自然语言描述必须使用简体中文，不得出现英文单词。",
                "分析倒地姿态、身体活动、尝试起身、持续低位、求助动作、遮挡、可见性和环境风险。",
                "画面不足时使用 unknown 或 insufficient_visual_evidence，不得猜测。",
                "不得诊断骨折、脑出血、昏迷、死亡或任何具体疾病。",
                "不得推断身份、姓名、年龄、诊断、位置或房间。",
                "不得修改、否定或重新裁决前级跌倒确认结果。",
                "不得输出路径、URL、RTSP 地址、凭据或任何标识符。",
            ],
        }
        serialized = json.dumps(content, ensure_ascii=False)
        if _PATH_PATTERN.search(serialized) or _URL_PATTERN.search(serialized):
            raise QwenKeyframeError("post-fall payload contains forbidden metadata")
        return {
            "model": self.model_name,
            "stream": False,
            "think": False,
            "format": _ollama_post_fall_json_schema(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是本机跌倒事件后状态分析模型。跌倒已由前级系统确认；"
                        "你只做事件后语义补充。只返回请求的 JSON 对象。"
                    ),
                },
                {
                    "role": "user",
                    "content": serialized,
                    "images": [base64.b64encode(image.image_bytes).decode("ascii") for image in images],
                },
            ],
        }

    def _advisory(
        self,
        status: str,
        *,
        missing_reasons: Sequence[str] = (),
        error_code: str | None = None,
    ) -> QwenKeyframeAdvisory:
        return QwenKeyframeAdvisory(
            analysis_status=status,  # type: ignore[arg-type]
            provider="ollama_qwen",
            model_name=self.model_name,
            missing_reasons=_bounded_strings(missing_reasons),
            error_code=error_code,
            completed_at=event_now_iso(),
        )


def _response_content(payload: Mapping[str, Any] | str) -> Mapping[str, Any]:
    value: Any = payload
    if isinstance(value, str):
        value = _extract_json_object(value)
    if not isinstance(value, Mapping):
        raise QwenKeyframeInvalidOutput("Ollama returned a non-object response")
    if "message" in value:
        message = value.get("message")
        if not isinstance(message, Mapping):
            raise QwenKeyframeInvalidOutput("Ollama response message is invalid")
        value = message.get("content")
    if isinstance(value, str):
        value = _extract_json_object(value)
    if not isinstance(value, Mapping):
        raise QwenKeyframeInvalidOutput("Ollama advisory content is not an object")
    return value


def _extract_json_object(value: str) -> Mapping[str, Any]:
    candidates = _JSON_FENCE_PATTERN.findall(value)
    candidates.append(value)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start, character in enumerate(candidate):
            if character != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                return parsed
    raise QwenKeyframeInvalidOutput("Ollama message content does not contain a JSON object")


def _bounded_raw_response(payload: Mapping[str, Any] | str) -> str:
    if isinstance(payload, str):
        value = payload
    else:
        message = payload.get("message") if isinstance(payload, Mapping) else None
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, str):
            value = content
        else:
            value = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return value[:4096]


def _parse_status_for_raw_response(status: str, raw_response: str | None) -> str:
    if status != "completed":
        return status
    if raw_response is not None and raw_response.lstrip().startswith("{"):
        return "direct_json_normalized"
    return "recovered_json_object"


def _ollama_advisory_json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "scene_summary", "posture_description", "movement_description",
            "possible_false_positive_reasons", "care_advice", "confidence_explanation", "advisory_confidence",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": "qwen_keyframe_advisory.v1"},
            "scene_summary": {"type": "string"},
            "posture_description": {"type": "string"},
            "movement_description": {"type": "string"},
            "possible_false_positive_reasons": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "care_advice": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            "confidence_explanation": {"type": "string"},
            "advisory_confidence": {"type": "string", "enum": ["low", "medium", "high", "unknown"]},
        },
    }


def _ollama_post_fall_json_schema() -> dict[str, Any]:
    text_or_unknown = {"type": "string", "minLength": 1, "maxLength": 600}
    enum_with_unknown = lambda values: {"type": "string", "enum": [*values, "unknown", "insufficient_visual_evidence"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "posture", "movement_level", "attempt_to_stand",
            "persistent_ground_state", "possible_help_gesture", "visibility", "occlusion",
            "scene_risks", "summary", "review_points", "confidence",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": "pfv2_post_fall_detail.v1"},
            "posture": text_or_unknown,
            "movement_level": enum_with_unknown(["none_observed", "slight", "active"]),
            "attempt_to_stand": enum_with_unknown(["observed", "not_observed"]),
            "persistent_ground_state": enum_with_unknown(["observed", "not_observed"]),
            "possible_help_gesture": enum_with_unknown(["observed", "not_observed"]),
            "visibility": enum_with_unknown(["good", "limited"]),
            "occlusion": enum_with_unknown(["none", "partial", "severe"]),
            "scene_risks": {"type": "array", "items": text_or_unknown, "maxItems": 8},
            "summary": text_or_unknown,
            "review_points": {"type": "array", "items": text_or_unknown, "minItems": 1, "maxItems": 8},
            "confidence": {"anyOf": [{"type": "number", "minimum": 0.0, "maximum": 1.0}, {"type": "null"}]},
        },
    }


def _parse_advisory(payload: Mapping[str, Any]) -> QwenKeyframeAdvisory:
    forbidden = set(payload) & _FORBIDDEN_OUTPUT_FIELDS
    if forbidden:
        raise QwenKeyframeInvalidOutput(f"Ollama advisory contains forbidden fields: {sorted(forbidden)}")
    if payload.get("schema_version") != "qwen_keyframe_advisory.v1":
        raise QwenKeyframeInvalidOutput("unexpected keyframe advisory schema_version")
    allowed = {
        "schema_version", "scene_summary", "posture_description", "movement_description",
        "possible_false_positive_reasons", "care_advice", "confidence_explanation", "advisory_confidence",
    }
    unexpected = set(payload) - allowed
    if unexpected:
        raise QwenKeyframeInvalidOutput(f"Ollama advisory contains unexpected fields: {sorted(unexpected)}")
    try:
        advisory = QwenKeyframeAdvisory.model_validate({
            **payload,
            "analysis_status": "completed",
            "scene_summary": _safe_chinese_text(payload.get("scene_summary")),
            "posture_description": _safe_chinese_text(payload.get("posture_description")),
            "movement_description": _safe_chinese_text(payload.get("movement_description")),
            "possible_false_positive_reasons": _bounded_chinese_strings(payload.get("possible_false_positive_reasons") or ()),
            "care_advice": _bounded_chinese_strings(payload.get("care_advice") or ()),
            "confidence_explanation": _safe_chinese_text(payload.get("confidence_explanation")),
        })
    except ValidationError as exc:
        raise QwenKeyframeInvalidOutput(str(exc)) from exc
    return advisory


def _parse_post_fall_detail(payload: Mapping[str, Any]) -> QwenPostFallDetail:
    forbidden = set(payload) & _FORBIDDEN_OUTPUT_FIELDS
    if forbidden:
        raise QwenKeyframeInvalidOutput(f"Ollama post-fall detail contains forbidden fields: {sorted(forbidden)}")
    normalized_payload = _normalize_post_fall_payload(payload)
    schema_version = normalized_payload.get("schema_version")
    if schema_version not in {None, "pfv2_post_fall_detail.v1"}:
        raise QwenKeyframeInvalidOutput("unexpected post-fall schema_version")
    allowed_values = {
        "movement_level": {"none_observed", "slight", "active", "unknown", "insufficient_visual_evidence"},
        "attempt_to_stand": {"observed", "not_observed", "unknown", "insufficient_visual_evidence"},
        "persistent_ground_state": {"observed", "not_observed", "unknown", "insufficient_visual_evidence"},
        "possible_help_gesture": {"observed", "not_observed", "unknown", "insufficient_visual_evidence"},
        "visibility": {"good", "limited", "unknown", "insufficient_visual_evidence"},
        "occlusion": {"none", "partial", "severe", "unknown", "insufficient_visual_evidence"},
    }
    normalized: dict[str, Any] = {
        "posture": _safe_chinese_or_unknown(normalized_payload.get("posture")),
    }
    for field_name, values in allowed_values.items():
        value = _normalize_post_fall_enum(field_name, normalized_payload.get(field_name))
        if value not in values:
            value = "unknown"
        normalized[field_name] = value
    scene_risks = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("scene_risks")))
    review_points = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("review_points")))
    if not review_points:
        review_points = ["建议人工复核事件关键帧。"]
    confidence = normalized_payload.get("confidence")
    if confidence is not None:
        confidence = _normalize_confidence(confidence)
    return QwenPostFallDetail(
        posture=normalized["posture"],
        movement_level=normalized["movement_level"],
        attempt_to_stand=normalized["attempt_to_stand"],
        persistent_ground_state=normalized["persistent_ground_state"],
        possible_help_gesture=normalized["possible_help_gesture"],
        visibility=normalized["visibility"],
        occlusion=normalized["occlusion"],
        scene_risks=scene_risks,
        summary=_safe_chinese_or_unknown(normalized_payload.get("summary")),
        review_points=review_points,
        confidence=confidence,
        latency_ms=0.0,
    )


def _normalize_post_fall_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized[_POST_FALL_FIELD_ALIASES.get(key, key)] = value
    return normalized


def _normalize_post_fall_enum(field_name: str, value: Any) -> str:
    if isinstance(value, bool):
        value = "observed" if value else "not_observed"
    if not isinstance(value, str):
        return "unknown"
    compact = value.strip().lower()
    if compact in _UNKNOWN_ENUM_VALUES:
        return "unknown"
    return _POST_FALL_ENUM_ALIASES.get(field_name, {}).get(compact, compact)


def _normalize_confidence(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip().removesuffix("%"))
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric > 1.0 and numeric <= 100.0:
        numeric /= 100.0
    if not 0.0 <= numeric <= 1.0:
        return None
    return numeric


def _is_local_ollama_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _safe_event_value(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 80 or _PATH_PATTERN.search(value) or _URL_PATTERN.search(value):
        return None
    return value


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QwenKeyframeInvalidOutput("expected advisory text field is not a string")
    value = value.strip()
    if _PATH_PATTERN.search(value) or _URL_PATTERN.search(value):
        raise QwenKeyframeInvalidOutput("advisory text contains a forbidden path or URL")
    return value[:_MAX_TEXT_LENGTH]


def _safe_chinese_text(value: Any) -> str | None:
    value = _safe_text(value)
    if value is None:
        return None
    if not _CJK_PATTERN.search(value) or _LATIN_PATTERN.search(value):
        raise QwenKeyframeNonChineseOutput("advisory text must be Simplified Chinese without Latin words")
    return value


def _safe_chinese_or_unknown(value: Any) -> str:
    if value in {"unknown", "insufficient_visual_evidence"}:
        return str(value)
    try:
        normalized = _safe_chinese_text(value)
    except QwenKeyframeNonChineseOutput:
        return "unknown"
    if not normalized:
        return "unknown"
    return _remove_medical_diagnosis(normalized)


def _bounded_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise QwenKeyframeInvalidOutput("advisory list item is not a string")
        normalized = _safe_text(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:8]


def _bounded_chinese_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise QwenKeyframeInvalidOutput("advisory list item is not a string")
        normalized = _safe_chinese_text(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result[:8]


def _bounded_chinese_or_unknown_strings(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _safe_chinese_or_unknown(value)
        if normalized not in result:
            result.append(normalized)
    return result[:8]


def _as_sequence(value: Any) -> Sequence[Any]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence):
        return value
    return ()


def _remove_medical_diagnosis(value: str) -> str:
    if _MEDICAL_DIAGNOSIS_PATTERN.search(value):
        return "仅可依据画面描述，建议人工复核。"
    return value
