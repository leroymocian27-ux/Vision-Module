from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.contracts.integration_v1 import RobotAssistTask, RobotTaskTransitionError
from robot_assist_service.service import (
    RobotAssistTaskService,
    RobotTaskApprovalRequiredError,
    RobotTaskNotFoundError,
)


class ApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=256)


class CancelRequest(BaseModel):
    reason: str = Field(default="cancelled by operator", min_length=1, max_length=1000)


router = APIRouter(prefix="/api/v1", tags=["robot-assist"])


def _service(request: Request) -> RobotAssistTaskService:
    return request.app.state.robot_assist_service


@router.get("/robot/status")
async def robot_status(request: Request) -> dict:
    return _service(request).status()


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(task: RobotAssistTask, request: Request) -> dict:
    stored, idempotent_replay = await _service(request).create_task(task)
    return {"task": stored, "idempotent_replay": idempotent_replay}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> RobotAssistTask:
    return _service(request).get_task(task_id)


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request) -> dict:
    return {"events": _service(request).list_events(task_id)}


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, approval: ApprovalRequest, request: Request) -> RobotAssistTask:
    return await _service(request).approve_task(task_id, approval.approved_by)


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, cancel: CancelRequest, request: Request) -> RobotAssistTask:
    return await _service(request).cancel_task(task_id, cancel.reason)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RobotTaskNotFoundError)
    async def task_not_found_handler(_: Request, exc: RobotTaskNotFoundError):
        return _error_response(404, exc.code, "robot task not found")

    @app.exception_handler(RobotTaskApprovalRequiredError)
    async def approval_handler(_: Request, exc: RobotTaskApprovalRequiredError):
        return _error_response(409, exc.code, str(exc))

    @app.exception_handler(RobotTaskTransitionError)
    async def transition_handler(_: Request, exc: RobotTaskTransitionError):
        return _error_response(409, exc.code, str(exc))


def _error_response(status_code: int, code: str, detail: str):
    return JSONResponse(status_code=status_code, content={"detail": {"code": code, "message": detail}})
