from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.contracts.integration_v1 import (
    QwenAdvisoryInput,
    QwenAdvisoryOutput,
    RobotAssistTask,
    RobotAssistTaskEvent,
    RobotTaskState,
    RobotTaskTransitionError,
    VisionEventMetadataExtension,
    allowed_task_transitions,
    contract_json_schemas,
    validate_task_transition,
)
from app.events.delivery import build_main_system_payload
from app.events.schemas import EvidenceKeyframe, EvidencePackage, TrustedEventResult


def _approved_task(state: RobotTaskState = RobotTaskState.CREATED) -> RobotAssistTask:
    return RobotAssistTask(
        task_id="robot-task-001",
        idempotency_key="alarm-001:fall_scene_check:living-room-point-a",
        incident_id="incident-001",
        alarm_id="alarm-001",
        elder_id="elder-001",
        target_room="living_room",
        observation_point_id="living-room-point-a",
        approval_status="approved",
        approved_by="community-user-001",
        approved_at=datetime.now(timezone.utc),
        state=state,
    )


def test_vision_extension_is_additive_and_never_accepts_absolute_keyframe_paths() -> None:
    extension = VisionEventMetadataExtension.model_validate(
        {
            "evidence": {
                "evidence_status": "complete",
                "keyframe_count": 6,
                "keyframe_urls": ["/events/incident-001/keyframes/t0"],
            },
            "semantic_analysis": {
                "support_fall_alarm": True,
                "final_event_type": "fall_confirmed",
                "final_risk_level": "high",
                "explanation": "rule-based confirmed event",
            },
            "robot_advisory": {"robot_assist_recommended": True, "reason": "human review requested"},
        }
    )
    assert extension.extension_schema == "eldercare.vision-event-extension.v1"

    with pytest.raises(ValidationError):
        VisionEventMetadataExtension.model_validate(
            {
                "evidence": {"evidence_status": "complete", "keyframe_count": 1, "keyframe_urls": ["C:\\archive\\frame.jpg"]},
                "semantic_analysis": {"support_fall_alarm": True, "final_event_type": "fall", "final_risk_level": "high", "explanation": "x"},
                "robot_advisory": {"robot_assist_recommended": False},
            }
        )


def test_qwen_input_is_allowlisted_and_output_is_advisory_only() -> None:
    payload = QwenAdvisoryInput.model_validate(
        {
            "fall_state": "fallen_confirmed",
            "risk_level": "high",
            "evidence_completeness": "degraded",
            "missing_reasons": ["frame_not_available"],
        }
    )
    assert "incident_id" not in payload.model_dump()

    with pytest.raises(ValidationError):
        QwenAdvisoryInput.model_validate(
            {
                "fall_state": "fallen_confirmed",
                "risk_level": "high",
                "evidence_completeness": "complete",
                "incident_id": "forbidden-stable-identifier",
            }
        )

    output = QwenAdvisoryOutput(
        summary="A fall event requires staff review.",
        robot_assist_recommended=True,
        advisory_confidence="low",
    )
    assert output.robot_assist_recommended is True


def test_robot_state_machine_requires_approval_and_has_no_terminal_reentry() -> None:
    pending = _approved_task().model_copy(update={"approval_status": "pending", "approved_by": None, "approved_at": None, "state": RobotTaskState.AWAITING_APPROVAL})
    with pytest.raises(RobotTaskTransitionError):
        validate_task_transition(pending, RobotTaskState.QUEUED)

    approved = _approved_task(state=RobotTaskState.AWAITING_APPROVAL)
    validate_task_transition(approved, RobotTaskState.QUEUED)
    assert RobotTaskState.QUEUED in allowed_task_transitions(RobotTaskState.AWAITING_APPROVAL)
    assert allowed_task_transitions(RobotTaskState.CANCELLED) == frozenset()


def test_robot_events_are_timestamped_and_contract_schemas_are_exportable() -> None:
    event = RobotAssistTaskEvent(
        event_id="event-001",
        task_id="robot-task-001",
        event_type="state_changed",
        previous_state=RobotTaskState.QUEUED,
        current_state=RobotTaskState.DISPATCHING,
        source="mock_adapter",
        message="simulated dispatch started",
        details={"adapter": "mock", "simulated": True},
    )
    assert event.timestamp.tzinfo is not None
    schemas = contract_json_schemas()
    assert set(schemas) == {
        "vision_event_metadata_extension",
        "qwen_advisory_input",
        "qwen_advisory_output",
        "robot_assist_task",
        "robot_assist_task_event",
    }
    assert schemas["robot_assist_task"]["additionalProperties"] is False


def test_delivery_payload_keeps_legacy_fields_without_robot_extension() -> None:
    evidence = EvidencePackage(
        incident_id="incident-001",
        camera_id="camera-001",
        trigger_timestamp="2026-07-19T00:00:00+00:00",
        keyframes=[EvidenceKeyframe(role="trigger", offset_ms=0, missing_reason="frame_not_available")],
    )
    trusted = TrustedEventResult(
        incident_id="incident-001",
        support_fall_alarm=True,
        final_event_type="fall_confirmed",
        final_risk_level="high",
        confidence=0.9,
        explanation="rule result",
        alarm_title="Fall",
        alarm_body="Fall confirmed",
        recommended_action="Staff review",
    )
    payload = build_main_system_payload(trusted, evidence)
    extension = payload["metadata"]
    assert payload["incident_id"] == "incident-001"
    assert extension["extension_schema"] == "eldercare.vision-event-extension.v1"
    assert extension["evidence"]["evidence_status"] == "degraded"
    assert extension["evidence"]["keyframe_urls"] == []
    assert "robot_advisory" not in extension
