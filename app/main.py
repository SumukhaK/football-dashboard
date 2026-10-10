"""Application factory and entry point.

create_app() builds the FastAPI application with static files, the health
router and the configured telemetry source.
"""

from __future__ import annotations

from pathlib import Path

import fastapi
from fastapi.staticfiles import StaticFiles

from app import config, contract
from app.domain.clock import Clock, system_clock
from app.routers import health
from app.sources.factory import build_source


def create_app(
    settings: config.Config | None = None, clock: Clock = system_clock
) -> fastapi.FastAPI:
    """Build and configure the FastAPI application."""
    settings = settings or config.get_config()
    app = fastapi.FastAPI(title="Football Dashboard Console")

    # Load contract once at startup and store in app.state
    app.state.contract = contract.load_contract()
    app.state.config = settings
    app.state.source = build_source(settings, app.state.contract, clock)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Include routers
    app.include_router(health.router)

    return app


app = create_app()
