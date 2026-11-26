"""Shared FastAPI dependencies for every router: app-state lookups and API auth."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

from scheduler import IngestionScheduler
from sync_service import SyncService


def _from_state(request: Request, name: str) -> Any:
    """Read a value the app factory put on ``app.state``; 503 if it is missing or None.

    ``app.state`` is untyped, so a failed startup, a test app or a new
    entrypoint that forgot to set the value would otherwise surface as an
    ``AttributeError`` and an opaque 500.
    """
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service is not ready: '{name}' is not available.",
        )
    return value


def get_sync_service(request: Request) -> SyncService:
    return _from_state(request, "sync_service")


def get_scheduler(request: Request) -> IngestionScheduler:
    return _from_state(request, "scheduler")


def get_output_dir(request: Request) -> Path:
    return Path(_from_state(request, "output_dir"))


def require_auth(request: Request) -> None:
    """Require ``Authorization: Bearer <USEP_INGESTION_API_TOKEN>``.

    Fails closed: with no token configured every protected route answers 503
    until one is set, unless auth was switched off explicitly with
    ``USEP_INGESTION_AUTH_DISABLED=true`` (local development only).
    """
    if getattr(request.app.state, "auth_disabled", False):
        return
    expected = getattr(request.app.state, "api_token", "") or ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured.",
        )
    if not secrets.compare_digest(_bearer_token(request).encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""
