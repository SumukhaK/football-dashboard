"""The overview page: GET / and its HTMX partial.

The route owns no arithmetic. It resolves the window, asks the service for the
model and renders a template; a source read that fails becomes a banner, never a
500. The domain types it needs are re-exported by the service module, so the
router still imports services only.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

import fastapi
from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_overview
from app.services.overview import (
    WINDOW_HOURS,
    OverviewModel,
    OverviewService,
    SourceUnavailableError,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["overview"])

FULL_TEMPLATE = "overview.html"
BODY_TEMPLATE = "partials/overview_body.html"
UNSUPPORTED_WINDOW = 422


def _resolve_hours(service: OverviewService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _build(
    service: OverviewService, hours: int
) -> tuple[OverviewModel | None, dict[str, str] | None]:
    """Build the model, turning a source failure into a banner."""
    try:
        return service.build_for_hours(hours), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _chart_data(model: OverviewModel | None) -> dict[str, Any]:
    """The chart series as plain data for the template's JSON block."""
    if model is None:
        return {}
    return {"traffic": asdict(model.traffic), "latency": asdict(model.latency)}


def _render(
    request: Request, service: OverviewService, requested: int | None, partial: bool
) -> HTMLResponse:
    """Render the page for one window request."""
    hours = _resolve_hours(service, requested)
    model, error = _build(service, hours)
    context: dict[str, Any] = {
        "model": model,
        "error": error,
        "charts": _chart_data(model),
        "hours": hours,
        "window_hours": WINDOW_HOURS,
        "picker_path": "/partials/overview",
        "page_path": "/",
        "body_id": "overview-body",
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def overview_page(
    request: Request,
    service: Annotated[OverviewService, Depends(get_overview)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full overview page."""
    return _render(request, service, hours, partial=False)


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_body(
    request: Request,
    service: Annotated[OverviewService, Depends(get_overview)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the overview body, for HTMX to swap in."""
    return _render(request, service, hours, partial=True)
