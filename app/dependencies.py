"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from typing import cast

from fastapi import Request

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


def get_source(request: Request) -> TelemetrySource:
    """Return the telemetry source that create_app stored on the app."""
    return cast(TelemetrySource, request.app.state.source)


def get_data(request: Request) -> DataJobsService:
    """Return the data and jobs service that create_app stored on the app."""
    return cast(DataJobsService, request.app.state.data)


def get_access(request: Request) -> AccessService:
    """Return the access service that create_app stored on the app."""
    return cast(AccessService, request.app.state.access)


def get_assistant(request: Request) -> AssistantService:
    """Return the assistant service that create_app stored on the app."""
    return cast(AssistantService, request.app.state.assistant)


def get_overview(request: Request) -> OverviewService:
    """Return the overview service that create_app stored on the app."""
    return cast(OverviewService, request.app.state.overview)


def get_invites(request: Request) -> InviteService:
    """Return the invite service that create_app stored on the app."""
    return cast(InviteService, request.app.state.invites)


def get_errors(request: Request) -> ErrorsService:
    """Return the errors service that create_app stored on the app."""
    return cast(ErrorsService, request.app.state.errors)


def get_requests(request: Request) -> RequestsService:
    """Return the requests service that create_app stored on the app."""
    return cast(RequestsService, request.app.state.requests)


def get_crashes(request: Request) -> CrashesService:
    """Return the crashes service that create_app stored on the app."""
    return cast(CrashesService, request.app.state.crashes)


def get_source_status(request: Request) -> SourceStatusService:
    """Return the source-page service that create_app stored on the app."""
    return cast(SourceStatusService, request.app.state.source_status)
