"""The crashes page: GET /crashes, its HTMX partials and GET /crashes/{issue_id}.

Only mounted when crashes are enabled. The routes own no arithmetic: they
resolve the window and the type filter, ask the service for a model and render a
template; a source read that fails becomes a banner, never a 500.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlencode

import fastapi
from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_crashes
from app.services.crashes import (
    WINDOW_HOURS,
    CrashesService,
    SourceUnavailableError,
)
from app.services.labels import window_label
from app.templating import templates

router = fastapi.APIRouter(tags=["crashes"])

FULL_TEMPLATE = "crashes.html"
BODY_TEMPLATE = "partials/crashes_body.html"
PANEL_TEMPLATE = "partials/crash_panel.html"
DETAIL_TEMPLATE = "crash_detail.html"
BAD_FILTER = 422
UNKNOWN_ISSUE = 404


def _resolve_hours(service: CrashesService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=str(exc)) from exc


def _resolve_type(service: CrashesService, requested: str | None) -> str | None:
    """Resolve the crash type filter, turning one with no chip into a 422."""
    try:
        return service.resolve_type(requested)
    except ValueError as exc:
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=str(exc)) from exc


def _banner(exc: SourceUnavailableError) -> dict[str, str]:
    """The banner context for a failed read."""
    return {"kind": exc.kind, "detail": exc.detail}


def _base_context(
    service: CrashesService, hours: int, type_filter: str | None
) -> dict[str, Any]:
    """The context every crashes render shares.

    ``close_link`` is the list's own URL, built here rather than from a panel,
    so a panel that could not read its issue still offers the way back to it.
    """
    return {
        "model": None,
        "error": None,
        "detail": None,
        "panel_error": None,
        "open_id": None,
        "hours": hours,
        "type_filter": type_filter,
        "window_label": window_label(hours),
        "window_hours": WINDOW_HOURS,
        "picker_path": "/partials/crashes",
        "picker_query": f"&{urlencode({'type': type_filter})}" if type_filter else "",
        "page_path": "/crashes",
        "body_id": "crashes-body",
        "close_link": service.list_link(hours, type_filter),
        "back_link": service.list_link(hours),
    }


def _read_panel(
    service: CrashesService, context: dict[str, Any], issue_id: str, hours: int
) -> None:
    """Read one issue into the context as the open panel, banner on a failure."""
    context["open_id"] = issue_id
    try:
        context["detail"] = service.detail_for_hours(issue_id, hours)
    except SourceUnavailableError as exc:
        context["panel_error"] = _banner(exc)


def _render_list(
    request: Request,
    service: CrashesService,
    requested: int | None,
    requested_type: str | None,
    open_id: str | None,
    partial: bool,
) -> HTMLResponse:
    """Render the crashes list for one window and type request."""
    hours = _resolve_hours(service, requested)
    type_filter = _resolve_type(service, requested_type)
    context = _base_context(service, hours, type_filter)
    try:
        context["model"] = service.build_for_hours(hours, type_filter)
    except SourceUnavailableError as exc:
        context["error"] = _banner(exc)
    if open_id is not None:
        _read_panel(service, context, open_id, hours)
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/crashes", response_class=HTMLResponse)
def crashes_page(
    request: Request,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
    type_filter: Annotated[str | None, Query(alias="type")] = None,
    open_id: Annotated[str | None, Query(alias="open")] = None,
) -> HTMLResponse:
    """Render the full crashes page, opening one issue's panel when asked."""
    return _render_list(request, service, hours, type_filter, open_id, partial=False)


@router.get("/partials/crashes", response_class=HTMLResponse)
def crashes_body(
    request: Request,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
    type_filter: Annotated[str | None, Query(alias="type")] = None,
) -> HTMLResponse:
    """Render only the crashes body, for HTMX to swap in."""
    return _render_list(request, service, hours, type_filter, None, partial=True)


@router.get("/partials/crashes/{issue_id}/panel", response_class=HTMLResponse)
def crash_panel(
    request: Request,
    service: Annotated[CrashesService, Depends(get_crashes)],
    issue_id: str,
    hours: Annotated[int | None, Query()] = None,
    type_filter: Annotated[str | None, Query(alias="type")] = None,
) -> HTMLResponse:
    """Render one issue's panel, for the list to swap in beside it."""
    resolved = _resolve_hours(service, hours)
    context = _base_context(service, resolved, _resolve_type(service, type_filter))
    _read_panel(service, context, issue_id, resolved)
    if context["detail"] is None and context["panel_error"] is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_ISSUE, detail=f"No events for issue {issue_id}"
        )
    return templates.TemplateResponse(request, PANEL_TEMPLATE, context)


@router.get("/crashes/{issue_id}", response_class=HTMLResponse)
def crash_issue(
    request: Request,
    issue_id: str,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render one issue's recent events and the latest event's frames."""
    resolved = _resolve_hours(service, hours)
    context = _base_context(service, resolved, None)
    try:
        context["detail"] = service.detail_for_hours(issue_id, resolved)
    except SourceUnavailableError as exc:
        context["error"] = _banner(exc)
    if context["detail"] is None and context["error"] is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_ISSUE, detail=f"No events for issue {issue_id}"
        )
    return templates.TemplateResponse(request, DETAIL_TEMPLATE, context)
