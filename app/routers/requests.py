"""The requests list, its appended rows and the request detail.

The list route parses the filters, asks the service for one page and renders it;
the appended-rows route returns only rows for the "load more" button; the detail
route validates the id and renders the timeline and the trace waterfall. A
request id typed into the search box goes straight to its detail page. No
arithmetic lives here.
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
    EVENT_OPTIONS,
    STATUS_OPTIONS,
    WINDOW_HOURS,
    InvalidFilter,
    RequestFilters,
    RequestPage,
    RequestsService,
    SourceUnavailableError,
    clean_text,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["requests"])

FULL_TEMPLATE = "requests.html"
BODY_TEMPLATE = "partials/requests_body.html"
ROWS_TEMPLATE = "partials/request_rows_and_more.html"
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


def _render_context(
    filters: RequestFilters,
    page: RequestPage | None,
    error: dict[str, str] | None,
    field_errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The shared context, holding everything the templates interpolate."""
    return {
        "page": page,
        "error": error,
        "filters": filters,
        "field_errors": field_errors or {},
        "hours_options": WINDOW_HOURS,
        "window_label": window_label(filters.hours),
        "event_options": EVENT_OPTIONS,
        "status_options": STATUS_OPTIONS,
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
        return _render_context(exc.filters, None, None, {exc.field: str(exc)})
    except ValueError as exc:
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=str(exc)) from exc
    page, error = _page(service, filters)
    return _render_context(filters, page, error)


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
    before: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[str | None, Query()] = None,
) -> Response:
    """Render the full requests page, or jump to a typed request's detail."""
    target = clean_text(request_id)
    if target is not None and REQUEST_ID_PATTERN.fullmatch(target):
        return _redirect_to_detail(request, target)
    context = _context(
        service,
        hours,
        route,
        status,
        event,
        component,
        before,
        before_id,
        field_errors=bool(request.headers.get("HX-Request")),
    )
    if target is not None:
        return _invalid_request_id(request, target, context)
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
