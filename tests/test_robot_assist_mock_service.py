from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.contracts.integration_v1 import RobotAssistTask, RobotTaskState
from robot_assist_service.adapters.mock import MockRobotAdapter
from robot_assist_service.main import create_robot_assist_app
from robot_assist_service.repository import RobotTaskRepository
from robot_assist_service.service import RobotAssistTaskService
from robot_assist_service.settings import RobotAssistSettings


def _task(*, task_id: str = "task-001", approved: bool = False) -> RobotAssistTask:
    values = {
        "task_id": task_id,
        "idempotency_key": "alarm-001:fall_scene_check:point-a",
        "incident_id": "incident-001",
        "alarm_id": "alarm-001",
        "elder_id": "elder-001",
        "target_room": "living_room",
        "observation_point_id": "point-a",
    }
    if approved:
        values.update(
            {
                "approval_status": "approved",
                "approved_by": "community-user-001",
                "approved_at": datetime.now(timezone.utc),
            }
        )
    return RobotAssistTask(**values)


def _service(path: Path, *, outcome: str = "success", delay: float = 0) -> RobotAssistTaskService:
    return RobotAssistTaskService(
        repository=RobotTaskRepository(path),
        adapter=MockRobotAdapter(step_delay_seconds=delay, outcome=outcome),
    )


async def _wait_for_terminal(service: RobotAssistTaskService, task_id: str) -> RobotAssistTask:
    for _ in range(100):
        task = service.get_task(task_id)
        if task.state in {state.value for state in (RobotTaskState.COMPLETED, RobotTaskState.FAILED, RobotTaskState.TIMED_OUT, RobotTaskState.SAFETY_BLOCKED)}:
            return task
        await asyncio.sleep(0.005)
    raise AssertionError("mock task did not finish")


def test_pending_task_needs_approval_and_idempotency_preserves_one_audit_timeline() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir) / "robot.sqlite3")

        async def scenario() -> None:
            first, replay = await service.create_task(_task())
            second, duplicate = await service.create_task(_task(task_id="task-duplicate"))
            assert replay is False
            assert duplicate is True
            assert first.task_id == second.task_id
            assert first.state == RobotTaskState.AWAITING_APPROVAL
            assert [event.current_state for event in service.list_events(first.task_id)] == [
                RobotTaskState.CREATED,
                RobotTaskState.POLICY_CHECKED,
                RobotTaskState.AWAITING_APPROVAL,
            ]

        asyncio.run(scenario())


def test_approved_mock_task_completes_with_explicit_simulation_audit() -> None:
    with TemporaryDirectory() as temp_dir:
        service = _service(Path(temp_dir) / "robot.sqlite3", delay=0)

        async def scenario() -> None:
            task, replay = await service.create_task(_task(approved=True))
            assert replay is False
            assert task.state == RobotTaskState.QUEUED
            completed = await _wait_for_terminal(service, task.task_id)
            assert completed.state == RobotTaskState.COMPLETED
            events = service.list_events(task.task_id)
            assert [event.current_state for event in events][-1] == RobotTaskState.COMPLETED
            assert all(event.details.get("simulated", True) for event in events[3:])

        asyncio.run(scenario())


def test_mock_failure_timeout_offline_cancel_and_restart_recovery_are_safe() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)

        async def scenario() -> None:
            failed_service = _service(root / "failed.sqlite3", outcome="failed")
            failed, _ = await failed_service.create_task(_task(task_id="failed", approved=True))
            assert (await _wait_for_terminal(failed_service, failed.task_id)).state == RobotTaskState.FAILED

            timeout_service = _service(root / "timeout.sqlite3", outcome="timeout")
            timeout, _ = await timeout_service.create_task(_task(task_id="timeout", approved=True))
            assert (await _wait_for_terminal(timeout_service, timeout.task_id)).state == RobotTaskState.TIMED_OUT

            offline_service = _service(root / "offline.sqlite3", outcome="offline")
            offline, _ = await offline_service.create_task(_task(task_id="offline", approved=True))
            assert offline_service.get_task(offline.task_id).state == RobotTaskState.SAFETY_BLOCKED

            cancel_service = _service(root / "cancel.sqlite3", delay=0.2)
            cancel, _ = await cancel_service.create_task(_task(task_id="cancel", approved=True))
            assert (await cancel_service.cancel_task(cancel.task_id)).state == RobotTaskState.CANCELLED

            recovery_path = root / "recovery.sqlite3"
            recovery_service = _service(recovery_path)
            pending, _ = await recovery_service.create_task(_task(task_id="recovery"))
            restarted = _service(recovery_path)
            assert restarted.get_task(pending.task_id).state == RobotTaskState.SAFETY_BLOCKED

        asyncio.run(scenario())


def test_mock_service_api_exposes_health_status_task_and_not_found_error() -> None:
    with TemporaryDirectory() as temp_dir:
        app = create_robot_assist_app(
            RobotAssistSettings(enabled=True, database_path=Path(temp_dir) / "robot.sqlite3", mock_step_delay_seconds=0.2)
        )
        with TestClient(app) as client:
            assert client.get("/healthz").json() == {"status": "ok", "adapter": "mock", "simulated": True}
            created = client.post("/api/v1/tasks", json=_task().model_dump(mode="json"))
            assert created.status_code == 201
            task = created.json()["task"]
            assert task["state"] == "AWAITING_APPROVAL"
            assert client.get("/api/v1/robot/status").json()["simulated"] is True
            missing = client.get("/api/v1/tasks/missing")
            assert missing.status_code == 404
            assert missing.json()["detail"]["code"] == "ROBOT_TASK_NOT_FOUND"


def test_mock_service_api_is_hidden_when_not_explicitly_enabled() -> None:
    app = create_robot_assist_app(RobotAssistSettings())
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "disabled", "adapter": "mock", "simulated": True}
        assert client.get("/api/v1/robot/status").status_code == 404
        assert client.post("/api/v1/tasks", json=_task().model_dump(mode="json")).status_code == 404
