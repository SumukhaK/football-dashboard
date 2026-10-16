"""The crashes page: GET /crashes, its HTMX partial and GET /crashes/{issue_id}.

Only mounted when crashes are enabled. The routes own no arithmetic: they
resolve the window, ask the service for a model and render a template; a source
read that fails becomes a banner, never a 500.
"""

from __future__ import annotations

from typing import Annotated, Any

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
from app.templating import templates

router = fastapi.APIRouter(tags=["crashes"])

FULL_TEMPLATE = "crashes.html"
BODY_TEMPLATE = "partials/crashes_body.html"
DETAIL_TEMPLATE = "crash_detail.html"
UNSUPPORTED_WINDOW = 422
UNKNOWN_ISSUE = 404


def _resolve_hours(service: CrashesService, requested: int | None) -> int:
    """Resolve the window size, turning an unsupported one into a 422."""
    try:
        return service.resolve_hours(requested)
    except ValueError as exc:
        raise StarletteHTTPException(
            status_code=UNSUPPORTED_WINDOW, detail=str(exc)
        ) from exc


def _banner(exc: SourceUnavailableError) -> dict[str, str]:
    """The banner context for a failed read."""
    return {"kind": exc.kind, "detail": exc.detail}


def _render_list(
    request: Request, service: CrashesService, requested: int | None, partial: bool
) -> HTMLResponse:
    """Render the crashes list for one window request."""
    hours = _resolve_hours(service, requested)
    context: dict[str, Any] = {
        "model": None,
        "error": None,
        "hours": hours,
        "window_hours": WINDOW_HOURS,
        "picker_path": "/partials/crashes",
        "page_path": "/crashes",
        "body_id": "crashes-body",
    }
    try:
        context["model"] = service.build_for_hours(hours)
    except SourceUnavailableError as exc:
        context["error"] = _banner(exc)
    template = BODY_TEMPLATE if partial else FULL_TEMPLATE
    return templates.TemplateResponse(request, template, context)


@router.get("/crashes", response_class=HTMLResponse)
def crashes_page(
    request: Request,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render the full crashes page."""
    return _render_list(request, service, hours, partial=False)


@router.get("/partials/crashes", response_class=HTMLResponse)
def crashes_body(
    request: Request,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render only the crashes body, for HTMX to swap in."""
    return _render_list(request, service, hours, partial=True)


@router.get("/crashes/{issue_id}", response_class=HTMLResponse)
def crash_issue(
    request: Request,
    issue_id: str,
    service: Annotated[CrashesService, Depends(get_crashes)],
    hours: Annotated[int | None, Query()] = None,
) -> HTMLResponse:
    """Render one issue's recent events and the latest event's frames."""
    resolved = _resolve_hours(service, hours)
    context: dict[str, Any] = {"detail": None, "error": None, "hours": resolved}
    try:
        context["detail"] = service.detail_for_hours(issue_id, resolved)
    except SourceUnavailableError as exc:
        context["error"] = _banner(exc)
    if context["detail"] is None and context["error"] is None:
        raise StarletteHTTPException(
            status_code=UNKNOWN_ISSUE, detail=f"No events for issue {issue_id}"
        )
    return templates.TemplateResponse(request, DETAIL_TEMPLATE, context)
