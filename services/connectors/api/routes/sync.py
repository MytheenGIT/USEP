"""Manual-trigger sync endpoints, one per registered source plus /sync/all. Scheduled syncs call the same SyncService."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.deps import get_sync_service
from common.sync_models import SyncResponse
from registry import SOURCES
from sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


async def _run_source(
    source: str, sync_service: SyncService, include_documents: bool, scope: list[str] | None = None
) -> SyncResponse:
    try:
        result = await sync_service.sync_source(source, scopes=scope or None)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SyncResponse.from_result(result, include_documents=include_documents)


def _add_route(source: str) -> None:
    async def sync_one(
        include_documents: bool = Query(True),
        scope: list[str] | None = Query(None, description="Limit the run to these configured scopes."),
        sync_service: SyncService = Depends(get_sync_service),
    ) -> SyncResponse:
        return await _run_source(source, sync_service, include_documents, scope)

    sync_one.__name__ = f"sync_{source}"
    router.add_api_route(f"/{source}", sync_one, methods=["POST"], response_model=SyncResponse)


for _source in SOURCES:
    _add_route(_source)


@router.post("/github", response_model=SyncResponse)
async def sync_github(
    include_documents: bool = Query(True),
    scope: list[str] | None = Query(None, description="Limit the run to these configured scopes."),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("github", sync_service, include_documents, scope)


@router.post("/servicenow", response_model=SyncResponse)
async def sync_servicenow(
    include_documents: bool = Query(True),
    scope: list[str] | None = Query(None, description="Limit the run to these configured scopes."),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("servicenow", sync_service, include_documents, scope)


@router.post("/github", response_model=SyncResponse)
async def sync_github(
    include_documents: bool = Query(True),
    scope: list[str] | None = Query(None, description="Limit the run to these configured scopes."),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("github", sync_service, include_documents, scope)


@router.post("/servicenow", response_model=SyncResponse)
async def sync_servicenow(
    include_documents: bool = Query(True),
    scope: list[str] | None = Query(None, description="Limit the run to these configured scopes."),
    sync_service: SyncService = Depends(get_sync_service),
) -> SyncResponse:
    return await _run_source("servicenow", sync_service, include_documents, scope)


@router.get("/{source}/scopes", response_model=list[str])
async def list_scopes(source: str, sync_service: SyncService = Depends(get_sync_service)) -> list[str]:
    try:
        return sync_service.scopes(source)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/all", response_model=list[SyncResponse])
async def sync_all(
    include_documents: bool = Query(True),
    sync_service: SyncService = Depends(get_sync_service),
) -> list[SyncResponse]:
    results = await sync_service.sync_all()
    return [SyncResponse.from_result(r, include_documents=include_documents) for r in results]
