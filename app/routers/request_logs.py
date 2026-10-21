"""Requests Logs tab rendering; services own predicates and pagination."""

from fastapi import Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException

from app.config import WINDOW_HOURS
from app.dependencies import get_source
from app.domain.errors import SourceUnavailableError
from app.domain.logs import LogsPage
from app.domain.models import Severity
from app.services.currency import conversion_note
from app.services.logs import logs_page
from app.templating import templates
from app.view_context import prepare_scope


def render_logs(request: Request, partial: bool) -> HTMLResponse:
    """Render the native full/partial Logs view with explicit source failures."""
    query = request.query_params
    if any(len(query.getlist(k)) > 1 for k in ("tab", "severity", "event", "log_page")):
        raise HTTPException(422, "duplicate log filter")
    event = query.get("event") or None
    if event and event not in request.app.state.contract.events:
        raise HTTPException(422, "unknown log event")
    scope = prepare_scope(request)
    error = None
    page = None
    try:
        page = logs_page(
            get_source(request),
            request.app.state.config,
            scope,
            request.app.state.clock(),
            page=int(query.get("log_page", "0")),
            severity=query.get("severity") or None,
            event=event,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SourceUnavailableError as exc:
        error = {"kind": exc.kind, "detail": exc.detail}
    return templates.TemplateResponse(
        request,
        "partials/request_logs.html" if partial else "request_logs.html",
        _context(request, page, error),
    )


def _context(
    request: Request, page: LogsPage | None, error: dict[str, str] | None
) -> dict[str, object]:
    """The existing shell controls for a full or HTMX log view."""
    return {
        "logs": page,
        "cost_conversion_note": conversion_note(request.app.state.config),
        "error": error,
        "severities": Severity.values(),
        "events": sorted(request.app.state.contract.events),
        "hours": prepare_scope(request).hours,
        "window_hours": WINDOW_HOURS,
        "picker_path": "/partials/requests",
        "page_path": "/requests",
        "body_id": "requests-body",
    }
