from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api.routes import api_router
from config import APP_VERSION, get_settings
from console_api.auth import LoginThrottle, SessionStore
from console_api.errors import ConsoleError, console_error_handler
from console_api.processor import ConfigProcessor
from console_api.routes import router as console_router
from console_api.secrets_store import SecretStore
from console_api.store import ConfigurationStore
from container import Container
from logging_setup import configure_logging
from usep.ingestion.ports.audit import AuditEvent


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    container = Container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.sync_service = container.sync_service
        app.state.scheduler = container.scheduler
        app.state.output_dir = settings.output_dir
        app.state.source_overview = container.source_overview
        # The admin console (the UI's API): sessions, configurations, and the processor that runs them.
        app.state.settings = settings
        app.state.sessions = SessionStore(settings.session_ttl_hours * 3600)
        app.state.throttle = LoginThrottle()
        app.state.audit = container.console_audit
        app.state.store = ConfigurationStore(settings.output_dir)
        app.state.store.mark_interrupted()
        app.state.secrets = SecretStore()
        app.state.runtime_for = container.runtime_for
        app.state.processor = ConfigProcessor(
            settings, app.state.store, app.state.audit, app.state.secrets, container.new_sync_service, container.runtime_for
        )
        app.state.background_tasks = set()
        await container.check_object_store()  # fail fast: nothing is fetched if it could not be stored
        await container.init_db()  # cursors, data keys and the audit trail live here: no database, no start
        await container.sync_service.refresh_scopes()  # e.g. every GitLab repository the token's user is a member of
        container.scheduler.start()
        await app.state.audit.record(AuditEvent(
            source="service", action="service.start", status="success", at=datetime.now(UTC),
            details={"version": APP_VERSION, "sources": container.source_overview() if callable(container.source_overview) else None,
                     "raw_store": settings.raw_store, "audit_store": settings.audit_store},
        ))
        yield
        await app.state.audit.record(AuditEvent(source="service", action="service.stop", status="success", at=datetime.now(UTC)))
        container.scheduler.shutdown()
        await container.aclose()

    app = FastAPI(title="USEP Ingestion Layer", version=APP_VERSION, lifespan=lifespan)
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

    @app.middleware("http")
    async def audit_requests(request: Request, call_next):
        """Every call to the service leaves an audit event: who (the signed-in admin or the API client), what, the
        result and how long. Bodies and query strings are never recorded, so no token or key can end up in the trail."""
        if request.method == "OPTIONS" or request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)
        request.state.request_id = uuid.uuid4().hex
        started = time.monotonic()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request.state.request_id
            return response
        finally:
            route = request.scope.get("route")
            actor = getattr(request.state, "actor", None) or ("api-client" if request.headers.get("authorization") else "anonymous")
            try:
                await request.app.state.audit.record(AuditEvent(
                    source="api", action="http.request", status="success" if status < 400 else "denied" if status in (401, 403) else "failed",
                    at=datetime.now(UTC),
                    details={
                        "actor": actor, "request_id": request.state.request_id, "method": request.method,
                        "path": getattr(route, "path", request.url.path)[:200], "status_code": status,
                        "duration_ms": round((time.monotonic() - started) * 1000),
                        "client_ip": request.client.host if request.client else None,
                    },
                ))
            except Exception as exc:  # noqa: BLE001 -- an audit store problem is logged; it must not break the request
                structlog.get_logger(__name__).warning("api.audit_failed", error=type(exc).__name__)

    app.add_exception_handler(ConsoleError, console_error_handler)
    app.include_router(api_router)
    app.include_router(console_router)
    return app


app = create_app()
