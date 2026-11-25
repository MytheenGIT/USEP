from __future__ import annotations

from contextlib import asynccontextmanager

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
        container.scheduler.start()
        yield
        container.scheduler.shutdown()
        await container.aclose()

    app = FastAPI(title="USEP Ingestion Layer", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


app = create_app()
