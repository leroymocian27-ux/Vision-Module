from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from robot_assist_service.settings import RobotAssistSettings


def create_robot_assist_app(settings: RobotAssistSettings | None = None) -> FastAPI:
    settings = settings or RobotAssistSettings()
    app = FastAPI(title="Robot Assist Service", version="0.1.0")
    app.state.robot_assist_service_enabled = settings.enabled
    if settings.enabled:
        from robot_assist_service.adapters.mock import MockRobotAdapter
        from robot_assist_service.api import install_error_handlers, router
        from robot_assist_service.repository import RobotTaskRepository
        from robot_assist_service.service import RobotAssistTaskService

        app.state.robot_assist_service = RobotAssistTaskService(
            repository=RobotTaskRepository(settings.database_path),
            adapter=MockRobotAdapter(
                step_delay_seconds=settings.mock_step_delay_seconds,
                outcome=settings.mock_outcome,
            ),
        )
        install_error_handlers(app)
        app.include_router(router)

    @app.get("/healthz")
    async def healthz() -> dict:
        if not settings.enabled:
            return {"status": "disabled", "adapter": "mock", "simulated": True}
        return {"status": "ok", "adapter": "mock", "simulated": True}

    return app


if __name__ == "__main__":
    uvicorn.run(create_robot_assist_app(), host="127.0.0.1", port=8200)
