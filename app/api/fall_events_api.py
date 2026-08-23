from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_runtime
from app.core.runtime import Runtime

router = APIRouter(prefix="/fall-events", tags=["fall-events"])


@router.get("/snapshots/{filename}")
def get_fall_event_snapshot(
    filename: str,
    runtime: Runtime = Depends(get_runtime),
) -> FileResponse:
    snapshot_dir = Path(runtime.settings.fall_event_snapshot_dir).resolve()
    path = (snapshot_dir / filename).resolve()
    if snapshot_dir not in path.parents and path != snapshot_dir:
        raise HTTPException(status_code=400, detail="INVALID_SNAPSHOT_PATH")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="SNAPSHOT_NOT_FOUND")
    if path.suffix.lower() not in {".jpg", ".jpeg"}:
        raise HTTPException(status_code=400, detail="UNSUPPORTED_SNAPSHOT_TYPE")
    return FileResponse(path, media_type="image/jpeg")
