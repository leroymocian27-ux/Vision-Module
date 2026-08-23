from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RobotAssistSettings:
    enabled: bool = os.getenv("ROBOT_ASSIST_SERVICE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    database_path: Path = Path("data/robot_assist.sqlite3")
    adapter_mode: str = "mock"
    mock_step_delay_seconds: float = 0.05
    mock_outcome: str = "success"

    def __post_init__(self) -> None:
        if self.adapter_mode != "mock":
            raise ValueError("RobotAssistService V1 only supports adapter_mode=mock")
        if self.mock_outcome not in {"success", "failed", "timeout", "offline"}:
            raise ValueError("mock_outcome must be success, failed, timeout, or offline")
        if self.mock_step_delay_seconds < 0:
            raise ValueError("mock_step_delay_seconds must be non-negative")
