from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.schemas import FallEvent, KeyframePackage


_UNKNOWN_VISUAL_VALUES = {"", "unknown", "insufficient_visual_evidence", "未知", "画面不足", "无法判断"}
_NO_PERSON_EVIDENCE = re.compile(
    r"无人|没有人|未见人|未见人员|未发现人|未发现人员|无明确人体|未见人体|空场景|空画面|仅有机器狗|只有机器狗|没有明确人体|无法确认是否有人|无法确认有人|无法确认人员|无法确认人体|不能确认有人|不能确认人员|未能确认有人"
)
_PERSON_EVIDENCE = re.compile(r"人体|人员|人影|身体|躯干|四肢|头部|手臂|腿部|有人")
_FALL_POSTURE_EVIDENCE = re.compile(
    r"跌倒|摔倒|倒地|倒下|倒伏|趴伏|趴倒|俯卧|仰卧|侧卧|躺倒|横躺|卧地|贴地|头部贴地|身体着地"
)


class PostFallEvidenceExporter:
    """Writes local-only, per-incident evidence without changing alert behavior."""

    def __init__(
        self,
        *,
        enabled: bool,
        binary_output_dir: str,
        qwen_output_dir: str,
    ) -> None:
        self.enabled = bool(enabled and binary_output_dir and qwen_output_dir)
        self.binary_output_dir = Path(binary_output_dir).expanduser()
        self.qwen_output_dir = Path(qwen_output_dir).expanduser()
        self._images: dict[str, list[QwenImageInput]] = {}
        self._exported_binary: set[str] = set()
        self._lock = threading.Lock()

    def export_binary(self, event: FallEvent, package: KeyframePackage, images: list[QwenImageInput]) -> None:
        if not self.enabled:
            return
        with self._lock:
            if event.incident_id in self._exported_binary:
                return
            self._exported_binary.add(event.incident_id)
            self._images[event.incident_id] = list(images)
        output_dir = self._incident_dir(self.binary_output_dir, event.incident_id)
        frame_files = self._write_images(output_dir, images)
        self._write_json(
            output_dir / "binary_result.json",
            {
                "schema_version": "post_fall_local_evidence.v2",
                "stage": "binary_confirmed",
                "decision": "FALL",
                "decision_description": "二分类确认跌倒候选，等待千问复核。",
                "incident_id": event.incident_id,
                "camera_id": event.camera_id,
                "confirmed_at": event.confirmed_at,
                "fall_probability": _probability_summary(event.binary_evidence),
                "evidence": _binary_evidence_summary(event.binary_evidence),
                "keyframes": _keyframe_summary(package, images, frame_files),
            },
        )

    def export_qwen_confirmation(
        self,
        event: FallEvent,
        images: list[QwenImageInput] | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        detail = event.vlm_analysis
        confirmed = bool(
            detail
            and detail.analysis_status == "completed"
            and self._has_visual_fall_evidence(detail.posture, detail.summary, detail.fall_verdict)
        )
        if images is None:
            with self._lock:
                images = self._images.pop(event.incident_id, [])
        if not confirmed:
            return False
        output_dir = self._incident_dir(self.qwen_output_dir, event.incident_id)
        frame_files = self._write_images(output_dir, images)
        self._write_json(
            output_dir / "qwen_confirmation.json",
            {
                "schema_version": "post_fall_local_evidence.v2",
                "stage": "qwen_confirmed",
                "decision": "确认跌倒",
                "event_description": _event_description(detail.posture, detail.summary),
                "confidence": detail.confidence,
                "incident_id": event.incident_id,
                "camera_id": event.camera_id,
                "confirmed_at": event.confirmed_at,
                "fall_verdict": detail.fall_verdict,
                "keyframes": frame_files,
            },
        )
        return True

    def export_qwen_review(
        self,
        event: FallEvent,
        images: list[QwenImageInput] | None = None,
    ) -> list[QwenImageInput]:
        """Write every Qwen review outcome so false accepts/denies are inspectable."""
        if not self.enabled:
            return []
        detail = event.vlm_analysis
        if detail is None:
            return []
        if images is None:
            with self._lock:
                images = self._images.pop(event.incident_id, [])
        output_dir = self._incident_dir(self.qwen_output_dir, event.incident_id)
        frame_files = self._write_images(output_dir, images)
        self._write_json(
            output_dir / "qwen_review.json",
            {
                "schema_version": "post_fall_local_qwen_review.v1",
                "stage": "qwen_review",
                "decision": _qwen_decision_label(detail.fall_verdict),
                "incident_id": event.incident_id,
                "camera_id": event.camera_id,
                "confirmed_at": event.confirmed_at,
                "analysis_status": detail.analysis_status,
                "fall_verdict": detail.fall_verdict,
                "high_risk_fall": detail.high_risk_fall,
                "semantic_event": detail.semantic_event,
                "raw_compact_json": detail.raw_compact_json,
                "confidence": detail.confidence,
                "latency_ms": detail.latency_ms,
                "timing": detail.timing,
                "qwen_start_frames_received": detail.qwen_start_frames_received,
                "qwen_end_frames_received": detail.qwen_end_frames_received,
                "frames_received_during_qwen": detail.frames_received_during_qwen,
                "prompt_version": detail.prompt_version,
                "schema_version_used": detail.schema_version,
                "fusion_version": detail.fusion_version,
                "posture": detail.posture,
                "summary": detail.summary,
                "last_frame_description": detail.last_frame_description,
                "visible_distress": detail.visible_distress,
                "vlm_is_true_fall": detail.vlm_is_true_fall,
                "error_message": detail.error_message,
                "keyframes": _qwen_keyframe_summary(images, frame_files),
            },
        )
        return list(images)

    @staticmethod
    def _has_visual_fall_evidence(posture: str, summary: str, fall_verdict: str = "unclear") -> bool:
        """Require an explicit VLM fall verdict while preserving empty-scene protection."""
        if fall_verdict != "confirmed_fall":
            return False
        posture_text = (posture or "").strip()
        summary_text = (summary or "").strip()
        if posture_text.lower() in _UNKNOWN_VISUAL_VALUES:
            return False
        evidence_text = f"{posture_text} {summary_text}"
        if _NO_PERSON_EVIDENCE.search(evidence_text):
            return False
        has_fall_posture = bool(_FALL_POSTURE_EVIDENCE.search(evidence_text))
        # `posture` is the model's subject-pose field; an explicit fall pose there
        # is sufficient even when the model leaves the free-text summary unknown.
        has_subject_or_pose = bool(_PERSON_EVIDENCE.search(evidence_text) or _FALL_POSTURE_EVIDENCE.search(posture_text))
        return bool(has_subject_or_pose and has_fall_posture)

    @staticmethod
    def _incident_dir(root: Path, incident_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", incident_id).strip("._") or "unknown_incident"
        output_dir = root / safe_id
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @staticmethod
    def _write_images(output_dir: Path, images: list[QwenImageInput]) -> list[str]:
        saved: list[str] = []
        for index, image in enumerate(images, start=1):
            role = re.sub(r"[^A-Za-z0-9._-]+", "_", image.role).strip("._") or "keyframe"
            name = f"{index:02d}_{image.offset_ms:+05d}ms_{role}.jpg"
            path = output_dir / name
            path.write_bytes(image.image_bytes)
            saved.append(name)
        return saved

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def _probability_summary(evidence: dict) -> dict:
    return {
        "max": evidence.get("max_fall_probability"),
        "mean": evidence.get("mean_fall_probability"),
        "threshold": evidence.get("threshold"),
    }


def _binary_evidence_summary(evidence: dict) -> dict:
    positive_count = evidence.get("positive_count")
    window_size = evidence.get("window_size")
    return {
        "positive_frames": f"{positive_count}/{window_size}",
        "consecutive_positive_frames": evidence.get("consecutive_positive_count"),
        "candidate_duration_ms": evidence.get("candidate_duration_ms"),
    }


def _keyframe_summary(
    package: KeyframePackage,
    images: list[QwenImageInput],
    frame_files: list[str],
) -> dict:
    slots = []
    for image, file_name in zip(images, frame_files):
        slots.append({
            "role": image.role,
            "offset_ms": image.offset_ms,
            "file": file_name,
        })
    return {
        "status": package.status,
        "missing_offsets_ms": package.missing_offsets_ms,
        "frames": slots,
    }


def _short_text(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip("，。；、 ") + "。"


def _event_description(posture: str, summary: str) -> str:
    if (summary or "").strip().lower() in _UNKNOWN_VISUAL_VALUES:
        return _short_text(posture, 80)
    return _short_text(summary or posture, 80)


def _qwen_decision_label(fall_verdict: str) -> str:
    if fall_verdict == "confirmed_fall":
        return "确认跌倒"
    if fall_verdict in {"non_fall", "normal_activity", "intentional_low_posture"}:
        return "非真实跌倒"
    return "无法确认"


def _qwen_keyframe_summary(images: list[QwenImageInput], frame_files: list[str]) -> list[dict]:
    frames = []
    for image, file_name in zip(images, frame_files):
        frames.append({
            "role": image.role,
            "offset_ms": image.offset_ms,
            "file": file_name,
        })
    return frames
