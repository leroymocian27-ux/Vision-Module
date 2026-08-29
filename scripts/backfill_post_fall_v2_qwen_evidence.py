from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from app.events.qwen_keyframe import QwenImageInput, QwenKeyframeAnalyzer
from app.post_fall_v2.evidence_exporter import PostFallEvidenceExporter
from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframeItem, KeyframePackage


DEFAULT_EVENT_IDS = (
    "pfv2-go2_front_camera-82f148ca077d",
    "pfv2-go2_front_camera-b2562512586c",
    "pfv2-go2_front_camera-54b5fc881b22",
    "pfv2-go2_front_camera-576f5f2b8c3e",
    "pfv2-go2_front_camera-87b285ee4dd1",
)


def _load_event(binary_path: Path) -> tuple[FallEvent, KeyframePackage, list[QwenImageInput]]:
    record = json.loads(binary_path.read_text(encoding="utf-8"))
    if record.get("schema_version") == "post_fall_local_evidence.v2":
        return _load_compact_event(binary_path, record)
    event_record = record["event"]
    package_record = record["keyframes"]
    package = KeyframePackage(
        **{
            **package_record,
            "frames": [KeyframeItem(**item) for item in package_record["frames"]],
        }
    )
    event = FallEvent(
        incident_id=event_record["incident_id"],
        camera_id=event_record["camera_id"],
        state=event_record["state"],
        started_at=event_record["started_at"],
        confirmed_at=event_record["confirmed_at"],
        binary_evidence=event_record["binary_evidence"],
        keyframes=package,
        vlm_status="collecting_keyframes",
        vlm_analysis=None,
        created_at=event_record.get("created_at", event_record["confirmed_at"]),
        updated_at=event_record.get("updated_at", event_record["confirmed_at"]),
    )

    image_names = record.get("saved_keyframes", [])
    image_by_name = {path.name: path for path in binary_path.parent.glob("*.jpg")}
    images: list[QwenImageInput] = []
    for frame, image_name in zip(package.frames, image_names, strict=False):
        image_path = image_by_name.get(image_name)
        if image_path is None:
            continue
        images.append(
            QwenImageInput(
                offset_ms=frame.offset_ms,
                role=frame.role,
                image_bytes=image_path.read_bytes(),
            )
        )
    return event, package, images


def _load_compact_event(binary_path: Path, record: dict) -> tuple[FallEvent, KeyframePackage, list[QwenImageInput]]:
    keyframes = record.get("keyframes") if isinstance(record.get("keyframes"), dict) else {}
    slots = keyframes.get("frames") if isinstance(keyframes.get("frames"), list) else []
    confirmed_at = str(record.get("confirmed_at") or "")
    evidence = _compact_binary_evidence(record)
    frames = [
        KeyframeItem(
            role=str(item.get("role") or "keyframe"),
            offset_ms=int(item.get("offset_ms") or 0),
            frame_id=None,
            frame_seq=None,
            timestamp=None,
        )
        for item in slots
        if isinstance(item, dict)
    ]
    package = KeyframePackage(
        incident_id=str(record["incident_id"]),
        camera_id=str(record["camera_id"]),
        confirmed_at=confirmed_at,
        source_width=0,
        source_height=0,
        frames=frames,
        fall_probability_summary=evidence,
        status=str(keyframes.get("status") or "degraded"),
        requested_offsets_ms=[frame.offset_ms for frame in frames],
        resolved_offsets_ms=[frame.offset_ms for frame in frames],
        missing_offsets_ms=[int(value) for value in keyframes.get("missing_offsets_ms", [])],
    )
    event = FallEvent(
        incident_id=str(record["incident_id"]),
        camera_id=str(record["camera_id"]),
        state="fall_confirmed",
        started_at=confirmed_at,
        confirmed_at=confirmed_at,
        binary_evidence=evidence,
        keyframes=package,
        vlm_status="collecting_keyframes",
    )
    images = []
    for frame, item in zip(frames, slots, strict=False):
        image_name = item.get("file") if isinstance(item, dict) else None
        image_path = binary_path.parent / str(image_name or "")
        if image_path.is_file():
            images.append(QwenImageInput(offset_ms=frame.offset_ms, role=frame.role, image_bytes=image_path.read_bytes()))
    return event, package, images


def _compact_binary_evidence(record: dict) -> dict:
    probabilities = record.get("fall_probability") if isinstance(record.get("fall_probability"), dict) else {}
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    positive_text = str(evidence.get("positive_frames") or "0/0")
    positive_count, _, window_size = positive_text.partition("/")
    return {
        "window_size": int(window_size) if window_size.isdigit() else 0,
        "positive_count": int(positive_count) if positive_count.isdigit() else 0,
        "consecutive_positive_count": evidence.get("consecutive_positive_frames"),
        "mean_fall_probability": probabilities.get("mean"),
        "max_fall_probability": probabilities.get("max"),
        "candidate_duration_ms": evidence.get("candidate_duration_ms"),
        "threshold": probabilities.get("threshold"),
    }


def _analyze(
    analyzer: QwenKeyframeAnalyzer,
    event: FallEvent,
    package: KeyframePackage,
    images: list[QwenImageInput],
) -> FallEvent:
    result = analyzer.analyze_post_fall(
        images=images,
        keyframe_status=package.status,
        missing_offsets_ms=package.missing_offsets_ms,
    )
    detail = FallDetailResult(
        incident_id=event.incident_id,
        analysis_status="completed",
        fall_verdict=result.fall_verdict,
        posture=result.posture,
        movement_level=result.movement_level,
        attempt_to_stand=result.attempt_to_stand,
        persistent_ground_state=result.persistent_ground_state,
        visibility=result.visibility,
        occlusion=result.occlusion,
        scene_risks=result.scene_risks,
        possible_help_gesture=result.possible_help_gesture,
        summary=result.summary,
        review_points=result.review_points,
        confidence=result.confidence,
        latency_ms=result.latency_ms,
        model_name=analyzer.model_name,
    )
    return replace(event, vlm_status="completed", vlm_analysis=detail, keyframes=package)


def _write_review(binary_path: Path, event: FallEvent, exported_to_da: bool) -> None:
    detail = event.vlm_analysis
    if detail is None:
        return
    payload = {
        "schema_version": "post_fall_local_evidence.v2",
        "stage": "qwen_reviewed",
        "decision": _verdict_label(detail.fall_verdict),
        "event_description": _short_text(detail.summary or detail.posture, 80),
        "confidence": detail.confidence,
        "incident_id": event.incident_id,
        "fall_verdict": detail.fall_verdict,
        "archive_eligible": exported_to_da,
    }
    (binary_path.parent / "qwen_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _verdict_label(verdict: str) -> str:
    return {
        "confirmed_fall": "确认跌倒",
        "intentional_low_posture": "主动低姿态",
        "insufficient_visual_evidence": "画面证据不足",
    }.get(verdict, "无法确认")


def _short_text(value: str, limit: int) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip("，。；、 ") + "。"


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-run local Qwen confirmation for saved PFV2 evidence.")
    parser.add_argument("event_ids", nargs="*", default=list(DEFAULT_EVENT_IDS))
    parser.add_argument("--xiao-dir", default=r"C:\Users\YANG\Desktop\ce\xiao")
    parser.add_argument("--da-dir", default=r"C:\Users\YANG\Desktop\ce\da")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    analyzer = QwenKeyframeAnalyzer(
        endpoint_url=args.endpoint,
        model_name=args.model,
        timeout_seconds=args.timeout,
    )
    exporter = PostFallEvidenceExporter(
        enabled=True,
        binary_output_dir=args.xiao_dir,
        qwen_output_dir=args.da_dir,
    )
    for event_id in dict.fromkeys(args.event_ids):
        binary_path = Path(args.xiao_dir) / event_id / "binary_result.json"
        try:
            event, package, images = _load_event(binary_path)
            if not images:
                raise RuntimeError("没有可用关键帧")
            updated = _analyze(analyzer, event, package, images)
            exported = exporter.export_qwen_confirmation(updated, images=images)
            _write_review(binary_path, updated, exported)
            detail = updated.vlm_analysis
            print(json.dumps({
                "incident_id": event_id,
                "exported_to_da": exported,
                "fall_verdict": detail.fall_verdict if detail else None,
                "image_count": len(images),
                "posture": detail.posture if detail else None,
                "summary": detail.summary if detail else None,
                "confidence": detail.confidence if detail else None,
            }, ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({"incident_id": event_id, "error": str(exc)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
