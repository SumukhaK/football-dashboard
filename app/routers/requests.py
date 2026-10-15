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

import fastapi
from fastapi import Depends, Path, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_requests
from app.services.requests import (
    EVENT_OPTIONS,
    STATUS_OPTIONS,
    WINDOW_HOURS,
    RequestFilters,
    RequestPage,
    RequestsService,
    SourceUnavailableError,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["requests"])

FULL_TEMPLATE = "requests.html"
BODY_TEMPLATE = "partials/requests_body.html"
ROWS_TEMPLATE = "partials/request_rows_and_more.html"
DETAIL_TEMPLATE = "request_detail.html"

REQUEST_ID_PATTERN = r"^[A-Za-z0-9._-]{8,64}$"
BAD_FILTER = 422
UNKNOWN_REQUEST = 404


def _filters(
    service: RequestsService,
    hours: int | None,
    route: str | None,
    status: str | None,
    event: str | None,
    component: str | None,
    before: datetime | None,
) -> RequestFilters:
    """Parse every filter, turning a bad one into a 422."""
    try:
        return service.filters(hours, route, status, event, component, before)
    except ValueError as exc:
        raise StarletteHTTPException(status_code=BAD_FILTER, detail=str(exc)) from exc


def _page(
    service: RequestsService, filters: RequestFilters
) -> tuple[RequestPage | None, dict[str, str] | None]:
    """Search one page, turning a source failure into a banner."""
    try:
        return service.search(filters), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _context(
    service: RequestsService,
    hours: int | None,
    route: str | None,
    status: str | None,
    event: str | None,
    component: str | None,
    before: datetime | None,
) -> dict[str, Any]:
    """The template context shared by the page, the body and the rows."""
    filters = _filters(service, hours, route, status, event, component, before)
    page, error = _page(service, filters)
    return {
        "page": page,
        "error": error,
        "filters": filters,
        "hours_options": WINDOW_HOURS,
        "event_options": EVENT_OPTIONS,
        "status_options": STATUS_OPTIONS,
    }


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
) -> Response:
    """Render the full requests page, or jump to a typed request's detail."""
    if request_id:
        return RedirectResponse(f"/requests/{request_id}", status_code=307)
    context = _context(service, hours, route, status, event, component, before)
    return templates.TemplateResponse(request, FULL_TEMPLATE, context)


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
) -> HTMLResponse:
    """Render only the requests body, for HTMX to swap in."""
    context = _context(service, hours, route, status, event, component, before)
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
) -> HTMLResponse:
    """Render one page of rows to append, plus the next "load more" button."""
    context = _context(service, hours, route, status, event, component, before)
    return templates.TemplateResponse(request, ROWS_TEMPLATE, context)


@router.get("/requests/{request_id}", response_class=HTMLResponse)
def request_detail(
    request: Request,
    service: Annotated[RequestsService, Depends(get_requests)],
    request_id: Annotated[str, Path(pattern=REQUEST_ID_PATTERN)],
) -> HTMLResponse:
    """Render one request's timeline and trace waterfall."""
    detail = service.detail(request_id)
    if detail is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_REQUEST, detail=f"unknown request: {request_id}"
        )
    return templates.TemplateResponse(request, DETAIL_TEMPLATE, {"detail": detail})
