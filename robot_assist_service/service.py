from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.contracts.integration_v1 import (
    RobotAssistTask,
    RobotAssistTaskEvent,
    RobotTaskState,
    RobotTaskTransitionError,
    TERMINAL_TASK_STATES,
    validate_task_transition,
)
from robot_assist_service.adapters.base import RobotAdapter, RobotAdapterError
from robot_assist_service.repository import RobotTaskRepository


class RobotTaskServiceError(RuntimeError):
    code = "ROBOT_TASK_ERROR"


class RobotTaskNotFoundError(RobotTaskServiceError):
    code = "ROBOT_TASK_NOT_FOUND"


class RobotTaskApprovalRequiredError(RobotTaskServiceError):
    code = "ROBOT_TASK_APPROVAL_REQUIRED"


class RobotAssistTaskService:
    def __init__(self, *, repository: RobotTaskRepository, adapter: RobotAdapter) -> None:
        self.repository = repository
        self.adapter = adapter
        self._lock = asyncio.Lock()
        self._executions: dict[str, asyncio.Task[None]] = {}
        self._recover_non_terminal_tasks()

    def _recover_non_terminal_tasks(self) -> None:
        for task in self.repository.list_non_terminal_tasks():
            recovered = task.model_copy(
                update={"state": RobotTaskState.SAFETY_BLOCKED, "updated_at": datetime.now(timezone.utc)}
            )
            self.repository.update_task(recovered)
            self.repository.append_event(
                self._event(
                    recovered,
                    event_type="safety",
                    previous_state=task.state,
                    source="robot_assist_service",
                    message="service restart requires manual task recovery",
                    details={"recovery_action": "safety_blocked", "adapter": self.adapter.status().adapter},
                )
            )

    async def create_task(self, task: RobotAssistTask) -> tuple[RobotAssistTask, bool]:
        async with self._lock:
            existing = self.repository.create_task(task)
            if existing is not None:
                return existing, True
            self.repository.append_event(
                self._event(task, event_type="audit", previous_state=None, source="main_system", message="task created")
            )
            task = await self._transition_locked(task, RobotTaskState.POLICY_CHECKED, "robot_assist_service", "policy check passed")
            task = await self._transition_locked(task, RobotTaskState.AWAITING_APPROVAL, "robot_assist_service", "awaiting community approval")
            if task.approval_status == "approved":
                task = await self._queue_locked(task, "task supplied with approved audit fields")
            return task, False

    async def approve_task(self, task_id: str, approved_by: str) -> RobotAssistTask:
        if not approved_by.strip():
            raise RobotTaskApprovalRequiredError("approved_by is required")
        async with self._lock:
            task = self._required_task(task_id)
            if task.state != RobotTaskState.AWAITING_APPROVAL:
                raise RobotTaskTransitionError(f"approval not allowed from {task.state}")
            task = task.model_copy(
                update={
                    "approval_status": "approved",
                    "approved_by": approved_by,
                    "approved_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.repository.update_task(task)
            self.repository.append_event(
                self._event(task, event_type="audit", previous_state=task.state, source="main_system", message="task approved")
            )
            return await self._queue_locked(task, "approved by community staff")

    async def cancel_task(self, task_id: str, reason: str = "cancelled by operator") -> RobotAssistTask:
        execution: asyncio.Task[None] | None = None
        async with self._lock:
            task = self._required_task(task_id)
            if task.state in TERMINAL_TASK_STATES:
                raise RobotTaskTransitionError(f"cannot cancel terminal task {task.state}")
            execution = self._executions.pop(task.task_id, None)
            task = await self._transition_locked(task, RobotTaskState.CANCELLED, "main_system", reason)
        if execution is not None:
            execution.cancel()
        await self.adapter.cancel(task)
        return task

    def get_task(self, task_id: str) -> RobotAssistTask:
        return self._required_task(task_id)

    def list_events(self, task_id: str) -> list[RobotAssistTaskEvent]:
        self._required_task(task_id)
        return self.repository.list_events(task_id)

    def status(self) -> dict:
        adapter_status = self.adapter.status()
        return {
            "adapter": adapter_status.adapter,
            "online": adapter_status.online,
            "simulated": adapter_status.simulated,
            "control_available": adapter_status.control_available,
            "detail": adapter_status.detail,
            "task_counts": self.repository.status_counts(),
        }

    async def _queue_locked(self, task: RobotAssistTask, message: str) -> RobotAssistTask:
        if task.approval_status != "approved":
            raise RobotTaskApprovalRequiredError("approved task required before queueing")
        task = await self._transition_locked(task, RobotTaskState.QUEUED, "robot_assist_service", message)
        if not self.adapter.status().online:
            return await self._transition_locked(task, RobotTaskState.SAFETY_BLOCKED, "robot_assist_service", "adapter offline")
        self._executions[task.task_id] = asyncio.create_task(self._execute_mock(task.task_id))
        return task

    async def _execute_mock(self, task_id: str) -> None:
        try:
            task = self._required_task(task_id)
            async for next_state, message, details in self.adapter.execute(task):
                async with self._lock:
                    current = self._required_task(task_id)
                    if current.state in TERMINAL_TASK_STATES:
                        return
                    current = await self._transition_locked(current, next_state, "mock_adapter", message, details)
                    if current.state in TERMINAL_TASK_STATES:
                        return
        except asyncio.CancelledError:
            raise
        except RobotAdapterError as exc:
            async with self._lock:
                current = self._required_task(task_id)
                if current.state not in TERMINAL_TASK_STATES:
                    await self._transition_locked(current, RobotTaskState.FAILED, "mock_adapter", str(exc), {"adapter": "mock", "simulated": True})
        finally:
            self._executions.pop(task_id, None)

    async def _transition_locked(
        self,
        task: RobotAssistTask,
        next_state: RobotTaskState,
        source: str,
        message: str,
        details: dict | None = None,
    ) -> RobotAssistTask:
        validate_task_transition(task, next_state)
        updated = task.model_copy(update={"state": next_state, "updated_at": datetime.now(timezone.utc)})
        self.repository.update_task(updated)
        self.repository.append_event(
            self._event(
                updated,
                event_type="state_changed",
                previous_state=task.state,
                source=source,  # type: ignore[arg-type]
                message=message,
                details=details or {"adapter": self.adapter.status().adapter, "simulated": self.adapter.status().simulated},
            )
        )
        return updated

    def _required_task(self, task_id: str) -> RobotAssistTask:
        task = self.repository.get_task(task_id)
        if task is None:
            raise RobotTaskNotFoundError(task_id)
        return task

    @staticmethod
    def _event(
        task: RobotAssistTask,
        *,
        event_type: str,
        previous_state: RobotTaskState | None,
        source: str,
        message: str,
        details: dict | None = None,
    ) -> RobotAssistTaskEvent:
        return RobotAssistTaskEvent(
            event_id=f"robot-event-{uuid4()}",
            task_id=task.task_id,
            event_type=event_type,  # type: ignore[arg-type]
            previous_state=previous_state,
            current_state=task.state,
            source=source,  # type: ignore[arg-type]
            message=message,
            details=details or {},
        )
