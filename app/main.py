"""Application factory and entry point.

create_app() builds the FastAPI application with static files, the health and
overview routers, the configured telemetry source and the overview service, plus
the invite page when it is enabled.
"""

from __future__ import annotations

from pathlib import Path

import fastapi
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, contract
from app.domain.clock import Clock, system_clock
from app.routers import health, invites, overview
from app.services.invites import InviteService
from app.services.overview import OverviewService
from app.sources.factory import build_source
from app.stores.firestore_invites import FirestoreInviteStore, firestore_client


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
    app.state.overview = OverviewService(
        app.state.source, clock, settings, app.state.contract.components
    )

    _install_error_handlers(app)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Include routers
    app.include_router(health.router)
    app.include_router(overview.router)
    if settings.invites_enabled:
        app.state.invites = _build_invites(settings, clock)
        app.include_router(invites.router)

    return app


def _build_invites(settings: config.Config, clock: Clock) -> InviteService:
    """The invite service over Firestore; the client is built on first use."""
    store = FirestoreInviteStore(
        lambda: firestore_client(settings.gcp_project_id),
        settings.invite_collection_prefix,
    )
    return InviteService(store, clock, settings.invite_lifetime_days)


def _install_error_handlers(app: fastapi.FastAPI) -> None:
    """Return every error as ``{"error": ..., "detail": ...}``."""

    @app.exception_handler(RequestValidationError)
    async def _validation(
        request: fastapi.Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Shape request-validation errors like every other error."""
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": jsonable_encoder(exc.errors()),
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(
        request: fastapi.Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Shape HTTP errors like every other error."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "detail": exc.detail},
        )


app = create_app()
