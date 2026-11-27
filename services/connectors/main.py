from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
import truststore
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import api_router
from config import get_settings
from container import Container
from logging_setup import configure_logging


def create_app() -> FastAPI:
    truststore.inject_into_ssl()
    settings = get_settings()
    configure_logging(settings.log_level)
    container = Container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.sync_service = container.sync_service
        app.state.scheduler = container.scheduler
        app.state.output_dir = settings.output_dir
        try:
            await container.init_db()
        except Exception as exc:  # the service still runs; run bookkeeping just isn't persisted
            structlog.get_logger(__name__).warning("db.init_failed", error=str(exc))
        container.scheduler.start()
        yield
        container.scheduler.shutdown()
        await container.aclose()

    app = FastAPI(title="USEP Ingestion Layer", version="0.1.0", lifespan=lifespan)
    app.state.api_token = settings.api_token
    app.state.auth_disabled = settings.auth_disabled
    if settings.auth_disabled:
        structlog.get_logger(__name__).warning("auth.disabled")
    elif not settings.api_token:
        structlog.get_logger(__name__).warning("auth.token_not_configured", effect="/sync and /results return 503")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )
    app.include_router(api_router)
    return app


app = create_app()
