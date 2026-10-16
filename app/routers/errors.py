"""The errors page: GET /errors and its HTMX partial.

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

from app.dependencies import get_errors
from app.services.errors import (
    WINDOW_HOURS,
    ErrorsModel,
    ErrorsService,
    SourceUnavailableError,
)
from app.templating import templates

router = fastapi.APIRouter(tags=["errors"])

FULL_TEMPLATE = "errors.html"
BODY_TEMPLATE = "partials/errors_body.html"
UNSUPPORTED_WINDOW = 422


def _resolve_hours(service: ErrorsService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _build(
    service: ErrorsService, hours: int
) -> tuple[ErrorsModel | None, dict[str, str] | None]:
    """Build the model, turning a source failure into a banner."""
    try:
        return service.build_for_hours(hours), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _sparklines(model: ErrorsModel | None) -> list[dict[str, Any]]:
    """The handled-error sparklines as plain data for the template's JSON block."""
    if model is None:
        return []
    return [
        {
            "id": f"sparkline-{index}",
            "labels": list(row.sparkline.labels),
            "values": list(row.sparkline.values),
        }
        for index, row in enumerate(model.handled_errors)
    ]


def _render(
    request: Request, service: ErrorsService, requested: int | None, partial: bool
) -> HTMLResponse:
    """Render the page for one window request."""
    hours = _resolve_hours(service, requested)
    model, error = _build(service, hours)
    context: dict[str, Any] = {
        "model": model,
        "error": error,
        "hours": hours,
        "window_hours": WINDOW_HOURS,
        "sparklines": _sparklines(model),
        "picker_path": "/partials/errors",
        "page_path": "/errors",
        "body_id": "errors-body",
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/errors", response_class=HTMLResponse)
def errors_page(
    request: Request,
    service: Annotated[ErrorsService, Depends(get_errors)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full errors page."""
    return _render(request, service, hours, partial=False)


@router.get("/partials/errors", response_class=HTMLResponse)
def errors_body(
    request: Request,
    service: Annotated[ErrorsService, Depends(get_errors)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the errors body, for HTMX to swap in."""
    return _render(request, service, hours, partial=True)
