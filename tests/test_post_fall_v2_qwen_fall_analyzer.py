from __future__ import annotations

import json

import pytest

from app.events.qwen_keyframe import QwenImageInput, QwenKeyframeAnalyzer, QwenKeyframeContextExceeded
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
    assert received[0]["format"]["required"] == [
        "high_risk_fall", "fall_verdict", "scene_type", "recommended_action",
        "activity", "posture_state",
        "fall_transition_visible", "intentional_action_evidence", "recovery_observed",
        "persistent_ground_state", "posture", "summary", "confidence",
    ]
    assert set(received[0]["format"]["properties"]) == {
        "high_risk_fall", "fall_verdict", "scene_type", "recommended_action",
        "activity", "posture_state",
        "fall_transition_visible", "intentional_action_evidence", "recovery_observed",
        "persistent_ground_state", "posture", "summary", "confidence",
    }
    assert received[0]["format"]["properties"]["high_risk_fall"]["enum"] == [0, 1]
    assert received[0]["format"]["properties"]["posture"]["maxLength"] == 80
    assert received[0]["format"]["properties"]["summary"]["maxLength"] == 160
    assert received[0]["options"]["num_ctx"] == 8192
    assert received[0]["options"]["num_predict"] == 192
    assert received[0]["options"]["temperature"] == 0.1
    request_text = json.dumps(received[0], ensure_ascii=False)
    assert "最终是否告警由确定性事件状态机决定" in request_text
    assert "示例 1 主动坐下看书或玩手机" in request_text
    assert "示例 3 真实跌倒" in request_text
    assert "示例 4 触发帧已在翻倒过程" in request_text
    assert "若没有看到人物怎样进入低位，必须诚实输出 unclear" in request_text
    assert "confirmed_fall 只允许两条证据路径" in request_text
    assert "后帧持续异常卧地、未恢复且无主动行为证据" in request_text
    assert "high_risk_fall" in request_text
    assert "坐在椅子上休息" in request_text
    assert "以下开始分析当前真实事件" in request_text
    assert "只有真实看见较高姿态到明显非自主失衡" not in request_text
    request_context = json.loads(received[0]["messages"][1]["content"])
    assert request_context["keyframe_timeline"] == [
        "图片 1：T0，候选事件触发附近，角色 trigger",
        "图片 2：T+1000ms，事件触发后，角色 trigger",
        "图片 3：T+3000ms，事件触发后，角色 trigger",
    ]
    assert "incident_id" not in request_text
    assert "camera_id" not in request_text
    assert "rtsp://" not in request_text.lower()


def test_qwen_fall_analyzer_retries_context_exceeded_with_compact_prompt_and_same_images() -> None:
    received: list[dict] = []

    def transport(payload: dict, timeout: float) -> dict:
        received.append(payload)
        if len(received) == 1:
            raise QwenKeyframeContextExceeded("request exceeds the available context size")
        return {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "fall_verdict": "unclear",
            "posture": "人员处于低位姿态。",
            "summary": "现有关键帧不足以可靠确认真实跌倒。",
            "confidence": 0.5,
        }, ensure_ascii=False)}}

    analyzer = _analyzer(transport, images=[_image(-1000), _image(0), _image(3000)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"
    assert len(received) == 2
    assert len(received[0]["messages"][1]["images"]) == 3
    assert len(received[1]["messages"][1]["images"]) == 3
    first_context = json.loads(received[0]["messages"][1]["content"])
    retry_context = json.loads(received[1]["messages"][1]["content"])
    assert first_context["profile"] == "full"
    assert retry_context["profile"] == "compact_retry"
    assert "示例 1 主动坐下看书或玩手机" in first_context["task"]
    assert "示例 1 主动坐下看书或玩手机" not in retry_context["task"]
    assert received[1]["options"]["num_ctx"] == 8192


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
    assert detail.high_risk_fall == 0
    assert detail.review_points == ["建议人工复核事件关键帧。"]


def test_qwen_fall_analyzer_maps_non_fall_seated_rest_to_safe_internal_result() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 0,
            "fall_verdict": "non_fall",
            "scene_type": "seated_rest",
            "recommended_action": "no_alert",
            "positive_evidence": [],
            "negative_evidence": ["身体受到椅子稳定支撑", "未见突然失衡或倒地"],
            "activity": "坐在椅子上休息",
            "posture_state": "seated",
            "fall_transition_visible": False,
            "intentional_action_evidence": True,
            "recovery_observed": None,
            "persistent_ground_state": "not_observed",
            "posture": "人物稳定坐在椅子上休息。",
            "summary": "人物坐姿稳定且有椅子支撑，不属于跌倒。",
            "confidence": 0.96,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.high_risk_fall == 0
    assert detail.fall_verdict == "non_fall"
    assert detail.scene_type == "seated_rest"
    assert detail.recommended_action == "no_alert"


def test_qwen_fall_analyzer_downgrades_confirmed_fall_when_high_risk_gate_is_zero() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 0,
            "fall_verdict": "confirmed_fall",
            "scene_type": "fall",
            "recommended_action": "manual_review",
            "positive_evidence": ["疑似低位"],
            "negative_evidence": ["未见明确失衡倒地"],
            **_transition_evidence(high_risk_fall=0, recommended_action="manual_review"),
            "posture": "人物处于低位。",
            "summary": "可见失衡倒地过程。",
            "confidence": 0.8,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.high_risk_fall == 0
    assert detail.fall_verdict == "unclear"
    assert detail.consistency_status == "corrected"
    assert "high_risk_fall=1" in (detail.consistency_reason or "")


def test_qwen_fall_analyzer_downgrades_high_risk_non_fall_contradiction() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 1,
            "fall_verdict": "non_fall",
            "scene_type": "seated_rest",
            "recommended_action": "emergency_alert",
            "positive_evidence": [],
            "negative_evidence": ["坐在椅子上休息"],
            "activity": "坐在椅子上休息",
            "posture_state": "seated",
            "fall_transition_visible": False,
            "intentional_action_evidence": True,
            "recovery_observed": None,
            "persistent_ground_state": "not_observed",
            "posture": "人物稳定坐在椅子上。",
            "summary": "人物坐在椅子上休息，未见跌倒。",
            "confidence": 0.9,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.high_risk_fall == 0
    assert detail.fall_verdict == "non_fall"
    assert detail.recommended_action == "no_alert"
    assert detail.consistency_status == "corrected"


def test_qwen_fall_analyzer_downgrades_non_fall_with_abnormal_ground_conflict() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 0,
            "fall_verdict": "non_fall",
            "scene_type": "unknown",
            "recommended_action": "manual_review",
            "positive_evidence": ["人物处于低位"],
            "negative_evidence": ["未见明确正常活动证据"],
            "activity": "低位状态不明",
            "posture_state": "ground_low",
            "fall_transition_visible": False,
            "intentional_action_evidence": False,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
            "posture": "人物持续处于地面低位。",
            "summary": "人物处于低位，但没有明确主动行为证据。",
            "confidence": 0.6,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.raw_fall_verdict == "non_fall"
    assert detail.fall_verdict == "unclear"
    assert detail.consistency_status == "corrected"


def test_qwen_fall_analyzer_rejects_ground_low_rest_without_strong_support() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 0,
            "fall_verdict": "non_fall",
            "scene_type": "intentional_low_posture",
            "recommended_action": "no_alert",
            "positive_evidence": [
                "人物从站立姿态主动弯腰并受控坐在地垫上",
                "随后主动调整身体姿态平躺于地面",
            ],
            "negative_evidence": [
                "未见突然失衡、急速下落或非自主翻倒过程",
                "未见跌倒后的痛苦表情或静止状态",
            ],
            "activity": "主动弯腰后平躺休息",
            "posture_state": "lying",
            "fall_transition_visible": False,
            "intentional_action_evidence": True,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
            "posture": "人物受控地从站立弯腰坐地，随后主动调整身体平躺于地面。",
            "summary": "连续画面显示人物从站立姿态主动弯腰、坐下并调整至平躺，动作受控且无失衡迹象，属于正常休息行为。",
            "confidence": 0.95,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.raw_fall_verdict == "non_fall"
    assert detail.fall_verdict == "unclear"
    assert detail.intentional_action_evidence is False
    assert detail.consistency_status == "corrected"


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


def test_qwen_fall_analyzer_preserves_intentional_low_posture_verdict() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "intentional_low_posture",
            **_intentional_evidence(),
            "posture": "人员稳定躺在垫子上阅读。",
            "movement_level": "slight",
            "attempt_to_stand": "not_observed",
            "persistent_ground_state": "not_observed",
            "possible_help_gesture": "not_observed",
            "visibility": "good",
            "occlusion": "none",
            "scene_risks": [],
            "summary": "画面显示自主躺卧阅读，未见失稳跌倒。",
            "review_points": ["关键帧中姿态稳定。"],
            "confidence": 0.9,
        }, ensure_ascii=False)}},
        images=[_image(0)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "intentional_low_posture"


def test_qwen_fall_analyzer_preserves_unclear_ground_evidence_without_fabricating_transition() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "fall_verdict": "unclear",
            "activity": "低位状态不明",
            "posture_state": "ground_low",
            "fall_transition_visible": False,
            "intentional_action_evidence": None,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
            "posture": "人物在所给关键帧中持续处于地面低位。",
            "summary": "未看到进入低位的过程，无法判断是否发生跌倒。",
            "confidence": 0.55,
        }, ensure_ascii=False)}},
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.fall_verdict == "unclear"
    assert detail.posture_state == "ground_low"
    assert detail.fall_transition_visible is False
    assert detail.persistent_ground_state == "observed"


def test_qwen_fall_analyzer_rejects_confirmed_fall_without_visible_transition() -> None:
    calls = 0

    def transport(*_) -> dict:
        nonlocal calls
        calls += 1
        return {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "fall_verdict": "confirmed_fall",
            "activity": "低位状态不明",
            "posture_state": "ground_low",
            "fall_transition_visible": False,
            "intentional_action_evidence": None,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
            "posture": "人物持续处于地面低位。",
            "summary": "没有看到人物如何进入低位。",
            "confidence": 0.7,
        }, ensure_ascii=False)}}

    analyzer = _analyzer(transport, images=[_image(-1000), _image(0), _image(3000)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.fall_verdict == "unclear"
    assert detail.raw_fall_verdict == "confirmed_fall"
    assert detail.consistency_status == "corrected"
    assert detail.fall_transition_visible is False
    assert calls == 1


def test_qwen_fall_analyzer_allows_high_risk_post_fall_abnormal_state_without_transition() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "schema_version": "pfv2_post_fall_detail.v1",
            "high_risk_fall": 1,
            "fall_verdict": "confirmed_fall",
            "scene_type": "fall",
            "recommended_action": "emergency_alert",
            "positive_evidence": ["人物明显异常倒地", "连续关键帧未恢复"],
            "negative_evidence": [],
            "activity": "高危跌倒后异常倒地",
            "posture_state": "ground_low",
            "fall_transition_visible": False,
            "intentional_action_evidence": False,
            "recovery_observed": False,
            "persistent_ground_state": "observed",
            "posture": "人物处于明显异常倒地低位。",
            "summary": "虽未见完整下落过程，但人物持续异常倒地且无主动行为证据。",
            "confidence": 0.88,
        }, ensure_ascii=False)}} ,
        images=[_image(0), _image(1000), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.high_risk_fall == 1
    assert detail.fall_verdict == "confirmed_fall"
    assert detail.fall_transition_visible is False


def test_qwen_fall_analyzer_downgrades_contradictory_active_reading_false_positive() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            "posture": "人物由站立姿态失衡倒地，随即坐在垫子上阅读书籍，属主动恢复低位而非失稳。",
            "movement_level": "unknown",
            "attempt_to_stand": "unknown",
            "persistent_ground_state": "unknown",
            "possible_help_gesture": "unknown",
            "visibility": "unknown",
            "occlusion": "unknown",
            "scene_risks": [],
            "summary": "结合多帧画面判断：后帧为自主坐下读书，更符合主动低位行为。",
            "review_points": ["建议人工复核事件关键帧。"],
            "confidence": 0.9,
        }, ensure_ascii=False)}},
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"


def test_qwen_fall_analyzer_downgrades_controlled_sitting_even_when_enum_is_wrong() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            "posture": "人物主动受控地坐下后阅读。",
            "summary": "连续画面显示人物主动弯腰并受控坐在地垫上，随后稳定坐姿低头看书，未见突然失衡或失控下坠过程。",
            "review_points": ["建议人工复核事件关键帧。"],
            "confidence": 0.92,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"


def test_qwen_fall_analyzer_downgrades_walking_motion_blur_false_positive() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            "posture": "人物处于站立或行走状态。",
            "summary": "画面只是正常行走经过镜头并存在运动模糊，未见明确失衡倒地过程。",
            "confidence": 0.82,
        }, ensure_ascii=False)}} ,
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"


@pytest.mark.parametrize(
    "summary",
    [
        "人物主动坐下看书，过程受控，未见失衡。",
        "人物主动坐下玩手机，后续保持稳定坐姿。",
        "人物主动躺下玩手机，未看到失控下落。",
        "人物主动躺下睡觉，姿态自然稳定。",
        "人物主动躺下看书，没有发生跌倒。",
    ],
)
def test_qwen_fall_analyzer_downgrades_common_active_low_posture_phrases(summary: str) -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            "posture": "人员处于低位姿态。",
            "summary": summary,
            "confidence": 0.88,
        }, ensure_ascii=False)}},
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"


def test_qwen_fall_analyzer_keeps_true_fall_when_summary_denies_active_lie_down() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            **_transition_evidence(),
            "posture": "人物从直立位置迅速倒下并躺在地上。",
            "movement_level": "none_observed",
            "attempt_to_stand": "not_observed",
            "persistent_ground_state": "observed",
            "possible_help_gesture": "not_observed",
            "visibility": "good",
            "occlusion": "none",
            "scene_risks": [],
            "summary": "画面显示人物从直立位置迅速倒下并躺在地上，没有自主躺下的迹象。",
            "review_points": ["关键帧显示突然倒地过程。"],
            "confidence": 0.94,
        }, ensure_ascii=False)}},
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "confirmed_fall"


def test_qwen_fall_analyzer_keeps_true_fall_before_later_phone_use() -> None:
    analyzer = _analyzer(
        lambda *_: {"message": {"content": json.dumps({
            "fall_verdict": "confirmed_fall",
            **_transition_evidence(
                posture_state="seated",
                recovery_observed=True,
                persistent_ground_state="not_observed",
            ),
            "posture": "人物先发生明显非自主跌倒，之后坐起玩手机。",
            "summary": "此前已有清楚失衡倒地过程，后续玩手机不能推翻真实跌倒。",
            "review_points": ["关键帧显示失衡后倒地。"],
            "confidence": 0.94,
        }, ensure_ascii=False)}},
        images=[_image(-1000), _image(0), _image(3000)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "confirmed_fall"


def test_qwen_fall_analyzer_accepts_single_confirmed_fall_verdict() -> None:
    calls = 0

    response = {
        "fall_verdict": "confirmed_fall",
        **_transition_evidence(),
        "posture": "人员失衡后倒地。",
        "movement_level": "none_observed",
        "attempt_to_stand": "not_observed",
        "persistent_ground_state": "observed",
        "possible_help_gesture": "not_observed",
        "visibility": "good",
        "occlusion": "none",
        "scene_risks": [],
        "summary": "可见失衡倒地过程。",
        "review_points": ["关键帧显示失衡后倒地。"],
        "confidence": 0.9,
    }

    def transport(*_) -> dict:
        nonlocal calls
        calls += 1
        return {"message": {"content": json.dumps(response, ensure_ascii=False)}}

    analyzer = _analyzer(
        transport,
        images=[_image(0)],
    )

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "confirmed_fall"
    assert calls == 2


def test_qwen_fall_analyzer_counterchecks_confirmed_fall_and_keeps_deny() -> None:
    calls = 0
    review_modes: list[str] = []
    responses = [
        {
            "fall_verdict": "confirmed_fall",
            **_transition_evidence(),
            "posture": "人物突然失衡后倒地。",
            "summary": "关键帧显示非自主失衡倒地过程。",
            "confidence": 0.9,
        },
        {
            "fall_verdict": "unclear",
            "posture": "人物处于站立或行走状态。",
            "summary": "反证复核未见明确失控倒地过程，可能只是行走或运动模糊。",
            "confidence": 0.8,
        },
    ]

    def transport(payload, _timeout):
        nonlocal calls
        calls += 1
        context = json.loads(payload["messages"][1]["content"])
        review_modes.append(context["review_mode"])
        return {"message": {"content": json.dumps(responses[calls - 1], ensure_ascii=False)}}

    analyzer = _analyzer(transport, images=[_image(-1000), _image(0), _image(3000)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.analysis_status == "completed"
    assert detail.fall_verdict == "unclear"
    assert calls == 2
    assert review_modes == ["首次复核", "反证复核"]


def test_qwen_fall_analyzer_does_not_overturn_fall_for_generic_countercheck_adl() -> None:
    calls = 0
    responses = [
        {
            "fall_verdict": "confirmed_fall",
            **_transition_evidence(),
            "posture": "人物突然失衡后倒地。",
            "summary": "可见明显非自主倒地过程。",
            "confidence": 0.92,
        },
        {
            "fall_verdict": "intentional_low_posture",
            "posture": "人物受控躺在垫子上。",
            "summary": "人物进入低位姿态，动作看起来较为受控。",
            "confidence": 0.7,
        },
    ]

    def transport(*_args):
        nonlocal calls
        calls += 1
        return {"message": {"content": json.dumps(responses[calls - 1], ensure_ascii=False)}}

    analyzer = _analyzer(transport, images=[_image(-1000), _image(0), _image(3000)])

    detail = analyzer.analyze_fall_event(_event(), _package())

    assert detail.fall_verdict == "confirmed_fall"
    assert calls == 2


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


def _transition_evidence(**updates) -> dict:
    evidence = {
        "high_risk_fall": 1,
        "scene_type": "fall",
        "recommended_action": "emergency_alert",
        "positive_evidence": ["明显失衡倒地"],
        "negative_evidence": [],
        "activity": "非自主失衡倒地",
        "posture_state": "ground_low",
        "fall_transition_visible": True,
        "intentional_action_evidence": False,
        "recovery_observed": False,
        "persistent_ground_state": "observed",
    }
    evidence.update(updates)
    return evidence


def _intentional_evidence(**updates) -> dict:
    evidence = {
        "high_risk_fall": 0,
        "scene_type": "intentional_low_posture",
        "recommended_action": "no_alert",
        "positive_evidence": [],
        "negative_evidence": ["主动低姿态"],
        "activity": "主动躺卧阅读",
        "posture_state": "lying",
        "fall_transition_visible": False,
        "intentional_action_evidence": True,
        "recovery_observed": False,
        "persistent_ground_state": "observed",
    }
    evidence.update(updates)
    return evidence


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
