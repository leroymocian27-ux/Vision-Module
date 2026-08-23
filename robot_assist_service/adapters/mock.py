from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.contracts.integration_v1 import RobotAssistTask, RobotTaskState
from robot_assist_service.adapters.base import RobotAdapter, RobotAdapterError, RobotAdapterStatus


class MockRobotAdapter(RobotAdapter):
    """Deterministic simulated adapter. It never imports or contacts a Go2 SDK."""

    def __init__(self, *, step_delay_seconds: float = 0.05, outcome: str = "success") -> None:
        self._step_delay_seconds = step_delay_seconds
        self._outcome = outcome

    def status(self) -> RobotAdapterStatus:
        return RobotAdapterStatus(
            adapter="mock",
            online=self._outcome != "offline",
            simulated=True,
            control_available=True,
            detail=f"simulated outcome={self._outcome}",
        )

    async def execute(self, task: RobotAssistTask) -> AsyncIterator[tuple[RobotTaskState, str, dict]]:
        if self._outcome == "offline":
            raise RobotAdapterError("mock adapter is intentionally offline")

        for state, message in (
            (RobotTaskState.DISPATCHING, "simulated dispatch started"),
            (RobotTaskState.EXECUTING, "simulated fixed observation-point travel"),
        ):
            await asyncio.sleep(self._step_delay_seconds)
            yield state, message, {"adapter": "mock", "simulated": True}

        if self._outcome == "failed":
            raise RobotAdapterError("mock adapter simulated execution failure")
        if self._outcome == "timeout":
            await asyncio.sleep(self._step_delay_seconds)
            yield RobotTaskState.TIMED_OUT, "mock adapter simulated timeout", {"adapter": "mock", "simulated": True}
            return

        for state, message in (
            (RobotTaskState.ARRIVED, "simulated arrival at fixed observation point"),
            (RobotTaskState.CHECKING, "simulated scene check"),
            (RobotTaskState.COMPLETED, "simulated scene check completed"),
        ):
            await asyncio.sleep(self._step_delay_seconds)
            yield state, message, {"adapter": "mock", "simulated": True}

    async def cancel(self, task: RobotAssistTask) -> None:
        # Cancellation is only an audit-visible simulation in V1.
        await asyncio.sleep(0)
