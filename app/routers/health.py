"""Health check endpoint."""

from __future__ import annotations

import fastapi

from app import config

router = fastapi.APIRouter(tags=["health"])


@router.get("/healthz", response_model=dict[str, str])
async def get_health() -> dict[str, str]:
    """Return application health and the contract version."""
    settings = config.get_config()
    return {
        "status": "ok",
        "contract_version": settings.contract_version,
    }
