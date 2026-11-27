"""Which sources the admin selected, what they will read, and whether that really works.

``GET /sources`` shows every source: selected or not, running, its scopes (project keys as JQL, space keys,
repositories, files) and why it is not running. Nothing secret is returned. ``POST /sources/{source}/check``
asks the source itself, with read-only calls, whether the saved credentials and every scope can be used, so a
wrong space key or an unknown project shows up here and not as an empty run.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import get_source_overview, get_sync_service
from common.connector_base import SourceCheck
from sync_service import SyncService

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceInfo(BaseModel):
    source: str
    enabled: bool
    running: bool
    scopes: list[str]
    blocked_reason: str | None = None


@router.get("", response_model=list[SourceInfo])
def list_sources(overview: Any = Depends(get_source_overview)) -> list[SourceInfo]:
    return [SourceInfo(**row) for row in overview()]


@router.post("/{source}/check", response_model=SourceCheck)
async def check_source(source: str, sync_service: SyncService = Depends(get_sync_service)) -> SourceCheck:
    try:
        return await sync_service.check_source(source)
    except ValueError as exc:  # not selected, so there is nothing to check
        raise HTTPException(status_code=404, detail=f"{source} is not selected") from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
