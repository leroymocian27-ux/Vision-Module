from __future__ import annotations

import json

import pytest

from app.events.qwen_keyframe import QwenImageInput, QwenKeyframeAnalyzer
from app.post_fall_v2.qwen_fall_analyzer import PFV2QwenFallAnalyzer
from app.post_fall_v2.schemas import FallEvent, KeyframePackage


def test_qwen_fall_analyzer_maps_valid_multimage_advisory_to_fall_detail() -> None:
    received: list[dict] = []

    def transport(payload: dict, timeout: float) -> dict:
        received.append(payload)
        return {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "posture": "疑似侧卧在地面附近。",
            "movement_level": "slight",
            "attempt_to_stand": "not_observed",
            "persistent_ground_state": "observed",
            "possible_help_gesture": "not_observed",
            "visibility": "limited",
            "occlusion": "partial",
            "scene_risks": ["人员位于通行区域。"],
            "summary": "人员仍处于低位，画面中未见明显自主起身。",
            "review_points": ["复核人员是否持续倒地。"],
            "confidence": 0.65,
        }, ensure_ascii=False)}}

    analyzer = _analyzer(transport, images=[_image(0), _image(1000), _image(3000)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.incident_id == "incident-1"
    assert detail.analysis_status == "completed"
    assert detail.posture == "疑似侧卧在地面附近。"
    assert detail.movement_level == "slight"
    assert detail.attempt_to_stand == "not_observed"
    assert detail.persistent_ground_state == "observed"
    assert detail.summary == "人员仍处于低位，画面中未见明显自主起身。"
    assert detail.confidence == 0.65
    assert len(received) == 1
    assert len(received[0]["messages"][1]["images"]) == 3
    request_text = json.dumps(received[0], ensure_ascii=False)
    assert "incident_id" not in request_text
    assert "camera_id" not in request_text
    assert "rtsp://" not in request_text.lower()


def test_qwen_fall_analyzer_parse_failure_keeps_event_context() -> None:
    analyzer = _analyzer(lambda *_: {"message": {"content": "not-json"}}, images=[_image(0)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.incident_id == "incident-1"
    assert detail.analysis_status == "parse_failed"
    assert "千问" in detail.summary
    assert detail.error_message


def test_qwen_fall_analyzer_recovers_missing_detail_fields() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({"schema_version": "pfv2_post_fall_detail.v1"})}},
        images=[_image(0)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.incident_id == "incident-1"
    assert detail.analysis_status == "completed"
    assert detail.posture == "unknown"
    assert detail.review_points == ["建议人工复核事件关键帧。"]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            """模型输出如下：
```json
{"posture":"侧卧","activity_level":"轻微活动","attempting_to_stand":"未见尝试起身","persistent_ground":"仍在地面","visibility_level":"清晰","occlusion_level":"无遮挡","scene_risk":"通行区域有障碍物","review_point":"复核是否尝试起身","confidence_score":"65%"}
```
以上为分析结果。""",
            {
                "movement_level": "slight",
                "attempt_to_stand": "not_observed",
                "persistent_ground_state": "observed",
                "visibility": "good",
                "occlusion": "none",
                "confidence": 0.65,
            },
        ),
        (
            json.dumps({
                "posture_description": "Kneeling posture.",
                "movement": "none",
                "attempting_to_stand": False,
                "ground_state": True,
                "visibility": "poor",
                "occlusion": "partial",
                "risks": ["Floor obstacle."],
                "review_point": "Check the live view.",
            }),
            {
                "movement_level": "none_observed",
                "attempt_to_stand": "not_observed",
                "persistent_ground_state": "observed",
                "visibility": "limited",
                "occlusion": "partial",
                "confidence": None,
            },
        ),
    ],
)
def test_qwen_fall_analyzer_recovers_format_language_and_schema_variations(content, expected) -> None:
    analyzer = _analyzer(lambda *_: {"message": {"content": content}}, images=[_image(0)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    for field, value in expected.items():
        assert getattr(detail, field) == value


def test_qwen_fall_analyzer_removes_medical_diagnosis_from_recovered_text() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "posture": "侧卧在地面。",
            "movement_level": "none_observed",
            "attempt_to_stand": "not_observed",
            "persistent_ground_state": "observed",
            "possible_help_gesture": "unknown",
            "visibility": "good",
            "occlusion": "none",
            "scene_risks": ["疑似骨折。"],
            "summary": "疑似昏迷。",
            "review_points": ["确认意识与呼吸状况。"],
        }, ensure_ascii=False)}},
        images=[_image(0)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.summary == "仅可依据画面描述，建议人工复核。"
    assert detail.scene_risks == ["仅可依据画面描述，建议人工复核。"]
    assert detail.review_points == ["仅可依据画面描述，建议人工复核。"]


def test_qwen_fall_analyzer_extracts_json_from_outer_markdown_response() -> None:
    analyzer = _analyzer(
        lambda *_: """返回如下：
```json
{"posture":"侧卧","movement_level":"none_observed","attempt_to_stand":"not_observed","persistent_ground_state":"observed","possible_help_gesture":"unknown","visibility":"good","occlusion":"none","scene_risks":[],"summary":"人员处于低位。","review_points":["复核现场。"],"confidence":0.7}
```""",
        images=[_image(0)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.confidence == 0.7


def test_qwen_fall_analyzer_records_bounded_parse_diagnostics() -> None:
    keyframe_analyzer = QwenKeyframeAnalyzer(
        endpoint_url="http://127.0.0.1:11434/api/chat",
        model_name="qwen-vision-cn:latest",
        timeout_seconds=1,
        transport=lambda *_: {"message": {"content": "{\"posture\":\"侧卧\"}"}},
    )
    analyzer = PFV2QwenFallAnalyzer(
        analyzer=keyframe_analyzer,
        image_provider=lambda _: ([_image(0)], []),
    )

    detail = analyzer.analyze_fall_event(_event(), _package())
    diagnostic = keyframe_analyzer.last_post_fall_diagnostic

    assert detail.analysis_status == "completed"
    assert diagnostic is not None
    assert diagnostic["status"] == "completed"
    assert diagnostic["parse_status"] == "direct_json_normalized"
    assert diagnostic["raw_response"] == "{\"posture\":\"侧卧\"}"
    assert diagnostic["normalized_response"]["posture"] == "侧卧"


def test_qwen_fall_analyzer_maps_timeout_and_transport_failure() -> None:
    timeout = _analyzer(lambda *_: (_ for _ in ()).throw(TimeoutError("slow")), images=[_image(0)])
    unavailable = _analyzer(lambda *_: (_ for _ in ()).throw(RuntimeError("offline")), images=[_image(0)])

    timeout_detail = timeout.analyze_fall_event(_event(), _package())
    unavailable_detail = unavailable.analyze_fall_event(_event(), _package())

    assert timeout_detail.analysis_status == "timeout"
    assert unavailable_detail.analysis_status == "failed"
    assert timeout_detail.incident_id == unavailable_detail.incident_id == "incident-1"


def test_qwen_fall_analyzer_no_images_fails_without_qwen_call() -> None:
    calls = 0

    def transport(*_) -> dict:
        nonlocal calls
        calls += 1
        return {}

    analyzer = _analyzer(transport, images=[])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert calls == 0
    assert detail.analysis_status == "failed"
    assert detail.visibility == "insufficient_visual_evidence"


def test_qwen_fall_analyzer_rejects_non_local_endpoint() -> None:
    with pytest.raises(ValueError, match="localhost"):
        PFV2QwenFallAnalyzer.from_config(
            endpoint_url="http://10.0.0.4:11434/api/chat",
            model_name="qwen-vision-cn:latest",
            timeout_seconds=1,
            image_provider=lambda _: ([], []),
        )


def _analyzer(transport, *, images: list[QwenImageInput]) -> PFV2QwenFallAnalyzer:
    return PFV2QwenFallAnalyzer(
        analyzer=QwenKeyframeAnalyzer(
            endpoint_url="http://127.0.0.1:11434/api/chat",
            model_name="qwen-vision-cn:latest",
            timeout_seconds=1,
            transport=transport,
        ),
        image_provider=lambda _: (images, []),
    )


def _image(offset_ms: int) -> QwenImageInput:
    return QwenImageInput(offset_ms=offset_ms, role="trigger", image_bytes=_JPEG_BYTES)


def _event() -> FallEvent:
    return FallEvent(
        incident_id="incident-1",
        camera_id="camera_01",
        state="fall_confirmed",
        started_at="2026-08-13T00:00:00.000+00:00",
        confirmed_at="2026-08-13T00:00:00.000+00:00",
        binary_evidence={"max_fall_probability": 0.9},
    )


def _package() -> KeyframePackage:
    return KeyframePackage(
        incident_id="incident-1",
        camera_id="camera_01",
        confirmed_at="2026-08-13T00:00:00.000+00:00",
        source_width=16,
        source_height=16,
        frames=[],
        fall_probability_summary={},
        status="ready",
        requested_offsets_ms=[-3000, -1000, 0, 1000, 3000, 5000],
        resolved_offsets_ms=[0, 1000, 3000],
        missing_offsets_ms=[],
    )


_JPEG_BYTES = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + bytes([8] * 64) + b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08"
    b"\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xbf\xff\xd9"
)
