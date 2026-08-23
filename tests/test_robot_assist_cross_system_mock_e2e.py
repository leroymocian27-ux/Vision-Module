from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

HEALTH_ROOT = Path("D:/Program/health(5-19)")
if str(HEALTH_ROOT) not in sys.path:
    sys.path.insert(0, str(HEALTH_ROOT))

from backend.models.alarm_model import AlarmLayer, AlarmPriority, AlarmRecord, AlarmType
from backend.models.robot_assist_model import RobotAssistTaskEvent as MainTaskEvent
from backend.models.robot_assist_model import RobotTaskCreateRequest, RobotTaskState as MainState
from backend.repositories.robot_assist_repo import RobotAssistRepository as MainRepository
from backend.services.robot_assist_service import RobotAssistService as MainTaskService

from app.contracts.integration_v1 import RobotAssistTask as RobotTask
from app.contracts.integration_v1 import RobotTaskState
from robot_assist_service.adapters.mock import MockRobotAdapter
from robot_assist_service.repository import RobotTaskRepository
from robot_assist_service.service import RobotAssistTaskService


class _Alarms:
    def __init__(self, alarm: AlarmRecord) -> None:
        self.alarm = alarm

    def list_alarms(self, *, active_only: bool = False) -> list[AlarmRecord]:
        return [self.alarm] if not active_only or not self.alarm.acknowledged else []


def test_main_approval_to_mock_execution_to_status_callback_closes_software_loop() -> None:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        alarm = AlarmRecord(
            id="alarm-001",
            device_mac="AA:BB:CC:DD:EE:FF",
            alarm_type=AlarmType.FALL_DETECTED,
            alarm_level=AlarmPriority.CRITICAL,
            alarm_layer=AlarmLayer.REALTIME,
            message="confirmed fall",
            metadata={"incident_id": "incident-001"},
        )
        main = MainTaskService(MainRepository(f"sqlite:///{root / 'main.sqlite3'}"), _Alarms(alarm))
        created, replay = main.create_for_alarm(
            alarm.id,
            RobotTaskCreateRequest(
                incident_id="incident-001",
                elder_id="elder-001",
                target_room="living_room",
                observation_point_id="living-room-point-a",
            ),
        )
        assert replay is False
        approved = main.approve(created.task_id, "community-user-001")
        assert approved.state == MainState.QUEUED

        mock = RobotAssistTaskService(
            repository=RobotTaskRepository(root / "robot.sqlite3"),
            adapter=MockRobotAdapter(step_delay_seconds=0, outcome="success"),
        )
        robot_task = RobotTask(
            task_id=approved.task_id,
            idempotency_key=approved.idempotency_key,
            incident_id=approved.incident_id,
            alarm_id=approved.alarm_id,
            elder_id=approved.elder_id,
            target_room=approved.target_room,
            observation_point_id=approved.observation_point_id,
            priority=approved.priority,
            approval_status="approved",
            approved_by=approved.approved_by,
            approved_at=approved.approved_at,
            adapter_mode="mock",
        )

        async def execute_and_callback() -> None:
            queued, duplicate = await mock.create_task(robot_task)
            assert duplicate is False
            for _ in range(100):
                current = mock.get_task(queued.task_id)
                if current.state == RobotTaskState.COMPLETED:
                    break
                await asyncio.sleep(0.005)
            assert mock.get_task(queued.task_id).state == RobotTaskState.COMPLETED
            for event in mock.list_events(queued.task_id):
                if event.current_state in {RobotTaskState.DISPATCHING, RobotTaskState.EXECUTING, RobotTaskState.ARRIVED, RobotTaskState.CHECKING, RobotTaskState.COMPLETED}:
                    main.ingest_event(
                        approved.task_id,
                        MainTaskEvent(
                            event_id=f"main-{event.event_id}",
                            task_id=approved.task_id,
                            previous_state=MainState(event.previous_state) if event.previous_state else None,
                            current_state=MainState(event.current_state),
                            source="mock_adapter",
                            message=event.message,
                            details={"adapter": "mock", "simulated": True},
                            timestamp=datetime.now(timezone.utc),
                        ),
                    )

        asyncio.run(execute_and_callback())
        completed = main.get(approved.task_id)
        assert completed.state == MainState.COMPLETED
        assert any(event.details.get("simulated") is True for event in main.events(completed.task_id))
