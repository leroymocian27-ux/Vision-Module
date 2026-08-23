from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_identity_service
from app.core.config import get_settings
from app.identity.schemas import EnrollResult, IdentityProfile, MatchResult
from app.services.identity_service import IdentityService

router = APIRouter(prefix="/identity", tags=["identity"])


@router.post("/enroll", response_model=EnrollResult)
async def enroll(
    person_id: str = Form(...),
    person_name: str = Form(...),
    replace_existing: bool = Form(False),
    files: list[UploadFile] = File(...),
    service: IdentityService = Depends(get_identity_service),
) -> EnrollResult:
    settings = get_settings()
    if not 1 <= len(files) <= settings.identity_max_images:
        raise HTTPException(status_code=400, detail=f"upload 1-{settings.identity_max_images} face images")
    images = await _read_images(files)
    try:
        return service.enroll(person_id, person_name, images, replace_existing=replace_existing)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/match", response_model=MatchResult)
async def match(
    file: UploadFile = File(...),
    threshold: float | None = Form(None),
    service: IdentityService = Depends(get_identity_service),
) -> MatchResult:
    images = await _read_images([file])
    try:
        return service.match(images[0], threshold=threshold)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/list", response_model=list[IdentityProfile])
def list_identities(service: IdentityService = Depends(get_identity_service)) -> list[IdentityProfile]:
    return service.list_identities()


@router.delete("/{person_id}")
def delete_identity(
    person_id: str,
    service: IdentityService = Depends(get_identity_service),
) -> dict[str, str]:
    deleted = service.delete(person_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"identity not found: {person_id}")
    return {"person_id": person_id, "status": "deleted"}


async def _read_images(files: list[UploadFile]) -> list[bytes]:
    images: list[bytes] = []
    for item in files:
        if item.content_type and not item.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"invalid image content type: {item.filename}")
        images.append(await item.read())
    return images
