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


class QwenKeyframeContextExceeded(QwenKeyframeError):
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
    fall_verdict: str
    high_risk_fall: int
    scene_type: str
    recommended_action: str
    positive_evidence: list[str]
    negative_evidence: list[str]
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
    raw_fall_verdict: str | None = None
    consistency_status: str = "unchanged"
    consistency_reason: str | None = None
    activity: str = "unknown"
    posture_state: str = "unknown"
    fall_transition_visible: bool | None = None
    intentional_action_evidence: bool | None = None
    recovery_observed: bool | None = None


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
_REVIEW_REQUEST_PATTERN = re.compile(r"人工复核|建议复核|复核现场|复核事件|复核关键帧")
_POST_FALL_FIELD_ALIASES = {
    "verdict": "fall_verdict",
    "fall_decision": "fall_verdict",
    "risk_control": "high_risk_fall",
    "high_risk": "high_risk_fall",
    "is_high_risk_fall": "high_risk_fall",
    "scene": "scene_type",
    "action": "recommended_action",
    "recommendation": "recommended_action",
    "review_suggestion": "recommended_action",
    "positive_reasons": "positive_evidence",
    "negative_reasons": "negative_evidence",
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
_FALL_VERDICT_ALIASES = {
    "normal_activity": "normal_activity",
    "normal": "normal_activity",
    "normal_activity": "normal_activity",
    "non_fall": "non_fall",
    "not_fall": "non_fall",
    "no_fall": "non_fall",
    "非跌倒": "non_fall",
    "正常活动": "normal_activity",
    "正常站立": "normal_activity",
    "正常行走": "normal_activity",
    "正常坐姿": "normal_activity",
    "普通活动": "normal_activity",
    "正常移动": "normal_activity",
    "经过镜头": "normal_activity",
    "confirmed_fall": "confirmed_fall",
    "fall": "confirmed_fall",
    "confirmed": "confirmed_fall",
    "确认跌倒": "confirmed_fall",
    "确认摔倒": "confirmed_fall",
    "intentional_low_posture": "intentional_low_posture",
    "intentional": "intentional_low_posture",
    "自主低姿态": "intentional_low_posture",
    "主动躺卧": "intentional_low_posture",
    "主动坐下": "intentional_low_posture",
    "自主坐下": "intentional_low_posture",
    "主动躺下": "intentional_low_posture",
    "自主躺下": "intentional_low_posture",
    "主动坐下看书": "intentional_low_posture",
    "坐下看书": "intentional_low_posture",
    "坐下玩手机": "intentional_low_posture",
    "躺下看书": "intentional_low_posture",
    "躺下玩手机": "intentional_low_posture",
    "躺下睡觉": "intentional_low_posture",
    "主动恢复低位": "intentional_low_posture",
    "休息": "intentional_low_posture",
    "unclear": "unclear",
    "uncertain": "unclear",
    "unknown": "unclear",
    "不明确": "unclear",
    "无法判断": "unclear",
    "insufficient_visual_evidence": "insufficient_visual_evidence",
    "画面不足": "insufficient_visual_evidence",
}

_POST_FALL_SYSTEM_PROMPT = """你是 Post-Fall V2 候选事件视觉复核模型。前级 FALL 仅表示候选，不代表真实跌倒。

根据按时间顺序排列的关键帧，独立判断人物实际动作和可见状态，只描述画面证据，不推测未观察到的过程。

最终高危控制规则：
`high_risk_fall` 是最终跌倒告警硬控制位，只能为整数 0 或 1，默认必须为 0。
只有视觉证据明确支持真实、非主动、具有危险性的跌倒，才允许 `high_risk_fall=1`。
正常站立、行走、坐下、坐在椅子/沙发/床边休息、弯腰、蹲下、主动受控下降、主动躺下、低姿态看书、玩手机、休息、睡觉、仅靠近地面、仅横向姿态、仅静止、证据不足、遮挡严重、无法判断、只是建议人工复核，都必须保持 `high_risk_fall=0`。
如果最早关键帧缺失，但后帧已经清楚呈现非自主翻倒、冲击后倒地或持续异常卧地状态，仍可判为 `confirmed_fall`；如果既看不到进入过程，也看不到这类异常倒地状态，才输出 `uncertain`。
“建议人工复核”绝对不等于“确认跌倒”，不能触发高危值。
若 `high_risk_fall=1`，则 `fall_verdict` 必须为 `confirmed_fall`，`scene_type` 必须为 `fall`，`recommended_action` 必须为 `emergency_alert`。
若 `high_risk_fall=0`，则 `fall_verdict` 不得为 `confirmed_fall`，`recommended_action` 不得为 `emergency_alert`。

判定规则：

- `confirmed_fall`：明确看到人物发生非自主失衡或失控下落并倒地；或虽未拍到完整过程，但后帧已明确呈现非自主翻倒、冲击后倒地或异常卧地状态，持续未恢复，且没有主动坐下、主动躺下、阅读、玩手机、休息等自主行为证据。
- `non_fall`：站立、行走、转身、普通活动、稳定坐姿、坐椅子休息、主动低姿态、阅读、玩手机、休息或睡觉。
- `uncertain`：只看到人物已处于地面或低位、动作过程缺失、证据矛盾，或无法可靠判断是否发生跌倒。
- `insufficient_visual_evidence`：人物不可见、严重遮挡或画面质量不足。

重要约束：
不得仅因前级 FALL、身体倾斜、运动模糊、坐着、躺着或靠近地面而判定跌倒。
未看到跌倒转场且后帧也没有异常翻倒、冲击后倒地或持续异常卧地状态时，即使人物在所提供关键帧时间跨度内持续低位，也不得推测曾发生跌倒。
如果人物臀部或躯干受到椅子、沙发、床等正常支撑面支撑，姿态稳定且没有突然失衡或失去支撑，必须输出 `scene_type=seated_rest`、`high_risk_fall=0`、`fall_verdict=non_fall`、`recommended_action=no_alert`。
`fall_transition_visible` 只能根据真实可见转场填写。
主动行为只有在有明确可见证据时才能成立。
`persistent_ground_state = observed` 只表示人物在所提供关键帧时间跨度内持续低位，不表示已经持续十秒。
`fall_verdict`、`high_risk_fall`、`scene_type`、`recommended_action`、`posture_state`、`fall_transition_visible`、`intentional_action_evidence`、`recovery_observed`、`persistent_ground_state` 和 `summary` 必须语义一致。

只返回规定的 JSON 对象，不输出解释、Markdown 或额外文字。"""


class QwenKeyframeAnalyzer:
    """Calls a localhost-only Ollama vision model with image bytes, never paths."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        model_name: str,
        timeout_seconds: float,
        transport: QwenTransport | None = None,
        num_ctx: int = 8192,
        max_output_tokens: int = 96,
        temperature: float = 0.0,
        context_retry_enabled: bool = True,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self._transport = transport
        self.num_ctx = max(4096, int(num_ctx))
        self.max_output_tokens = max(64, min(1024, int(max_output_tokens)))
        self.temperature = max(0.0, float(temperature))
        self.context_retry_enabled = bool(context_retry_enabled)
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
            response_payload = self._send_payload(payload)
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
        review_mode: str = "initial",
    ) -> QwenPostFallDetail:
        """Review a binary-model candidate and independently decide whether it is a real fall."""
        if not images:
            raise QwenKeyframeError("post-fall analysis requires at least one keyframe image")
        if not _is_local_ollama_url(self.endpoint_url):
            raise QwenKeyframeError("Qwen keyframe analysis endpoint must be localhost")
        payload = self.build_post_fall_payload(
            images=images,
            keyframe_status=keyframe_status,
            missing_offsets_ms=missing_offsets_ms,
            review_mode=review_mode,
        )
        started = time.perf_counter()
        try:
            try:
                response_payload = self._send_payload(payload)
            except QwenKeyframeContextExceeded:
                if not self.context_retry_enabled:
                    raise
                retry_payload = self.build_post_fall_payload(
                    images=images,
                    keyframe_status=keyframe_status,
                    missing_offsets_ms=missing_offsets_ms,
                    review_mode=review_mode,
                    compact=True,
                )
                response_payload = self._send_payload(retry_payload)
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

    def _send_payload(self, payload: Mapping[str, Any]) -> Mapping[str, Any] | str:
        try:
            if self._transport is not None:
                return self._transport(payload, self.timeout_seconds)
            response = requests.post(self.endpoint_url, json=payload, timeout=self.timeout_seconds)
            if response.status_code >= 400:
                message = _http_error_message(response)
                if _is_context_exceeded(message):
                    raise QwenKeyframeContextExceeded(message)
                raise QwenKeyframeError(message)
            return response.json()
        except QwenKeyframeError:
            raise
        except requests.Timeout:
            raise
        except requests.RequestException as exc:
            message = _request_error_message(exc)
            if _is_context_exceeded(message):
                raise QwenKeyframeContextExceeded(message) from exc
            raise

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
            "keep_alive": -1,
            "options": self._ollama_options(),
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
        review_mode: str = "initial",
        compact: bool = False,
    ) -> dict[str, Any]:
        countercheck = review_mode == "countercheck"
        content = {
            "schema_version": "pfv2_post_fall_input.v1",
            "task": _build_compact_post_fall_task(countercheck=countercheck) if compact else _build_post_fall_task(countercheck=countercheck),
            "keyframes": [
                {"offset_ms": image.offset_ms, "role": image.role}
                for image in images
            ],
            "keyframe_timeline": _post_fall_keyframe_timeline(images),
            "keyframe_status": _safe_event_value(keyframe_status),
            "missing_offsets_ms": [int(value) for value in missing_offsets_ms],
            "review_mode": "反证复核" if countercheck else "首次复核",
            "constraints": [
                "只返回符合给定结构的 JSON 对象，不要输出解释、Markdown 或额外文字。",
                "所有自然语言描述必须使用简体中文，不得出现英文单词。",
                "只输出安全判定所需字段；最终是否告警由确定性事件状态机决定，不由你直接决定。",
                "posture 不超过 40 个汉字，summary 不超过 80 个汉字；两者均只描述可见画面，不重复说明。",
                "示例只用于学习判定边界，不得把示例人物、物品、动作或场景复制到当前事件。",
                "这是前级模型触发的候选事件，候选事件可能是正常活动、主动低姿态、画面不足或真实跌倒；必须从零判断实际动作。",
                "先判断连续关键帧实际发生了什么：正常活动、主动受控进入低位、真实非自主失衡倒地，还是过程不清楚。",
                "confirmed_fall 只允许两条证据路径：一是完整看到较高姿态到非自主失衡、失控下降并真正倒地的转场；二是虽未完整看到转场，但后帧持续异常卧地、未恢复且无主动行为证据。前者可将 fall_transition_visible 记为 true，后者可记为 false。",
                "人物最终坐在地面、垫子、床或躺在地面本身，不是确认跌倒的充分依据。",
                "只看到人物已处于低位且进入过程缺失时输出 unclear；如果后帧持续异常卧地、未恢复且无主动行为证据，则可判 confirmed_fall。",
                "persistent_ground_state=observed 只表示在所给关键帧跨度内持续低位，不代表已经持续十秒。",
                "如果文字已经明确说明主动坐下、主动躺下、坐下看书/玩手机、躺下看书/玩手机/睡觉、主动恢复低位、没有明显失衡，则 fall_verdict 不能写成 confirmed_fall。",
                "如果先看见突然失衡、急速下落、肢体翻起、伸手撑地、撞向地面或非自主倒地，随后人物又坐起、阅读、玩手机或休息，仍可判 confirmed_fall。",
                "清楚显示正常站立、正常行走、正常坐姿、普通活动或经过镜头，且没有真实倒地过程时，使用 normal_activity。",
                "空场景、无人或画面不足时使用 insufficient_visual_evidence，不得猜测有人或跌倒。",
                "不得诊断骨折、脑出血、昏迷、死亡或任何具体疾病。",
                "不得推断身份、姓名、年龄、诊断、位置或房间。",
                "不得把二分类候选结果当作视觉事实；不得仅凭持续低位、未起身、垫子或可见性来确认跌倒，也不得忽略跨帧真实可见的失衡过程。",
                "触发帧或中间帧严重运动模糊时，不得把模糊本身当作失衡证据；必须结合前后清晰帧确认人体是否真的倒向地面。",
                "如果后帧显示人物仍在站立、行走、经过镜头或只有腿部近景，而不是倒地后的低位状态，不能确认跌倒。",
                "fall_verdict 和安全判定字段必须一致；证据矛盾时输出 unclear，不得用结论反推或补造证据。",
                "不得输出路径、URL、RTSP 地址、凭据或任何标识符。",
            ],
            "profile": "compact_retry" if compact else "full",
        }
        serialized = json.dumps(content, ensure_ascii=False)
        if _PATH_PATTERN.search(serialized) or _URL_PATTERN.search(serialized):
            raise QwenKeyframeError("post-fall payload contains forbidden metadata")
        return {
            "model": self.model_name,
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": self._ollama_options(),
            "format": _ollama_post_fall_json_schema(),
            "messages": [
                {
                    "role": "system",
                    "content": _POST_FALL_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": serialized,
                    "images": [base64.b64encode(image.image_bytes).decode("ascii") for image in images],
                },
            ],
        }

    def _ollama_options(self) -> dict[str, float | int]:
        return {
            "num_ctx": self.num_ctx,
            "num_predict": self.max_output_tokens,
            "temperature": self.temperature,
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


def _http_error_message(response: requests.Response) -> str:
    body = response.text.strip()
    if body:
        return f"{response.status_code} {body}"
    return f"{response.status_code} {response.reason}"


def _request_error_message(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        return _http_error_message(response)
    return str(exc)


def _is_context_exceeded(message: str) -> bool:
    lowered = message.lower()
    return (
        "exceeds the available context size" in lowered
        or "exceed_context_size" in lowered
        or ("context" in lowered and "exceed" in lowered)
    )


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
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "high_risk_fall", "fall_verdict", "scene_type", "recommended_action",
            "activity", "posture_state",
            "fall_transition_visible", "intentional_action_evidence", "recovery_observed",
            "persistent_ground_state", "posture", "summary", "confidence",
        ],
        "properties": {
            "high_risk_fall": {"type": "integer", "enum": [0, 1]},
            "fall_verdict": {"type": "string", "enum": ["confirmed_fall", "non_fall", "uncertain", "insufficient_visual_evidence"]},
            "scene_type": {
                "type": "string",
                "enum": [
                    "fall", "seated_rest", "standing", "walking", "intentional_low_posture",
                    "intentional_lying", "squatting", "bending", "other", "unknown",
                ],
            },
            "recommended_action": {"type": "string", "enum": ["no_alert", "manual_review", "emergency_alert"]},
            "activity": {"type": "string", "minLength": 1, "maxLength": 64},
            "posture_state": {"type": "string", "enum": ["upright", "seated", "lying", "ground_low", "unknown"]},
            "fall_transition_visible": {"type": "boolean"},
            "intentional_action_evidence": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "recovery_observed": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "persistent_ground_state": {"type": "string", "enum": ["observed", "not_observed", "unknown", "insufficient_visual_evidence"]},
            "posture": {"type": "string", "minLength": 1, "maxLength": 80},
            "summary": {"type": "string", "minLength": 1, "maxLength": 160},
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
    posture = _safe_chinese_or_unknown(normalized_payload.get("posture"))
    summary = _safe_chinese_or_unknown(normalized_payload.get("summary"))
    normalized: dict[str, Any] = {
        "posture": posture,
    }
    for field_name, values in allowed_values.items():
        value = _normalize_post_fall_enum(field_name, normalized_payload.get(field_name))
        if value not in values:
            value = "unknown"
        normalized[field_name] = value
    scene_risks = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("scene_risks")))
    review_points = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("review_points")))
    positive_evidence = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("positive_evidence")))
    negative_evidence = _bounded_chinese_or_unknown_strings(_as_sequence(normalized_payload.get("negative_evidence")))
    confidence = normalized_payload.get("confidence")
    if confidence is not None:
        confidence = _normalize_confidence(confidence)
    activity = str(normalized_payload.get("activity") or "unknown").strip()[:64] or "unknown"
    scene_type = _normalize_scene_type(normalized_payload.get("scene_type"))
    recommended_action = _normalize_recommended_action(normalized_payload.get("recommended_action"))
    high_risk_fall = _normalize_high_risk_fall(normalized_payload.get("high_risk_fall"))
    posture_state = _normalize_posture_state(normalized_payload.get("posture_state"), normalized["posture"])
    transition_visible = _normalize_optional_bool(normalized_payload.get("fall_transition_visible"))
    intentional_evidence = _normalize_optional_bool(normalized_payload.get("intentional_action_evidence"))
    recovery_observed = _normalize_optional_bool(normalized_payload.get("recovery_observed"))
    intentional_context = _has_verified_intentional_context(
        f"{activity} {posture} {summary}",
        posture_state=posture_state,
    )
    if (
        intentional_evidence is True
        and posture_state in {"lying", "ground_low"}
        and not intentional_context
    ):
        intentional_evidence = False
    effective_fall_verdict = _post_fall_verdict_for_internal_consistency(
        normalized_payload.get("fall_verdict"),
        scene_type=scene_type,
        intentional_action_evidence=intentional_evidence,
    )
    consistency = validate_post_fall_consistency(
        effective_fall_verdict,
        posture,
        summary,
        activity=activity,
        posture_state=posture_state,
        fall_transition_visible=transition_visible,
        intentional_action_evidence=intentional_evidence,
        recovery_observed=recovery_observed,
        persistent_ground_state=normalized["persistent_ground_state"],
        high_risk_fall=high_risk_fall,
        scene_type=scene_type,
    )
    normalized["fall_verdict"] = consistency["normalized_verdict"]
    if high_risk_fall == 1 and (
        normalized["fall_verdict"] != "confirmed_fall"
        or scene_type != "fall"
        or recommended_action != "emergency_alert"
    ):
        high_risk_fall = 0
        if normalized["fall_verdict"] == "confirmed_fall":
            normalized["fall_verdict"] = "unclear"
        consistency = _corrected_consistency(
            consistency,
            "high_risk_fall=1 与 fall_verdict/scene_type/recommended_action 不一致，已按安全默认降级",
        )
    elif high_risk_fall == 0 and normalized["fall_verdict"] == "confirmed_fall":
        normalized["fall_verdict"] = "unclear"
        consistency = _corrected_consistency(
            consistency,
            "confirmed_fall 缺少 high_risk_fall=1 的高危控制位支持，已按安全默认降级",
        )
    if normalized["fall_verdict"] != "confirmed_fall":
        high_risk_fall = 0
    if high_risk_fall == 1:
        scene_type = "fall"
        recommended_action = "emergency_alert"
    elif recommended_action == "emergency_alert":
        recommended_action = "no_alert" if normalized["fall_verdict"] in {"normal_activity", "intentional_low_posture", "non_fall"} else "manual_review"
    if normalized["fall_verdict"] == "intentional_low_posture":
        review_points = [point for point in review_points if not _REVIEW_REQUEST_PATTERN.search(point)]
    elif not review_points:
        review_points = ["建议人工复核事件关键帧。"]
    return QwenPostFallDetail(
        fall_verdict=normalized["fall_verdict"],
        high_risk_fall=high_risk_fall,
        scene_type=scene_type,
        recommended_action=recommended_action,
        positive_evidence=positive_evidence,
        negative_evidence=negative_evidence,
        posture=normalized["posture"],
        movement_level=normalized["movement_level"],
        attempt_to_stand=normalized["attempt_to_stand"],
        persistent_ground_state=normalized["persistent_ground_state"],
        possible_help_gesture=normalized["possible_help_gesture"],
        visibility=normalized["visibility"],
        occlusion=normalized["occlusion"],
        scene_risks=scene_risks,
        summary=summary,
        review_points=review_points,
        confidence=confidence,
        latency_ms=0.0,
        raw_fall_verdict=consistency["raw_verdict"],
        consistency_status=consistency["consistency_status"],
        consistency_reason=consistency["consistency_reason"],
        activity=activity,
        posture_state=posture_state,
        fall_transition_visible=transition_visible,
        intentional_action_evidence=intentional_evidence,
        recovery_observed=recovery_observed,
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


def _normalize_high_risk_fall(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and not isinstance(value, bool):
        return 1 if value == 1 else 0
    if isinstance(value, float):
        return 1 if value == 1.0 else 0
    if isinstance(value, str):
        compact = value.strip().lower()
        if compact in {"1", "true", "yes", "高危", "确认高危", "确认跌倒"}:
            return 1
    return 0


def _normalize_scene_type(value: Any) -> str:
    compact = str(value or "").strip().lower()
    aliases = {
        "fall": "fall",
        "confirmed_fall": "fall",
        "seated": "seated_rest",
        "seated_rest": "seated_rest",
        "chair_rest": "seated_rest",
        "sitting_rest": "seated_rest",
        "standing": "standing",
        "walking": "walking",
        "intentional_low_posture": "intentional_low_posture",
        "intentional_lying": "intentional_lying",
        "lying_rest": "intentional_lying",
        "squatting": "squatting",
        "bending": "bending",
        "other": "other",
        "unknown": "unknown",
        "unclear": "unknown",
        "uncertain": "unknown",
        "坐椅子休息": "seated_rest",
        "坐姿休息": "seated_rest",
        "正常坐姿": "seated_rest",
        "低姿态看书": "intentional_low_posture",
        "主动低姿态": "intentional_low_posture",
        "主动躺卧": "intentional_lying",
        "正常行走": "walking",
        "正常站立": "standing",
    }
    return aliases.get(compact, "unknown")


def _normalize_recommended_action(value: Any) -> str:
    compact = str(value or "").strip().lower()
    aliases = {
        "no_alert": "no_alert",
        "none": "no_alert",
        "dismiss": "no_alert",
        "manual_review": "manual_review",
        "review": "manual_review",
        "human_review": "manual_review",
        "emergency_alert": "emergency_alert",
        "alert": "emergency_alert",
        "alarm": "emergency_alert",
        "不告警": "no_alert",
        "无需告警": "no_alert",
        "人工复核": "manual_review",
        "建议人工复核": "manual_review",
        "紧急告警": "emergency_alert",
        "跌倒告警": "emergency_alert",
    }
    return aliases.get(compact, "manual_review")


def _post_fall_verdict_for_internal_consistency(
    value: Any,
    *,
    scene_type: str,
    intentional_action_evidence: bool | None,
) -> Any:
    normalized = _normalize_fall_verdict(value)
    if normalized == "normal_activity" and scene_type in {"intentional_low_posture", "intentional_lying"}:
        return "intentional_low_posture"
    return normalized


def _corrected_consistency(consistency: Mapping[str, str | None], reason: str) -> dict[str, str | None]:
    return {
        "raw_verdict": consistency.get("raw_verdict"),
        "normalized_verdict": "unclear",
        "consistency_status": "corrected",
        "consistency_reason": reason,
    }


def _normalize_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        compact = value.strip().lower()
        if compact in {"true", "yes", "observed", "是", "有", "可见"}:
            return True
        if compact in {"false", "no", "not_observed", "否", "无", "未见"}:
            return False
    return None


def _normalize_posture_state(value: Any, posture: str) -> str:
    compact = str(value or "").strip().lower()
    if compact in {"upright", "seated", "lying", "ground_low", "unknown"}:
        return compact
    if any(marker in posture for marker in ("倒地", "贴地", "地面", "趴伏")):
        return "ground_low"
    if any(marker in posture for marker in ("躺", "卧")):
        return "lying"
    if "坐" in posture:
        return "seated"
    if any(marker in posture for marker in ("站", "直立", "行走")):
        return "upright"
    return "unknown"


def _normalize_fall_verdict(value: Any) -> str:
    raw_text = value.strip().lower() if isinstance(value, str) else ""
    return _FALL_VERDICT_ALIASES.get(raw_text, "unclear")


def _normalize_fall_verdict_with_context(value: Any, posture: Any, summary: Any) -> str:
    return validate_post_fall_consistency(value, posture, summary)["normalized_verdict"] or "unclear"


def validate_post_fall_consistency(
    raw_verdict: Any,
    posture: Any,
    summary: Any,
    *,
    activity: Any = None,
    posture_state: Any = None,
    fall_transition_visible: Any = None,
    intentional_action_evidence: Any = None,
    recovery_observed: Any = None,
    persistent_ground_state: Any = None,
    high_risk_fall: Any = None,
    scene_type: Any = None,
) -> dict[str, str | None]:
    """Reject semantic conclusions that are not supported by explicit evidence fields."""
    raw_text = raw_verdict.strip().lower() if isinstance(raw_verdict, str) else ""
    raw_normalized = _FALL_VERDICT_ALIASES.get(raw_text, "unclear")
    text = f"{_compact_text(activity)} {_compact_text(posture)} {_compact_text(summary)}".strip()
    explicit_fall = _looks_like_explicit_fall_sequence(text)
    intentional = _looks_like_intentional_low_posture(text)
    normal = _looks_like_non_fall_activity(text)
    transition_visible = _normalize_optional_bool(fall_transition_visible)
    intentional_evidence = _normalize_optional_bool(intentional_action_evidence)
    recovery_value = _normalize_optional_bool(recovery_observed)
    posture_value = str(posture_state or "unknown").strip().lower()
    persistent_value = str(persistent_ground_state or "unknown").strip().lower()
    high_risk = _normalize_high_risk_fall(high_risk_fall) == 1
    scene_value = _normalize_scene_type(scene_type)
    verified_normal_scene = (
        scene_value in {"walking", "standing", "seated_rest"}
        and posture_value in {"upright", "seated"}
    )
    verified_intentional_scene = (
        scene_value in {"intentional_low_posture", "intentional_lying"}
        and intentional_evidence is True
    )
    abnormal_persistent_ground = (
        posture_value in {"lying", "ground_low"}
        and persistent_value == "observed"
        and recovery_value is False
        and intentional_evidence is not True
        and scene_value not in {"walking", "standing", "seated_rest", "intentional_low_posture", "intentional_lying", "squatting", "bending"}
    )

    if raw_normalized == "confirmed_fall":
        if transition_visible is not True:
            if (
                high_risk
                and scene_value == "fall"
                and posture_value in {"lying", "ground_low"}
                and persistent_value == "observed"
                and recovery_value is False
                and intentional_evidence is not True
                and not intentional
                and not normal
            ):
                return {
                    "raw_verdict": raw_text or raw_normalized,
                    "normalized_verdict": "confirmed_fall",
                    "consistency_status": "unchanged",
                    "consistency_reason": None,
                }
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "confirmed_fall 必须满足 transition_fall 或 post_fall_abnormality 两类证据之一",
            }
        if intentional_evidence is True or intentional or normal:
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "跌倒转场结论与主动行为或正常活动证据冲突",
            }
        if explicit_fall:
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "confirmed_fall",
                "consistency_status": "unchanged",
                "consistency_reason": None,
            }
        return {
            "raw_verdict": raw_text or raw_normalized,
            "normalized_verdict": "unclear",
            "consistency_status": "corrected",
            "consistency_reason": "fall_transition_visible=true 但文字缺少明确失衡、下落和倒地语义",
        }

    if raw_normalized == "intentional_low_posture":
        if transition_visible is True or intentional_evidence is not True or not verified_intentional_scene or explicit_fall:
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "intentional_low_posture 缺少明确主动行为证据或与跌倒转场证据冲突",
            }

    if raw_normalized == "non_fall":
        if transition_visible is True or explicit_fall or abnormal_persistent_ground:
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "non_fall 与跌倒转场、明确跌倒或异常持续低位证据冲突",
            }
        if not (verified_normal_scene or verified_intentional_scene):
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "non_fall 需要明确正常或主动低姿态证据支持",
            }

    if raw_normalized == "normal_activity":
        if transition_visible is True or not verified_normal_scene or abnormal_persistent_ground:
            return {
                "raw_verdict": raw_text or raw_normalized,
                "normalized_verdict": "unclear",
                "consistency_status": "corrected",
                "consistency_reason": "normal_activity 缺少明确正常活动证据或与低位持续证据冲突",
            }

    return {
        "raw_verdict": raw_text or raw_normalized,
        "normalized_verdict": raw_normalized,
        "consistency_status": "unchanged",
        "consistency_reason": None,
    }


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


def _compact_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


_INTENTIONAL_LOW_POSTURE_PHRASES = (
    "主动坐下",
    "自主坐下",
    "主动躺下",
    "自主躺下",
    "自主躺卧",
    "受控坐下",
    "受控躺下",
    "主动恢复低位",
    "主动进入低位",
    "主动受控",
    "受控地坐",
    "受控坐",
    "受控地躺",
    "受控躺",
    "主动弯腰并受控坐",
    "主动弯腰坐",
    "自然过渡到坐姿",
    "自然坐下",
    "稳定坐姿",
    "稳定坐在",
    "坐姿看书",
    "坐姿玩手机",
    "持续稳定坐姿",
    "稳定卧姿",
    "自然卧姿",
    "稳定躺姿",
    "稳定躺在",
    "自然躺下",
    "坐下看书",
    "坐下玩手机",
    "躺下看书",
    "躺下玩手机",
    "躺下睡觉",
    "主动休息",
    "主动阅读",
    "没有失衡",
    "未见失衡",
    "未见失稳",
    "不是跌倒",
    "没有发生跌倒",
    "未发生跌倒",
    "而非失稳",
    "更符合主动",
)
_NEGATED_INTENTIONAL_LOW_POSTURE_PHRASES = (
    "没有失衡",
    "未见失衡",
    "未见失稳",
    "不是跌倒",
    "没有发生跌倒",
    "未发生跌倒",
    "而非失稳",
    "更符合主动",
)
_INTENTIONAL_NEGATION_PREFIXES = ("没有", "未见", "未发现", "无", "并非", "不是", "不存在")

_CLEAR_FALL_PHRASES = (
    "突然失去平衡",
    "明显失衡",
    "失控下落",
    "非自主",
    "急速下落",
    "快速倒向地面",
    "非自主倒向地面",
    "失去支撑",
    "突然倒下",
    "迅速倒下",
    "非自主倒地",
    "突然摔倒",
    "突然跌倒",
    "撞向地面",
    "伸手撑地",
    "从直立位置迅速倒下",
)


def _looks_like_intentional_low_posture(text: str) -> bool:
    for phrase in _INTENTIONAL_LOW_POSTURE_PHRASES:
        start = text.find(phrase)
        while start >= 0:
            if phrase in _NEGATED_INTENTIONAL_LOW_POSTURE_PHRASES or not _has_negation_prefix(text, start):
                return True
            start = text.find(phrase, start + len(phrase))
    return False


def _has_verified_intentional_context(text: str, *, posture_state: str) -> bool:
    """Require a positive purpose/support signal before trusting active low posture."""
    support_signals = (
        "床",
        "沙发",
        "椅子",
        "支撑面",
        "支撑物",
        "床上",
        "沙发上",
        "椅子上",
    )
    purpose_signals = ("看书", "阅读", "玩手机", "睡觉", "睡眠")
    seated_signals = ("坐下", "坐在", "坐姿", "休息", "主动休息", "主动调整身体")
    if posture_state == "seated":
        return any(phrase in text for phrase in (*support_signals, *purpose_signals, *seated_signals))
    if posture_state in {"lying", "ground_low"}:
        return any(phrase in text for phrase in (*support_signals, *purpose_signals))
    return any(phrase in text for phrase in (*support_signals, *purpose_signals, *seated_signals))


def _looks_like_clear_fall(text: str) -> bool:
    return _looks_like_explicit_fall_sequence(text)


_NON_FALL_ACTIVITY_PHRASES = (
    "正在行走",
    "正常行走",
    "行走过程中",
    "行走过程",
    "行走状态",
    "走路",
    "步行",
    "走动",
    "边走边",
    "正常活动",
    "正常移动",
    "普通活动",
    "正常转身",
    "保持站立",
    "站立状态",
    "稳定站立",
    "仍然站立",
    "站着",
    "正常坐姿",
    "稳定坐姿",
    "坐在椅子",
    "坐椅子",
    "椅子上休息",
    "坐在沙发",
    "坐在床边",
    "支撑面",
    "站立状态",
    "正常站立",
    "经过镜头",
    "路过",
)


def _looks_like_non_fall_activity(text: str) -> bool:
    """Detect ordinary activity descriptions that should not become alarms."""
    return any(phrase in text for phrase in _NON_FALL_ACTIVITY_PHRASES)


_EXPLICIT_FALL_SEQUENCE_PHRASES = (
    "先发生明显非自主跌倒",
    "此前已有清楚失衡倒地过程",
    "从直立位置迅速倒下",
    "先明显失衡倒地",
    "非自主倒地",
    "撞向地面后",
)

_FALL_ACTION_PHRASES = (
    *_CLEAR_FALL_PHRASES,
    "失去平衡并倒地",
    "失去平衡后倒地",
    "失衡后倒地",
    "明显失衡并倒下",
    "明显失衡后倒下",
    "突然下坠并倒地",
    "快速下落并倒地",
)
_FALL_OUTCOME_PHRASES = (
    "倒地",
    "倒下",
    "跌倒",
    "摔倒",
    "躺在地上",
    "身体着地",
    "落到地面",
    "趴伏",
    "俯卧",
    "仰卧",
    "侧卧",
)
_NEGATED_FALL_PATTERN = re.compile(
    r"(?:没有|未见|未发现|未观察到|未发生|无|并非|不是|看不出|无法确认|不能确认)"
    r"[^。；，,]{0,14}(?:失衡|失稳|下坠|下落|倒地|倒下|跌倒|摔倒|撞向地面|身体着地)"
)


def _looks_like_explicit_fall_sequence(text: str) -> bool:
    if not text or _NEGATED_FALL_PATTERN.search(text):
        return False
    if any(phrase in text for phrase in _EXPLICIT_FALL_SEQUENCE_PHRASES):
        return True
    has_action = any(phrase in text for phrase in _FALL_ACTION_PHRASES)
    has_outcome = any(phrase in text for phrase in _FALL_OUTCOME_PHRASES)
    return has_action and has_outcome


def _has_negation_prefix(text: str, start: int) -> bool:
    prefix = text[max(0, start - 4):start]
    return any(marker in prefix for marker in _INTENTIONAL_NEGATION_PREFIXES)


def _build_post_fall_task(*, countercheck: bool) -> str:
    review_mode = "反证复核" if countercheck else "首次复核"
    examples = [
        (
            "示例 1 主动坐下看书或玩手机",
            "前帧站立或缓慢移动，随后主动弯腿并受控坐下，后帧稳定阅读或使用手机，没有突然失衡、失控下坠或意外倒地。",
            '{"high_risk_fall":0,"fall_verdict":"non_fall","scene_type":"intentional_low_posture","recommended_action":"no_alert","activity":"主动坐下阅读","posture_state":"seated","fall_transition_visible":false,"intentional_action_evidence":true,"recovery_observed":false,"persistent_ground_state":"not_observed","posture":"人物主动受控地坐下后活动。","summary":"连续画面显示主动坐下阅读，没有非自主失衡。","confidence":0.93}',
        ),
        (
            "示例 2 主动躺下看书、玩手机或睡觉",
            "人物在床、沙发等明确支撑面上有控制地向后或侧面躺下，后帧保持自然卧姿看书、玩手机或睡觉，没有失衡下落。",
            '{"high_risk_fall":0,"fall_verdict":"non_fall","scene_type":"intentional_lying","recommended_action":"no_alert","activity":"主动躺下休息","posture_state":"lying","fall_transition_visible":false,"intentional_action_evidence":true,"recovery_observed":false,"persistent_ground_state":"observed","posture":"人物在明确支撑面上主动进入稳定卧姿。","summary":"动作受控且后续保持自然卧姿，属于主动躺下休息。","confidence":0.91}',
        ),
        (
            "示例 3 真实跌倒",
            "人物原本站立或处于较高姿态，随后身体突然失去平衡并快速向地面倾倒，后帧已倒地，没有主动坐下或躺下的连续动作。",
            '{"high_risk_fall":1,"fall_verdict":"confirmed_fall","scene_type":"fall","recommended_action":"emergency_alert","activity":"非自主失衡倒地","posture_state":"ground_low","fall_transition_visible":true,"intentional_action_evidence":false,"recovery_observed":false,"persistent_ground_state":"observed","posture":"人物由较高姿态突然失衡并非自主倒地。","summary":"连续画面显示明显失衡和失控倒地过程。","confidence":0.96}',
        ),
        (
            "示例 4 触发帧已在翻倒过程后持续异常低位",
            "最早关键帧没有完整跌倒起始动作，但后帧连续呈现异常倒地或贴地状态，人物未恢复，且没有主动坐下、主动躺下、阅读、玩手机、休息或睡觉的证据。",
            '{"high_risk_fall":1,"fall_verdict":"confirmed_fall","scene_type":"fall","recommended_action":"emergency_alert","activity":"持续异常倒地","posture_state":"ground_low","fall_transition_visible":false,"intentional_action_evidence":false,"recovery_observed":false,"persistent_ground_state":"observed","posture":"人物持续处于异常倒地低位状态。","summary":"虽未完整记录跌倒瞬间，但连续画面支持异常倒地且未见自主行为或恢复。","confidence":0.88}',
        ),
        (
            "示例 5 无法确认过程",
            "前后帧只能看见人物短暂或局部处于低位，但既没有看到进入低位的过程，也没有看到后帧异常卧地、持续贴地或未恢复状态，无法可靠区分主动低姿态和真实跌倒。",
            '{"high_risk_fall":0,"fall_verdict":"uncertain","scene_type":"unknown","recommended_action":"manual_review","activity":"低位状态不明","posture_state":"ground_low","fall_transition_visible":false,"intentional_action_evidence":null,"recovery_observed":false,"persistent_ground_state":"not_observed","posture":"人物处于低位姿态，但进入过程不清楚。","summary":"现有关键帧不足以可靠区分主动低位与真实跌倒。","confidence":0.55}',
        ),
    ]
    lines = [
        "你是 Post-Fall V2 的视觉事件复核模型。",
        f"当前任务为{review_mode}。",
        "输入是一组按时间顺序排列的同一事件关键帧。",
        "你只判断关键帧中真实可见的动作和状态；若没有看到人物怎样进入低位，必须诚实输出 unclear，除非后帧显示异常翻倒、冲击后倒地或持续异常卧地状态。",
        "重点区分主动且受控地放低身体，与突然失衡、失控、非自主地倒地。",
        "前级模型只提供候选事件，不代表已经发生真实跌倒。",
         "只填写安全判定所需字段：high_risk_fall、fall_verdict、scene_type、recommended_action、activity、posture_state、fall_transition_visible、intentional_action_evidence、recovery_observed、persistent_ground_state、posture、summary、confidence。",
        "intentional_action_evidence=true 仅表示清楚看见主动控制身体的证据，例如明确坐下、阅读、玩手机、睡觉，或在床/沙发/椅子等正常支撑面上稳定休息。",
        "从坐姿、半躺姿态变化为地面平躺本身不能证明是主动躺下；如果只有主动调整身体、口头休息或地面平躺，而没有阅读、玩手机、睡觉或明确支撑面等更强证据，不能把 intentional_action_evidence 写成 true。",
        "intentional_action_evidence=false 表示人物和姿态清楚可见，但没有观察到上述主动行为证据；只有严重遮挡、严重模糊、人物不可见或图片不足时才可写 null。",
        "必须输出 high_risk_fall，默认 0；只有明确高危真实跌倒才允许为 1。",
        "输出四类结论：confirmed_fall、non_fall、uncertain、insufficient_visual_evidence。",
        "清楚显示正常站立、正常行走、正常坐姿、坐椅子休息、普通活动或经过镜头，且没有真实倒地过程，输出 non_fall。",
        "如果文字分析已经明确是主动坐下、主动躺下、坐下看书/玩手机、躺下看书/玩手机/睡觉，fall_verdict 不能写成 confirmed_fall，high_risk_fall 必须为 0。",
        "如果画面清楚显示正常行走、站立、经过镜头、正常坐姿或普通活动，且没有明确失衡倒地过程，fall_verdict 应为 non_fall，不能写成 confirmed_fall。",
        "坐在椅子上休息、坐在沙发上休息或坐在床边等明确支撑面上，且无失衡倒地过程时，scene_type=seated_rest，high_risk_fall=0，recommended_action=no_alert。",
        "蓝色地垫、瑜伽垫或地面软垫本身不等于正常支撑面，不能仅凭人物在垫子上就自动判定为主动躺下或休息。",
        "如果先看到突然失衡、急速下落、肢体翻起、伸手撑地、撞向地面或非自主倒地，随后又坐起、阅读、玩手机或休息，仍可判 confirmed_fall。",
        "真实跌倒允许两类确认路径：一类是完整看到站立/较高姿态到失衡、下落并倒地的转场；另一类是虽未完整拍到转场，但连续关键帧明确支持异常倒地或贴地状态、持续未恢复、且没有主动行为证据。",
        "如果最早可见帧缺失，但后帧已明显呈现异常翻倒、冲击后倒地或持续异常卧地状态，且没有主动坐下或主动躺下证据，仍可判 confirmed_fall。",
        "若没有看到人物怎样进入低位，且也没有后帧异常翻倒、冲击后倒地或持续异常卧地状态，必须诚实输出 unclear；如果后帧持续异常卧地、未恢复且无主动行为证据，则可判 confirmed_fall。",
        "persistent_ground_state=observed 只描述所给关键帧跨度，不表示持续十秒。",
        "recommended_action=manual_review 只表示可人工查看，绝对不等于跌倒告警。",
        "high_risk_fall=1 时必须同时输出 fall_verdict=confirmed_fall、scene_type=fall、recommended_action=emergency_alert；否则必须保持 high_risk_fall=0。",
        "若最早可见帧已经处于横向翻倒、身体失去支撑、双腿抬起或冲击后的异常姿态，不要仅凭后续坐起或静止就改判为主动躺下；应结合异常动态和后续状态判断。",
        "最终输出前要自检 fall_verdict 与安全判定字段是否一致；不得用 verdict 反推证据。",
         "以下示例只用于学习判定边界，不得复制示例中的人物、物品、动作或场景到当前事件。",
         "不要输出 positive_evidence、negative_evidence、movement_level、attempt_to_stand、visibility、occlusion、scene_risks、possible_help_gesture 或 review_points；展示字段由系统按精简格式补齐。",
    ]
    for title, scenario, answer in examples:
        lines.extend([title + "：", scenario, f"正确输出：{answer}"])
    lines.extend([
        "====== 以下开始分析当前真实事件 ======",
        "现在请忘记示例中的具体人物和物品，只使用从示例中学到的判断原则。",
        "下面提供的是当前真实事件关键帧，请严格根据实际图片判断。",
    ])
    if countercheck:
        lines.extend([
            "反证复核特别要求：如果既没有观察到跌倒转场，也没有持续异常卧地、未恢复且无主动行为证据的后跌倒证据，才输出 unclear。",
            "如果后帧显示人物站立、行走、坐着工作、经过镜头、只有腿部近景，或触发帧主要是运动模糊，应输出 normal_activity、intentional_low_posture 或 unclear。",
            "如果不能清楚看到从较高姿态非自主倒向地面并进入倒地低位状态，而且也没有持续异常卧地、未恢复的证据，应输出 unclear。",
        ])
    return "\n".join(lines)


def _build_compact_post_fall_task(*, countercheck: bool) -> str:
    lines = [
        "按时间顺序分析同一事件的三张关键帧，独立判断是否真实跌倒。",
        "前级二分类只表示候选，不代表真实跌倒。",
        "必须输出 high_risk_fall，默认 0；只有明确高危真实跌倒才允许为 1。",
        "看到较高姿态到非自主失衡、失控下落并倒地，或明确高危跌倒后异常倒地且无自主行为证据，才输出 high_risk_fall=1 和 confirmed_fall。",
        "真实跌倒允许两类确认路径：一类是完整看到跌倒转场；另一类是虽未完整拍到转场，但连续关键帧明确支持异常倒地或贴地状态、持续未恢复、且没有主动行为证据。",
        "只看到持续低位但没有可见进入过程，且没有后帧异常翻倒、冲击后倒地或持续异常卧地状态时输出 high_risk_fall=0 和 unclear，不得推测曾发生跌倒。",
        "正常站立、行走、经过镜头、普通活动、稳定坐姿或坐椅子休息且无倒地过程，输出 non_fall。",
        "主动且受控地坐下、躺下、阅读、玩手机、休息或睡觉且无失控倒地，输出 non_fall。",
        "从坐姿、半躺姿态变化为地面平躺本身不能证明是主动躺下；只有明确主动控制证据才可判 intentional_action_evidence=true。",
        "坐在椅子、沙发或床边等支撑面上休息，scene_type=seated_rest，high_risk_fall=0，recommended_action=no_alert。",
        "蓝色地垫、瑜伽垫或地面软垫本身不等于正常支撑面，不能仅凭人物在垫子上就自动判定为主动躺下或休息。",
        "过程缺失或无法可靠判断，输出 uncertain；人物不可见、遮挡严重或画面不足，输出 insufficient_visual_evidence。",
        "不能仅凭身体倾斜、运动模糊、坐着、躺着、靠近地面或未起身确认跌倒。",
         "只填写安全判定所需字段；persistent_ground_state 只描述所给关键帧跨度。",
         "不要输出 positive_evidence、negative_evidence、movement_level、attempt_to_stand、visibility、occlusion、scene_risks、possible_help_gesture 或 review_points；展示字段由系统按精简格式补齐。",
        "recommended_action=manual_review 不是跌倒告警；若 high_risk_fall=0，recommended_action 不得为 emergency_alert。",
        "high_risk_fall=1 必须同时满足 fall_verdict=confirmed_fall、scene_type=fall、recommended_action=emergency_alert。",
        "fall_verdict 与安全判定字段必须一致；只返回 JSON，不输出解释或 Markdown。",
    ]
    if countercheck:
        lines.append("反证复核：证据不足时不要确认跌倒，优先排除正常活动和主动低姿态。")
    return "\n".join(lines)


def _post_fall_keyframe_timeline(images: Sequence[QwenImageInput]) -> list[str]:
    timeline: list[str] = []
    for index, image in enumerate(images, start=1):
        if image.offset_ms < 0:
            label = f"T{image.offset_ms}ms，事件触发前"
        elif image.offset_ms == 0:
            label = "T0，候选事件触发附近"
        else:
            label = f"T+{image.offset_ms}ms，事件触发后"
        timeline.append(f"图片 {index}：{label}，角色 {image.role}")
    return timeline
