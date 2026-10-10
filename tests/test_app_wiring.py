"""Tests that create_app wires the telemetry source."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_source
from app.main import create_app
from app.sources.base import TelemetrySource


def test_create_app_stores_a_source() -> None:
    """create_app puts a source on app.state and get_source returns it."""
    app = create_app(Config(), clock=lambda: datetime(2026, 10, 10, tzinfo=UTC))
    seen: list[TelemetrySource] = []

    @app.get("/_source_probe")
    def probe(
        source: Annotated[TelemetrySource, Depends(get_source)],
    ) -> dict[str, str]:
        seen.append(source)
        return {"ok": "yes"}

    response = TestClient(app).get("/_source_probe")
    assert response.status_code == 200
    assert seen == [app.state.source]


def test_app_is_a_fastapi_app() -> None:
    """The module-level app builds with default settings."""
    assert isinstance(create_app(Config()), FastAPI)
