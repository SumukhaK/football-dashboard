"""Canonical filter and pagination links used by request lists and panels."""

from app.domain.models import TelemetryEvent
from app.domain.requests import RequestFilters
from app.services.links import requests_link

PAGE_SIZE = 100
ROWS_PATH = "/partials/request_rows"


def filter_params(filters: RequestFilters) -> dict[str, str | None]:
    """The active filters as query parameters, for every link that carries them."""
    return {
        "route": filters.route,
        "status": filters.status.label if filters.status else None,
        "event": filters.event,
        "component": filters.component,
    }


def panel_link(filters: RequestFilters, request_id: str) -> str:
    """The partial that swaps one request's panel into the list."""
    return requests_link(
        filters.window,
        f"/partials/requests/{request_id}/panel",
        **filter_params(filters),
    )


def open_link(filters: RequestFilters, request_id: str) -> str:
    """The list's own URL with this request's panel open, so it can be shared."""
    return requests_link(
        filters.window, "/requests", **filter_params(filters), open=request_id
    )


def next_link(filters: RequestFilters, matched: list[TelemetryEvent]) -> str | None:
    """A "load more" link past the last row shown, or None on the last page.

    The cursor is the last row's timestamp *and* request id, so rows sharing
    that timestamp are neither dropped nor shown twice.
    """
    if len(matched) <= PAGE_SIZE:
        return None
    cursor = matched[PAGE_SIZE - 1]
    return requests_link(
        filters.window,
        ROWS_PATH,
        route=filters.route,
        status=filters.status.label if filters.status else None,
        event=filters.event,
        component=filters.component,
        before=cursor.timestamp.isoformat(),
        before_id=cursor.request_id,
    )
