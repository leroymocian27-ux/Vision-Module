from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkerHealthSnapshot:
    worker_alive: bool
    restart_count: int
    success_count: int
    error_count: int
    last_success_at: float | None = None
    last_error_at: float | None = None
    last_error: str | None = None
    last_latency_ms: float | None = None


class WorkerHealthTracker:
    def __init__(self) -> None:
        self._restart_count = 0
        self._success_count = 0
        self._error_count = 0
        self._last_success_at: float | None = None
        self._last_error_at: float | None = None
        self._last_error: str | None = None
        self._last_latency_ms: float | None = None

    def mark_restart(self) -> None:
        self._restart_count += 1

    def mark_success(self, latency_ms: float) -> None:
        self._success_count += 1
        self._last_success_at = time.time()
        self._last_latency_ms = round(latency_ms, 2)
        self._last_error = None

    def mark_error(self, error: str) -> None:
        self._error_count += 1
        self._last_error_at = time.time()
        self._last_error = error

    def snapshot(self, worker_alive: bool) -> WorkerHealthSnapshot:
        return WorkerHealthSnapshot(
            worker_alive=worker_alive,
            restart_count=self._restart_count,
            success_count=self._success_count,
            error_count=self._error_count,
            last_success_at=self._last_success_at,
            last_error_at=self._last_error_at,
            last_error=self._last_error,
            last_latency_ms=self._last_latency_ms,
        )
