"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import cast

from fastapi import Request
from starlette.exceptions import HTTPException

from app.domain.android_versions import android_version
from app.services.access import AccessService
from app.services.assistant import AssistantService
from app.services.crashes import CrashesService
from app.services.data_jobs import DataJobsService
from app.services.errors import ErrorsService
from app.services.invites import InviteService
from app.services.overview import OverviewService
from app.services.requests import RequestsService
from app.services.source_status import SourceStatusService
from app.sources.base import TelemetrySource
from app.sources.scoped import ReleaseSource
from app.view_context import prepare_scope


def get_source(request: Request) -> TelemetrySource:
    """Return the telemetry source that create_app stored on the app."""
    return cast(TelemetrySource, request.app.state.source)


def get_data(request: Request) -> DataJobsService:
    """Return the data and jobs service that create_app stored on the app."""
    scope = prepare_scope(request)
    if scope.release.kind != "all":
        return DataJobsService(
            ReleaseSource(get_source(request), scope.release),
            request.app.state.clock,
            request.app.state.config,
        )
    return cast(DataJobsService, request.app.state.data)


def get_access(request: Request) -> AccessService:
    """Return the access service that create_app stored on the app."""
    scope = prepare_scope(request)
    if scope.release.kind != "all":
        return AccessService(
            ReleaseSource(get_source(request), scope.release),
            request.app.state.clock,
            request.app.state.config,
        )
    return cast(AccessService, request.app.state.access)


def get_assistant(request: Request) -> AssistantService:
    """Return the assistant service that create_app stored on the app."""
    scope = prepare_scope(request)
    if scope.release.kind != "all":
        return AssistantService(
            ReleaseSource(get_source(request), scope.release),
            request.app.state.clock,
            request.app.state.config,
        )
    return cast(AssistantService, request.app.state.assistant)


def get_overview(request: Request) -> OverviewService:
    """Return the overview service that create_app stored on the app."""
    scope = prepare_scope(request)
    if scope.release.kind != "all":
        return OverviewService(
            ReleaseSource(get_source(request), scope.release),
            request.app.state.clock,
            request.app.state.config,
            request.app.state.contract.components,
        )
    return cast(OverviewService, request.app.state.overview)


def get_invites(request: Request) -> InviteService:
    """Return the invite service that create_app stored on the app."""
    return cast(InviteService, request.app.state.invites)


def get_errors(request: Request) -> ErrorsService:
    """Return the errors service that create_app stored on the app."""
    scope = prepare_scope(request)
    settings = request.app.state.config
    retained = scope.custom or scope.release.kind != "all" or settings.source != "gcp"
    return ErrorsService(
        ReleaseSource(get_source(request), scope.release, derive_errors=retained),
        request.app.state.clock,
        settings,
        retained_groups=retained,
    )


def get_requests(request: Request) -> RequestsService:
    """Return the requests service that create_app stored on the app."""
    scope = prepare_scope(request)
    if scope.explicit:
        source = get_source(request)
        return RequestsService(
            ReleaseSource(source, scope.release),
            request.app.state.clock,
            request.app.state.config,
            detail_source=source,
            window=scope.window,
            release=scope.release,
        )
    return cast(RequestsService, request.app.state.requests)


def get_crashes(request: Request) -> CrashesService:
    """Return the crashes service that create_app stored on the app."""
    try:
        if len(request.query_params.getlist("android_version")) > 1:
            raise ValueError("duplicate Android version")
        version = android_version(request.query_params.get("android_version"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if version is not None:
        return CrashesService(
            request.app.state.crash_source,
            request.app.state.clock,
            request.app.state.config.crash_app_package,
            version=version,
        )
    return cast(CrashesService, request.app.state.crashes)


def get_source_status(request: Request) -> SourceStatusService:
    """Return the source-page service that create_app stored on the app."""
    return cast(SourceStatusService, request.app.state.source_status)
