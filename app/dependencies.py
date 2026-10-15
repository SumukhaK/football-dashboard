"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from app.services.overview import OverviewService
from app.sources.base import TelemetrySource


def get_source(request: Request) -> TelemetrySource:
    """Return the telemetry source that create_app stored on the app."""
    return cast(TelemetrySource, request.app.state.source)


def get_overview(request: Request) -> OverviewService:
    """Return the overview service that create_app stored on the app."""
    return cast(OverviewService, request.app.state.overview)
