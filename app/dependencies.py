"""Dependency injection for telemetry source."""

from __future__ import annotations

from fastapi import Depends, Request

from app.sources.base import TelemetrySource


def get_source(request: Request) -> TelemetrySource:
    """Return the telemetry source stored in the app state.

    FastAPI routers can depend on this to get the source that was
    initialised by ``create_app``.
    """
    return request.app.state.source