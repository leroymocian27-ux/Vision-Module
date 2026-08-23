from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReconnectPolicy:
    initial_delay_sec: float = 1.0
    max_delay_sec: float = 10.0
    factor: float = 1.7
    schedule_sec: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        self._failures = 0

    def reset(self) -> None:
        self._failures = 0

    def next_delay(self) -> float:
        if self.schedule_sec:
            index = min(self._failures, len(self.schedule_sec) - 1)
            self._failures += 1
            return self.schedule_sec[index]
        delay = self.initial_delay_sec * (self.factor ** self._failures)
        self._failures += 1
        return min(delay, self.max_delay_sec)

