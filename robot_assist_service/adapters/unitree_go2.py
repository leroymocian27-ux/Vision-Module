from __future__ import annotations

from typing import AsyncIterator

from app.contracts.integration_v1 import RobotAssistTask, RobotTaskState
from robot_assist_service.adapters.base import RobotAdapter, RobotAdapterError, RobotAdapterStatus


class UnitreeGo2Adapter(RobotAdapter):
    """Phase-11 interface skeleton. V1 deliberately contains no SDK or DDS call."""

    def status(self) -> RobotAdapterStatus:
        return RobotAdapterStatus(
            adapter="unitree_go2",
            online=False,
            simulated=False,
            control_available=False,
            detail="real Go2 control is forbidden until the dedicated read-only and safety gates pass",
        )

    async def execute(self, task: RobotAssistTask) -> AsyncIterator[tuple[RobotTaskState, str, dict]]:
        raise RobotAdapterError("real Go2 execution is forbidden in RobotAssistService V1")
        yield RobotTaskState.FAILED, "unreachable", {}

    async def cancel(self, task: RobotAssistTask) -> None:
        raise RobotAdapterError("real Go2 cancellation is unavailable because real control is disabled")
