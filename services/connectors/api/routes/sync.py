"""Manual-trigger sync endpoints. Scheduled syncs call the same SyncService."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_sync_service
from common.sync_models import SyncResponse
from sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


async def _run_source(source: str, sync_service: SyncService, include_documents: bool) -> SyncResponse:
    try:
        result = await sync_service.sync_source(source)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SyncResponse.from_result(result, include_documents=include_documents)


@router.post("/jira", response_model=SyncResponse)
async def sync_jira(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("jira", sync_service, include_documents)


@router.post("/gitlab", response_model=SyncResponse)
async def sync_gitlab(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("gitlab", sync_service, include_documents)


@router.post("/confluence", response_model=SyncResponse)
async def sync_confluence(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("confluence", sync_service, include_documents)


@router.post("/figma", response_model=SyncResponse)
async def sync_figma(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("figma", sync_service, include_documents)


@router.post("/all", response_model=list[SyncResponse])
async def sync_all(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> list[SyncResponse]:
    results = await sync_service.sync_all()
    return [SyncResponse.from_result(r, include_documents=include_documents) for r in results]
