"""Health check endpoint."""

from __future__ import annotations

import fastapi

router = fastapi.APIRouter(tags=["health"])


@router.get("/healthz", response_model=dict[str, str])
async def get_health() -> dict[str, str]:
    """A liveness answer with no source, version or configuration detail."""
    return {"status": "ok"}
