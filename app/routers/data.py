"""The data and jobs page: GET /data and its HTMX partial.

The route owns no arithmetic. It resolves the window, asks the service for the
model and renders a template; a source read that fails becomes a banner, never a
500. The domain types it needs are re-exported by the service module, so the
router still imports services only.
"""

from __future__ import annotations

from typing import Annotated, Any

import fastapi
from fastapi import Depends, Query, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.dependencies import get_data
from app.services.data_jobs import (
    WINDOW_HOURS,
    DataJobsModel,
    DataJobsService,
    SourceUnavailableError,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["data"])

FULL_TEMPLATE = "data.html"
BODY_TEMPLATE = "partials/data_body.html"
UNSUPPORTED_WINDOW = 422


def _resolve_hours(service: DataJobsService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _build(
    service: DataJobsService, hours: int
) -> tuple[DataJobsModel | None, dict[str, str] | None]:
    """Build the model, turning a source failure into a banner."""
    try:
        return service.build_for_hours(hours), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _render(
    request: Request, service: DataJobsService, requested: int | None, partial: bool
) -> HTMLResponse:
    """Render the page for one window request."""
    hours = _resolve_hours(service, requested)
    model, error = _build(service, hours)
    context: dict[str, Any] = {
        "model": model,
        "error": error,
        "hours": hours,
        "window_hours": WINDOW_HOURS,
        "picker_path": "/partials/data",
        "page_path": "/data",
        "body_id": "data-body",
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/data", response_class=HTMLResponse)
def data_page(
    request: Request,
    service: Annotated[DataJobsService, Depends(get_data)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full data and jobs page."""
    return _render(request, service, hours, partial=False)


@router.get("/partials/data", response_class=HTMLResponse)
def data_body(
    request: Request,
    service: Annotated[DataJobsService, Depends(get_data)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the data and jobs body, for HTMX to swap in."""
    return _render(request, service, hours, partial=True)
