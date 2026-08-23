from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_runtime
from app.core.runtime import Runtime
from app.identity.schemas import EnrollResult, IdentityStoreEntry

router = APIRouter(prefix="/identity", tags=["identity"])


@router.post("/enroll", response_model=EnrollResult)
async def enroll_identity(
    person_id: str = Form(...),
    person_name: str = Form(...),
    replace_existing: bool = Form(False),
    files: list[UploadFile] = File(...),
    runtime: Runtime = Depends(get_runtime),
) -> EnrollResult:
    if not 1 <= len(files) <= runtime.settings.identity_max_images:
        raise HTTPException(
            status_code=400,
            detail=f"upload 1-{runtime.settings.identity_max_images} face images",
        )

    images: list[bytes] = []
    for item in files:
        if item.content_type and not item.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"invalid image content type: {item.filename}")
        images.append(await item.read())

    try:
        return runtime.identity_service.enroll(
            person_id=person_id,
            person_name=person_name,
            images=images,
            replace_existing=replace_existing,
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/list", response_model=list[IdentityStoreEntry])
def list_identities(runtime: Runtime = Depends(get_runtime)) -> list[IdentityStoreEntry]:
    return runtime.identity_service.list_identities()


@router.delete("/{person_id}")
def delete_identity(
    person_id: str,
    runtime: Runtime = Depends(get_runtime),
) -> dict[str, str]:
    deleted = runtime.identity_service.delete(person_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"identity not found: {person_id}")
    return {"person_id": person_id, "status": "deleted"}
