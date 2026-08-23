from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

from app.contracts.integration_v1 import RobotAssistTask, RobotTaskState


class RobotAdapterError(RuntimeError):
    code = "ROBOT_ADAPTER_ERROR"


@dataclass(frozen=True)
class RobotAdapterStatus:
    adapter: str
    online: bool
    simulated: bool
    control_available: bool
    detail: str = ""


class RobotAdapter(ABC):
    @abstractmethod
    def status(self) -> RobotAdapterStatus:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, task: RobotAssistTask) -> AsyncIterator[tuple[RobotTaskState, str, dict]]:
        raise NotImplementedError

    @abstractmethod
    async def cancel(self, task: RobotAssistTask) -> None:
        raise NotImplementedError
