from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import identity_api, status_api
from app.core.config import get_settings
from app.core.logger import configure_logging, get_logger
from app.services.identity_service import IdentityService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    identity_service = IdentityService(settings)
    app.state.identity_service = identity_service
    logger.info("identity_service_started port=%s", settings.port)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Identity Service", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(status_api.router)
    app.include_router(identity_api.router)
    return app


app = create_app()
