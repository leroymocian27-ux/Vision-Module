from __future__ import annotations

from fastapi import Request

from app.services.identity_service import IdentityService


def get_identity_service(request: Request) -> IdentityService:
    return request.app.state.identity_service
