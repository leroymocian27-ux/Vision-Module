"""Versioned, transport-neutral contracts for the elder-care integration."""

from app.contracts.integration_v1 import (
    QwenAdvisoryInput,
    QwenAdvisoryOutput,
    RobotAssistTask,
    RobotAssistTaskEvent,
    RobotTaskState,
    VisionEventMetadataExtension,
    allowed_task_transitions,
    validate_task_transition,
)

__all__ = [
    "QwenAdvisoryInput",
    "QwenAdvisoryOutput",
    "RobotAssistTask",
    "RobotAssistTaskEvent",
    "RobotTaskState",
    "VisionEventMetadataExtension",
    "allowed_task_transitions",
    "validate_task_transition",
]
