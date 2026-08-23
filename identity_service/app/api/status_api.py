from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_identity_service
from app.identity.schemas import HealthStatus
from app.services.identity_service import IdentityService

router = APIRouter(tags=["status"])


@router.get("/healthz", response_model=HealthStatus)
def healthz(service: IdentityService = Depends(get_identity_service)) -> HealthStatus:
    return service.health()
