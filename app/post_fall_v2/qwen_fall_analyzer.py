from __future__ import annotations

from collections.abc import Callable, Sequence
from urllib.parse import urlsplit

from app.events.qwen_keyframe import (
    QwenImageInput,
    QwenKeyframeAnalyzer,
    QwenKeyframeError,
    QwenKeyframeInvalidOutput,
    QwenKeyframeNonChineseOutput,
    QwenKeyframeTimeout,
)
from app.events.schemas import EventSemantics, QwenKeyframeAdvisory
from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframePackage


QwenImageProvider = Callable[[str], tuple[list[QwenImageInput], list[str]]]


class PFV2QwenFallAnalyzer:
    """PFV2 adapter that enriches an already confirmed fall with local Qwen vision."""

    def __init__(
        self,
        *,
        analyzer: QwenKeyframeAnalyzer,
        image_provider: QwenImageProvider,
    ) -> None:
        self.analyzer = analyzer
        self.image_provider = image_provider

    @classmethod
    def from_config(
        cls,
        *,
        endpoint_url: str,
        model_name: str,
        timeout_seconds: float,
        image_provider: QwenImageProvider,
    ) -> "PFV2QwenFallAnalyzer":
        endpoint = urlsplit(endpoint_url)
        if endpoint.scheme != "http" or endpoint.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("PFV2 Qwen endpoint must use localhost")
        return cls(
            analyzer=QwenKeyframeAnalyzer(
                endpoint_url=endpoint_url,
                model_name=model_name,
                timeout_seconds=timeout_seconds,
            ),
            image_provider=image_provider,
        )

    def analyze_fall_event(self, event: FallEvent, keyframes: KeyframePackage) -> FallDetailResult:
        images, missing_reasons = self.image_provider(event.incident_id)
        if not images:
            return FallDetailResult(
                incident_id=event.incident_id,
                analysis_status="failed",
                visibility="insufficient_visual_evidence",
                summary="本地千问未获得可分析的事件关键帧，跌倒事件仍以二分类确认结果为准。",
                review_points=["检查关键帧采集链路是否可用。"],
                model_name=self.analyzer.model_name,
                error_message="no_qwen_keyframe_images",
            )
        try:
            detail = self.analyzer.analyze_post_fall(
                images=_bounded_images(images),
                keyframe_status=keyframes.status,
                missing_offsets_ms=keyframes.missing_offsets_ms,
            )
        except QwenKeyframeTimeout as exc:
            return _failure(event, "timeout", self.analyzer.model_name, "qwen_timeout", str(exc))
        except QwenKeyframeNonChineseOutput as exc:
            return _failure(event, "parse_failed", self.analyzer.model_name, "qwen_non_chinese_output", str(exc))
        except QwenKeyframeInvalidOutput as exc:
            return _failure(event, "parse_failed", self.analyzer.model_name, "qwen_invalid_output", str(exc))
        except QwenKeyframeError as exc:
            return _failure(event, "failed", self.analyzer.model_name, "qwen_unavailable", str(exc))
        except Exception as exc:
            return _failure(event, "failed", self.analyzer.model_name, "qwen_adapter_failed", str(exc))
        return FallDetailResult(
            incident_id=event.incident_id,
            analysis_status="completed",
            posture=detail.posture,
            movement_level=detail.movement_level,
            attempt_to_stand=detail.attempt_to_stand,
            persistent_ground_state=detail.persistent_ground_state,
            visibility=detail.visibility,
            occlusion=detail.occlusion,
            scene_risks=detail.scene_risks,
            possible_help_gesture=detail.possible_help_gesture,
            summary=detail.summary,
            review_points=detail.review_points,
            confidence=detail.confidence,
            latency_ms=detail.latency_ms,
            model_name=self.analyzer.model_name,
        )


def _bounded_images(images: Sequence[QwenImageInput]) -> list[QwenImageInput]:
    return list(images)


def _build_semantics(event: FallEvent, keyframes: KeyframePackage, missing_reasons: Sequence[str]) -> EventSemantics:
    return EventSemantics(
        incident_id=event.incident_id,
        actor={},
        scene={},
        motion={},
        posture={},
        evidence={
            "pipeline": "post_fall_v2",
            "binary_evidence": event.binary_evidence,
            "keyframe_status": keyframes.status,
            "requested_offsets_ms": keyframes.requested_offsets_ms,
            "resolved_offsets_ms": keyframes.resolved_offsets_ms,
            "missing_offsets_ms": keyframes.missing_offsets_ms,
            "missing_reasons": list(missing_reasons),
        },
        risk={
            "event_type": "fallen_confirmed",
            "risk_level": "high",
        },
        uncertainty=list(dict.fromkeys(missing_reasons)),
        degradation_used=[f"missing_{offset}ms" for offset in keyframes.missing_offsets_ms],
    )


def _map_advisory(incident_id: str, advisory: QwenKeyframeAdvisory) -> FallDetailResult:
    confidence = _confidence(advisory.advisory_confidence)
    review_points = []
    if advisory.confidence_explanation:
        review_points.append(advisory.confidence_explanation)
    review_points.extend(advisory.care_advice[:4])
    return FallDetailResult(
        incident_id=incident_id,
        analysis_status="completed" if advisory.analysis_status == "completed" else "failed",
        posture=advisory.posture_description or "unknown",
        movement_level=advisory.movement_description or "unknown",
        attempt_to_stand="unknown",
        persistent_ground_state=advisory.scene_summary or "unknown",
        visibility="unknown" if advisory.image_count else "insufficient_visual_evidence",
        occlusion="unknown",
        scene_risks=[],
        possible_help_gesture="unknown",
        summary=advisory.scene_summary or "本地千问已完成事件关键帧辅助分析。",
        review_points=review_points,
        confidence=confidence,
        model_name=advisory.model_name,
        error_message=advisory.error_code,
    )


def _failure(
    event: FallEvent,
    status: str,
    model_name: str,
    reason: str,
    message: str,
) -> FallDetailResult:
    return FallDetailResult(
        incident_id=event.incident_id,
        analysis_status=status,  # type: ignore[arg-type]
        posture="unknown",
        movement_level="unknown",
        attempt_to_stand="unknown",
        persistent_ground_state="unknown",
        visibility="insufficient_visual_evidence",
        occlusion="unknown",
        scene_risks=[],
        possible_help_gesture="unknown",
        summary=f"本地千问辅助分析未完成：{reason}。跌倒事件仍以二分类确认结果为准。",
        review_points=["复核实时画面。", "检查本地 Ollama/Qwen 服务和关键帧输入。"],
        confidence=None,
        model_name=model_name,
        error_message=message or reason,
    )


def _confidence(value: str) -> float | None:
    return {
        "low": 0.35,
        "medium": 0.65,
        "high": 0.85,
    }.get((value or "").lower())
