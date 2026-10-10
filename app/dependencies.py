"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from app.sources.base import TelemetrySource


def get_source(request: Request) -> TelemetrySource:
    """Return the telemetry source that create_app stored on the app."""
    return cast(TelemetrySource, request.app.state.source)
