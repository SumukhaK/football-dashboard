"""The access page: GET /access and its HTMX partial.

The route owns no arithmetic. It resolves the window, asks the service for the
model, turns the two charts into plain data and renders a template; a source
read that fails becomes a banner, never a 500. The domain types it needs are
re-exported by the service module, so the router still imports services only.
"""

from __future__ import annotations

from typing import Annotated, Any

import fastapi
from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_access
from app.domain.models import TimeWindow
from app.domain.overview import Chart
from app.services.access import (
    WINDOW_HOURS,
    AccessModel,
    AccessService,
    SourceUnavailableError,
)
from app.services.labels import window_label
from app.templating import templates
from app.view_context import prepare_scope

router = fastapi.APIRouter(tags=["access"], dependencies=[Depends(prepare_scope)])

FULL_TEMPLATE = "access.html"
BODY_TEMPLATE = "partials/access_body.html"
UNSUPPORTED_WINDOW = 422


def _chart_data(model: AccessModel | None) -> dict[str, Any]:
    """The two charts as plain data for the template's JSON block."""
    if model is None:
        return {}
    return {
        "failed_sign_ins": _chart_json(model.failed_sign_ins),
        "rate_limit": _chart_json(model.rate_limit),
    }


def _chart_json(chart: Chart) -> dict[str, Any]:
    """One chart as labels and named series, ready for JSON."""
    return {
        "labels": list(chart.labels),
        "series": [
            {"name": series.name, "values": list(series.values)}
            for series in chart.series
        ],
    }


def _resolve_hours(service: AccessService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _build(
    service: AccessService, window: TimeWindow
) -> tuple[AccessModel | None, dict[str, str] | None]:
    """Build the model, turning a source failure into a banner."""
    try:
        return service.build(window), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _render(
    request: Request, service: AccessService, requested: int | None, partial: bool
) -> HTMLResponse:
    """Render the page for one window request."""
    hours = _resolve_hours(service, requested)
    model, error = _build(service, prepare_scope(request).window)
    context: dict[str, Any] = {
        "model": model,
        "error": error,
        "hours": hours,
        "window_hours": WINDOW_HOURS,
        "window_label": window_label(hours),
        "charts": _chart_data(model),
        "picker_path": "/partials/access",
        "page_path": "/access",
        "body_id": "access-body",
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/access", response_class=HTMLResponse)
def access_page(
    request: Request,
    service: Annotated[AccessService, Depends(get_access)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full access page."""
    return _render(request, service, hours, partial=False)


@router.get("/partials/access", response_class=HTMLResponse)
def access_body(
    request: Request,
    service: Annotated[AccessService, Depends(get_access)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the access body, for HTMX to swap in."""
    return _render(request, service, hours, partial=True)
