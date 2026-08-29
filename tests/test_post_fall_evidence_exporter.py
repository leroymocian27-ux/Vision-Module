import json
from dataclasses import replace

from app.events.qwen_keyframe import QwenImageInput
from app.post_fall_v2.evidence_exporter import PostFallEvidenceExporter
from app.post_fall_v2.schemas import FallDetailResult, FallEvent, KeyframeItem, KeyframePackage


def test_qwen_confirmation_requires_explicit_visual_fall_evidence() -> None:
    assert PostFallEvidenceExporter._has_visual_fall_evidence("人员俯卧于地面", "画面中明确可见有人倒地", "confirmed_fall")
    assert not PostFallEvidenceExporter._has_visual_fall_evidence("俯卧于蓝色垫子", "稳定躺下看书", "intentional_low_posture")
    assert not PostFallEvidenceExporter._has_visual_fall_evidence("unknown", "画面不足", "insufficient_visual_evidence")
    assert not PostFallEvidenceExporter._has_visual_fall_evidence("人员俯卧于地面", "空场景，未见人员", "confirmed_fall")
    assert not PostFallEvidenceExporter._has_visual_fall_evidence("人员站立", "画面中有人站立", "confirmed_fall")
    assert not PostFallEvidenceExporter._has_visual_fall_evidence("倒地姿态", "无法确认是否有人倒地", "unclear")


def test_evidence_exporter_writes_compact_binary_and_qwen_files(tmp_path) -> None:
    exporter = PostFallEvidenceExporter(
        enabled=True,
        binary_output_dir=str(tmp_path / "xiao"),
        qwen_output_dir=str(tmp_path / "da"),
    )
    event = FallEvent(
        incident_id="incident-1",
        camera_id="camera_01",
        state="fall_confirmed",
        started_at="2026-08-25T00:00:00.000+00:00",
        confirmed_at="2026-08-25T00:00:01.000+00:00",
        binary_evidence={
            "window_size": 8,
            "positive_count": 4,
            "consecutive_positive_count": 3,
            "mean_fall_probability": 0.66,
            "max_fall_probability": 0.93,
            "candidate_duration_ms": 1000,
            "threshold": 0.4,
        },
    )
    package = KeyframePackage(
        incident_id=event.incident_id,
        camera_id=event.camera_id,
        confirmed_at=event.confirmed_at,
        source_width=960,
        source_height=540,
        frames=[KeyframeItem("trigger", 0, "frame-1", 1, event.confirmed_at)],
        fall_probability_summary=event.binary_evidence,
        status="ready",
    )
    images = [QwenImageInput(offset_ms=0, role="trigger", image_bytes=b"jpeg-bytes")]

    exporter.export_binary(event, package, images)
    binary = json.loads((tmp_path / "xiao" / event.incident_id / "binary_result.json").read_text(encoding="utf-8"))

    assert binary["schema_version"] == "post_fall_local_evidence.v2"
    assert binary["decision"] == "FALL"
    assert binary["fall_probability"] == {"max": 0.93, "mean": 0.66, "threshold": 0.4}
    assert binary["evidence"]["positive_frames"] == "4/8"
    assert binary["keyframes"]["frames"][0]["file"] == "01_+0000ms_trigger.jpg"
    assert "event" not in binary
    assert "saved_keyframes" not in binary

    detail = FallDetailResult(
        incident_id=event.incident_id,
        analysis_status="completed",
        fall_verdict="confirmed_fall",
        posture="人员失衡后倒地。",
        summary="人员由站立失衡后倒地。" * 20,
        confidence=0.91,
    )
    assert exporter.export_qwen_confirmation(replace(event, vlm_analysis=detail), images=images)
    qwen = json.loads((tmp_path / "da" / event.incident_id / "qwen_confirmation.json").read_text(encoding="utf-8"))

    assert qwen["schema_version"] == "post_fall_local_evidence.v2"
    assert qwen["decision"] == "确认跌倒"
    assert qwen["fall_verdict"] == "confirmed_fall"
    assert len(qwen["event_description"]) <= 81
    assert "event" not in qwen
    assert "qwen_analysis" not in qwen
