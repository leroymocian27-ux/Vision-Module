from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.schemas.status import VisionStatus

router = APIRouter(tags=["status"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status", response_model=VisionStatus)
def status(
    camera_id: str | None = None,
    runtime: Runtime = Depends(get_runtime),
) -> VisionStatus:
    return runtime.status_service.status(camera_id=camera_id)

