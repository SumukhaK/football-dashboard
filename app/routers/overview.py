"""The overview page: GET / and its HTMX partial.

The route owns no arithmetic. It checks the window, asks the service for the
model and renders a template; a source read that fails becomes a banner, never
a 500.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

import fastapi
from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_overview
from app.domain.errors import SourceUnavailableError
from app.domain.overview import OverviewModel
from app.services.overview import (
    DEFAULT_WINDOW_HOURS,
    WINDOW_HOURS,
    OverviewService,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["overview"])

FULL_TEMPLATE = "overview.html"
BODY_TEMPLATE = "partials/overview_body.html"


def _checked_hours(hours: int) -> int:
    """Return the window size, rejecting one the picker does not offer."""
    if hours not in WINDOW_HOURS:
        raise StarletteHTTPException(
            status_code=422, detail=f"unsupported window: {hours} hours"
        )
    return hours


def _chart_data(model: OverviewModel | None) -> dict[str, Any]:
    """The chart series as plain data for the template's JSON block."""
    if model is None:
        return {}
    return {"traffic": asdict(model.traffic), "latency": asdict(model.latency)}


def _render(
    request: Request, service: OverviewService, hours: int, partial: bool
) -> HTMLResponse:
    """Render the page, turning a source failure into a banner."""
    model: OverviewModel | None = None
    error: dict[str, str] | None = None
    try:
        model = service.build_for_hours(hours)
    except SourceUnavailableError as exc:
        error = {"kind": exc.kind, "detail": exc.detail}
    context: dict[str, Any] = {
        "model": model,
        "error": error,
        "charts": _chart_data(model),
        "hours": hours,
        "window_hours": WINDOW_HOURS,
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/", response_class=HTMLResponse)
def overview_page(
    request: Request,
    service: Annotated[OverviewService, Depends(get_overview)],
    hours: Annotated[int, Query()] = DEFAULT_WINDOW_HOURS,
) -> HTMLResponse:
    """Render the full overview page."""
    return _render(request, service, _checked_hours(hours), partial=False)


@router.get("/partials/overview", response_class=HTMLResponse)
def overview_body(
    request: Request,
    service: Annotated[OverviewService, Depends(get_overview)],
    hours: Annotated[int, Query()] = DEFAULT_WINDOW_HOURS,
) -> HTMLResponse:
    """Render only the overview body, for HTMX to swap in."""
    return _render(request, service, _checked_hours(hours), partial=True)
