"""Health check endpoint."""

from __future__ import annotations

import fastapi

router = fastapi.APIRouter(tags=["health"])


@router.get("/healthz", response_model=dict[str, str])
async def get_health(request: fastapi.Request) -> dict[str, str]:
    """Return application health and the contract version."""
    return {
        "status": "ok",
        "contract_version": request.app.state.contract.version,
    }
