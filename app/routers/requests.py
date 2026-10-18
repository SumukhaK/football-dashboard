"""The requests list, its appended rows, its side panel and the detail.

The list route parses the filters, asks the service for one page and renders it;
the appended-rows route returns only rows for the "load more" button; the panel
route returns one request's panel for the list to swap in; the detail route
validates the id and renders the timeline and the trace waterfall. A request id
typed into the search box goes straight to its detail page. No arithmetic lives
here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from urllib.parse import quote

import fastapi
from fastapi import Depends, Path, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_requests
from app.domain.models import REQUEST_ID_PATTERN
from app.services.labels import window_label
from app.services.requests import (
    WINDOW_HOURS,
    InvalidFilter,
    RequestFilters,
    RequestPage,
    RequestPanel,
    RequestsService,
    SourceUnavailableError,
    clean_text,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["requests"])

FULL_TEMPLATE = "requests.html"
BODY_TEMPLATE = "partials/requests_body.html"
ROWS_TEMPLATE = "partials/request_rows_and_more.html"
PANEL_TEMPLATE = "partials/request_panel.html"
DETAIL_TEMPLATE = "request_detail.html"

BAD_FILTER = 422
UNKNOWN_REQUEST = 404


def _page(
    service: RequestsService, filters: RequestFilters
) -> tuple[RequestPage | None, dict[str, str] | None]:
    """Search one page, turning a source failure into a banner."""
    try:
        return service.search(filters), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _panel(
    service: RequestsService, request_id: str | None, filters: RequestFilters
) -> tuple[RequestPanel | None, dict[str, str] | None]:
    """Read one open panel, turning a source failure into a banner."""
    if request_id is None:
        return None, None
    try:
        return service.panel(request_id, filters), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _render_context(
    service: RequestsService,
    filters: RequestFilters,
    page: RequestPage | None,
    error: dict[str, str] | None,
    field_errors: dict[str, str] | None = None,
    open_id: str | None = None,
) -> dict[str, Any]:
    """The shared context, holding everything the templates interpolate."""
    panel, panel_error = _panel(service, open_id, filters)
    return {
        "page": page,
        "error": error,
        "filters": filters,
        "field_errors": field_errors or {},
        "chips": service.chips(filters),
        "clear_link": service.clear_link(filters),
        "panel": panel,
        "panel_error": panel_error,
        "open_id": open_id,
        "hours": filters.hours,
        "window_hours": WINDOW_HOURS,
        "window_label": window_label(filters.hours),
        "picker_path": "/partials/requests",
        "page_path": "/requests",
        "body_id": "requests-body",
    }


def _context(
    service: RequestsService,
    hours: int | None,
    route: str | None,
    status: str | None,
    event: str | None,
    component: str | None,
    before: datetime | None,
    before_id: str | None,
    open_id: str | None = None,
    field_errors: bool = False,
) -> dict[str, Any]:
    """The template context shared by the page, the body and the rows.

    A filter the page cannot parse is a 422, except when ``field_errors`` is set:
    the HTMX page route then redraws the form with the message under the box that
    failed, because HTMX does not swap an error reply.
    """
    try:
        filters = service.filters(
            hours, route, status, event, component, before, before_id
        )
    except InvalidFilter as exc:
        if not field_errors:
            raise StarletteHTTPException(
                status_code=BAD_FILTER, detail=str(exc)
            ) from exc
        return _render_context(service, exc.filters, None, None, {exc.field: str(exc)})
    except ValueError as exc:
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=str(exc)) from exc
    page, error = _page(service, filters)
    return _render_context(service, filters, page, error, open_id=open_id)


def _as_request_id(value: str | None) -> str | None:
    """A filter value read as a request id, or None when it is not one."""
    cleaned = clean_text(value)
    if cleaned is not None and REQUEST_ID_PATTERN.fullmatch(cleaned):
        return cleaned
    return None


def _validated_open(value: str | None) -> str | None:
    """The id whose panel the page should open, or a 422 when it is malformed."""
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    if not REQUEST_ID_PATTERN.fullmatch(cleaned):
        raise StarletteHTTPException(
            status_code=BAD_FILTER, detail=f"Not a valid request ID: {cleaned!r}"
        )
    return cleaned


@router.get("/requests", response_class=HTMLResponse)
def requests_page(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    hours: Annotated[int | None, Query()] = None,
    route: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    event: Annotated[str | None, Query()] = None,
    component: Annotated[str | None, Query()] = None,
    request_id: Annotated[str | None, Query()] = None,
    open_id: Annotated[str | None, Query(alias="open")] = None,
    before: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[str | None, Query()] = None,
) -> Response:
    """Render the full requests page, or open a typed id's detail or panel.

    The search box holds either a route filter or a pasted request id, so a value
    of the id's shape jumps to the detail page; ``open`` instead opens the side
    panel for a list that stays put.
    """
    for candidate in (route, request_id):
        typed = _as_request_id(candidate)
        if typed is not None:
            return _redirect_to_detail(request, typed)
    context = _context(
        service,
        hours,
        route,
        status,
        event,
        component,
        before,
        before_id,
        open_id=_validated_open(open_id),
        field_errors=bool(request.headers.get("HX-Request")),
    )
    typed_request_id = clean_text(request_id)
    if typed_request_id is not None:
        return _invalid_request_id(request, typed_request_id, context)
    return templates.TemplateResponse(request, FULL_TEMPLATE, context)


def _invalid_request_id(
    request: Request, request_id: str, context: dict[str, Any]
) -> Response:
    """Report a malformed typed id where the browser will show it.

    HTMX does not swap a 422 body, so the message belongs under the field
    instead: the body is re-rendered for an HTMX request, while a plain request
    still gets the structured 422.
    """
    message = f"Not a valid request ID: {request_id!r}"
    if not request.headers.get("HX-Request"):
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=message)
    context["field_errors"] = {"request_id": message}
    return templates.TemplateResponse(request, BODY_TEMPLATE, context)


def _redirect_to_detail(request: Request, request_id: str) -> Response:
    """Send a typed request id to its detail page.

    HTMX swaps the reply into the page, so a plain redirect would leave the
    browser on the list with nothing to show; an ``HX-Redirect`` header makes it
    navigate instead.
    """
    location = f"/requests/{quote(request_id, safe='')}"
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=303)


@router.get("/partials/requests", response_class=HTMLResponse)
def requests_body(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    hours: Annotated[int | None, Query()] = None,
    route: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    event: Annotated[str | None, Query()] = None,
    component: Annotated[str | None, Query()] = None,
    before: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Render only the requests body, for HTMX to swap in."""
    context = _context(
        service, hours, route, status, event, component, before, before_id
    )
    return templates.TemplateResponse(request, BODY_TEMPLATE, context)


@router.get("/partials/request_rows", response_class=HTMLResponse)
def request_rows(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    hours: Annotated[int | None, Query()] = None,
    route: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    event: Annotated[str | None, Query()] = None,
    component: Annotated[str | None, Query()] = None,
    before: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Render one page of rows to append, plus the next "load more" button."""
    context = _context(
        service, hours, route, status, event, component, before, before_id
    )
    return templates.TemplateResponse(request, ROWS_TEMPLATE, context)


def _filters_for_links(
    service: RequestsService,
    hours: int | None,
    route: str | None,
    status: str | None,
    event: str | None,
    component: str | None,
) -> RequestFilters:
    """The list filters a panel link carries, for its close link.

    The panel only needs them to build the link back to the list, so a filter the
    page cannot parse falls back to what it can read rather than a 422: the
    request itself is still worth showing.
    """
    try:
        return service.filters(hours, route, status, event, component, None, None)
    except InvalidFilter as exc:
        return exc.filters
    except ValueError:
        return service.filters(None, None, None, None, None, None, None)


@router.get("/partials/requests/{request_id}/panel", response_class=HTMLResponse)
def request_panel(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    request_id: Annotated[str, Path(pattern=REQUEST_ID_PATTERN.pattern)],
    hours: Annotated[int | None, Query()] = None,
    route: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    event: Annotated[str | None, Query()] = None,
    component: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Render one request's panel, for the list to swap in beside it."""
    filters = _filters_for_links(service, hours, route, status, event, component)
    panel, error = _panel(service, request_id, filters)
    if panel is None and error is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_REQUEST, detail=f"unknown request: {request_id}"
        )
    return templates.TemplateResponse(
        request, PANEL_TEMPLATE, {"panel": panel, "panel_error": error}
    )


@router.get("/requests/{request_id}", response_class=HTMLResponse)
def request_detail(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    request_id: Annotated[str, Path(pattern=REQUEST_ID_PATTERN.pattern)],
) -> HTMLResponse:
    """Render one request's timeline and trace waterfall."""
    try:
        detail = service.detail(request_id)
    except SourceUnavailableError as exc:
        error = {"kind": exc.kind, "detail": exc.detail}
        return templates.TemplateResponse(
            request, DETAIL_TEMPLATE, {"detail": None, "error": error}
        )
    if detail is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_REQUEST, detail=f"unknown request: {request_id}"
        )
    return templates.TemplateResponse(request, DETAIL_TEMPLATE, {"detail": detail})
