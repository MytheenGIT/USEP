from fastapi import APIRouter, Depends

from api.deps import require_auth
from api.routes.health import router as health_router
from api.routes.results import router as results_router
from api.routes.sync import router as sync_router

api_router = APIRouter()
# /health stays open for probes; every other router requires the bearer token.
api_router.include_router(health_router)
api_router.include_router(sync_router, dependencies=[Depends(require_auth)])
api_router.include_router(results_router, dependencies=[Depends(require_auth)])

__all__ = ["api_router"]
