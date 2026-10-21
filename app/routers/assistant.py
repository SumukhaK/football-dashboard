"""The assistant page: GET /assistant and its HTMX partial.

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

from app.dependencies import get_assistant
from app.domain.models import TimeWindow
from app.services.assistant import (
    WINDOW_HOURS,
    AssistantModel,
    AssistantService,
    SourceUnavailableError,
)
from app.services.labels import window_label
from app.templating import templates
from app.view_context import prepare_scope

router = fastapi.APIRouter(tags=["assistant"], dependencies=[Depends(prepare_scope)])

FULL_TEMPLATE = "assistant.html"
BODY_TEMPLATE = "partials/assistant_body.html"
UNSUPPORTED_WINDOW = 422


def _resolve_hours(service: AssistantService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _build(
    service: AssistantService, window: TimeWindow
) -> tuple[AssistantModel | None, dict[str, str] | None]:
    """Build the model, turning a source failure into a banner."""
    try:
        return service.build(window), None
    except SourceUnavailableError as exc:
        return None, {"kind": exc.kind, "detail": exc.detail}


def _render(
    request: Request, service: AssistantService, requested: int | None, partial: bool
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
        "picker_path": "/partials/assistant",
        "page_path": "/assistant",
        "body_id": "assistant-body",
    }
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/assistant", response_class=HTMLResponse)
def assistant_page(
    request: Request,
    service: Annotated[AssistantService, Depends(get_assistant)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full assistant page."""
    return _render(request, service, hours, partial=False)


@router.get("/partials/assistant", response_class=HTMLResponse)
def assistant_body(
    request: Request,
    service: Annotated[AssistantService, Depends(get_assistant)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the assistant body, for HTMX to swap in."""
    return _render(request, service, hours, partial=True)
