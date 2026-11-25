from fastapi import APIRouter

from api.routes.health import router as health_router
from api.routes.results import router as results_router
from api.routes.sync import router as sync_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(sync_router)
api_router.include_router(results_router)

__all__ = ["api_router"]
