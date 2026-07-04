from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.db.session import check_db_connection

router = APIRouter(tags=["Observability"])


@router.get("/health")
async def health():
    """Liveness probe - process is up and serving requests."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness probe - dependent infra (DB) is reachable."""
    db_ok = await check_db_connection()
    status_ = "ok" if db_ok else "degraded"
    return {"status": status_, "checks": {"database": db_ok}}


@router.get("/version")
async def version():
    settings = get_settings()
    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
    }
