from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.contracts.integration_v1 import RobotAssistTask, RobotAssistTaskEvent, TERMINAL_TASK_STATES


class RobotTaskRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS robot_assist_tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS robot_assist_task_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_robot_task_events_task_sequence
                    ON robot_assist_task_events(task_id, sequence);
                """
            )

    def get_task(self, task_id: str) -> RobotAssistTask | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_json FROM robot_assist_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return RobotAssistTask.model_validate_json(row["task_json"]) if row else None

    def get_task_by_idempotency_key(self, idempotency_key: str) -> RobotAssistTask | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT task_json FROM robot_assist_tasks WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return RobotAssistTask.model_validate_json(row["task_json"]) if row else None

    def create_task(self, task: RobotAssistTask) -> RobotAssistTask | None:
        """Return an existing task for an idempotency collision, otherwise persist new task."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO robot_assist_tasks(task_id, idempotency_key, state, task_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.idempotency_key,
                        str(task.state),
                        task.model_dump_json(),
                        task.updated_at.isoformat(),
                    ),
                )
            return None
        except sqlite3.IntegrityError:
            return self.get_task_by_idempotency_key(task.idempotency_key)

    def update_task(self, task: RobotAssistTask) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE robot_assist_tasks
                SET state = ?, task_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (str(task.state), task.model_dump_json(), task.updated_at.isoformat(), task.task_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(task.task_id)

    def append_event(self, event: RobotAssistTaskEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO robot_assist_task_events(event_id, task_id, event_json)
                VALUES (?, ?, ?)
                """,
                (event.event_id, event.task_id, event.model_dump_json()),
            )

    def list_events(self, task_id: str) -> list[RobotAssistTaskEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_json FROM robot_assist_task_events
                WHERE task_id = ? ORDER BY sequence ASC
                """,
                (task_id,),
            ).fetchall()
        return [RobotAssistTaskEvent.model_validate_json(row["event_json"]) for row in rows]

    def list_non_terminal_tasks(self) -> list[RobotAssistTask]:
        terminal = tuple(str(state) for state in TERMINAL_TASK_STATES)
        placeholders = ",".join("?" for _ in terminal)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT task_json FROM robot_assist_tasks WHERE state NOT IN ({placeholders})",
                terminal,
            ).fetchall()
        return [RobotAssistTask.model_validate_json(row["task_json"]) for row in rows]

    def status_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS count FROM robot_assist_tasks GROUP BY state"
            ).fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}
