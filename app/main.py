"""Application factory and entry point.

create_app() builds the FastAPI application with static files, the health and
overview routers, the configured telemetry source and the overview service, plus
the invite and crashes pages when they are enabled, and the owner sign-in routes
when the console runs in Google mode.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import fastapi
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, contract
from app.auth.access_logs import configure_auth_access_logs
from app.domain.clock import Clock, system_clock
from app.domain.listen import ListenAddress
from app.middleware.auth import (
    AuthGuardMiddleware,
    apply_response_policy,
    response_nonce,
)
from app.middleware.loopback import DEMO_COMMAND, LoopbackOnlyMiddleware
from app.routers import (
    access,
    assistant,
    auth,
    crashes,
    data,
    errors,
    health,
    invites,
    overview,
    requests,
    selection,
)
from app.routers import (
    source as source_routes,
)
from app.services.access import AccessService
from app.services.assistant import AssistantService
from app.services.auth import IdentityProvider
from app.services.crashes import CrashesService
from app.services.data_jobs import DataJobsService
from app.services.errors import ErrorsService
from app.services.invites import InviteService
from app.services.overview import OverviewService
from app.services.requests import RequestsService
from app.services.source_status import SourceStatusService
from app.sources.factory import build_crash_source, build_source
from app.stores.firestore_invites import FirestoreInviteStore, firestore_client

logger = logging.getLogger("app")


@asynccontextmanager
async def _lifespan(app: fastapi.FastAPI) -> AsyncIterator[None]:
    """Refuse to serve a console whose owner sign-in is not configured.

    The check runs when the ASGI server starts rather than when this module is
    imported, so tests and tooling can build the app without credentials while
    a hosted revision exits instead of serving behind no login.
    """
    settings: config.Config = app.state.config
    settings.require_google_auth()
    if settings.auth_mode == "fixture":
        _require_loopback_bind(app.state.listen)
    yield


def _require_loopback_bind(listen: ListenAddress | None) -> None:
    """Refuse to start the fixture demonstration on an unknown or open bind.

    Only the demo launcher knows the socket it bound; ``uvicorn app.main:app``
    does not tell the application, so that path is refused rather than trusted.
    """
    if listen is None or not listen.loopback:
        where = "an unknown address" if listen is None else listen.host
        raise ValueError(
            f"auth_mode=fixture serves this computer only, not {where}: "
            f"start it with {DEMO_COMMAND}"
        )


def create_app(
    settings: config.Config | None = None,
    clock: Clock = system_clock,
    provider: IdentityProvider | None = None,
    listen: ListenAddress | None = None,
) -> fastapi.FastAPI:
    """Build the app; ``listen`` is the fixture launcher's loopback bind."""
    settings = settings or config.get_config()
    if settings.auth_mode == "google":
        configure_auth_access_logs()
    _log_read_target(settings)
    # The console is not a public API: its schema and interactive docs are
    # never served. Any framework-created path stays behind the same guard.
    app = fastapi.FastAPI(
        title="Football Dashboard Console",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    _install_boundary(app, settings, clock, listen)

    # Load contract once at startup and store in app.state
    app.state.contract = contract.load_contract()
    app.state.config = settings
    app.state.clock = clock
    app.state.auth_provider = provider
    app.state.listen = listen
    app.state.source = build_source(settings, app.state.contract, clock)
    _build_services(app, settings, clock)

    _install_error_handlers(app)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    _include_routers(app, settings, clock)
    return app


def _install_boundary(
    app: fastapi.FastAPI,
    settings: config.Config,
    clock: Clock,
    listen: ListenAddress | None,
) -> None:
    """The owner sign-in guard, or the fixture demonstration's loopback boundary."""
    if settings.auth_mode == "google":
        app.add_middleware(AuthGuardMiddleware, settings=settings, clock=clock)
    else:
        app.add_middleware(LoopbackOnlyMiddleware, listen=listen)


def _log_read_target(settings: config.Config) -> None:
    """Log one line saying which telemetry this console reads.

    No Google call happens here: a cold start must stay fast, so the readers are
    built on the first query, not at startup.
    """
    _ensure_app_handler()
    if settings.source == "gcp":
        logger.info(
            "reading telemetry from project %s, Cloud Run service %s",
            settings.gcp_project_id,
            settings.api_service_name,
        )
    elif settings.source == "local":
        logger.info("reading telemetry from the log file %s", settings.local_log_path)
    else:
        logger.info(
            "reading telemetry from the sample files in %s", settings.fixture_dir
        )


def _ensure_app_handler() -> None:
    """Give this logger its own handler; uvicorn leaves the root logger alone."""
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _build_services(
    app: fastapi.FastAPI, settings: config.Config, clock: Clock
) -> None:
    """Put the page services on app.state, each reading through the source."""
    source = app.state.source
    app.state.overview = OverviewService(
        source, clock, settings, app.state.contract.components
    )
    app.state.errors = ErrorsService(source, clock, settings)
    app.state.requests = RequestsService(source, clock, settings)
    app.state.assistant = AssistantService(source, clock, settings)
    app.state.data = DataJobsService(source, clock, settings)
    app.state.access = AccessService(source, clock, settings)
    app.state.source_status = SourceStatusService(source, settings)


def _include_routers(
    app: fastapi.FastAPI, settings: config.Config, clock: Clock
) -> None:
    """Include the page routers, and the opt-in invite and crashes pages."""
    app.include_router(health.router)
    if settings.auth_mode == "google":
        app.include_router(auth.router)
    app.include_router(overview.router)
    app.include_router(selection.router)
    app.include_router(errors.router)
    app.include_router(requests.router)
    app.include_router(assistant.router)
    app.include_router(data.router)
    app.include_router(access.router)
    app.include_router(source_routes.router)
    if settings.invites_enabled:
        app.state.invites = _build_invites(settings, clock)
        app.include_router(invites.router)
    crash_source = build_crash_source(settings, clock)
    if crash_source is not None:
        app.state.crash_source = crash_source
        app.state.crashes = CrashesService(
            crash_source, clock, settings.crash_app_package
        )
        app.include_router(crashes.router)


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

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> PlainTextResponse:
        """A generic 500 that still carries the response security policy.

        Starlette's ServerErrorMiddleware sits outside application middleware,
        so this handler is the outer boundary for unexpected exceptions. It
        never echoes the exception, a parameter or private data.
        """
        settings: config.Config = request.app.state.config
        response = PlainTextResponse("Internal Server Error", status_code=500)
        apply_response_policy(
            response.headers,
            path=str(request.scope.get("path", "/")),
            status_code=500,
            nonce=response_nonce(request.scope),
            hosted=(settings.auth_public_origin or "").startswith("https://"),
        )
        return response


app = create_app()
