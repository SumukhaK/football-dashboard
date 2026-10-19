"""Links and short labels the pages render.

Building them here keeps the routes and the templates free of string arithmetic,
and means a route pattern is percent-encoded in exactly one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

from app.domain.models import TimeWindow


def requests_link(window: TimeWindow, path: str = "/requests", **params: object) -> str:
    """Build a link for the window plus any non-null filter values."""
    hours = int((window.end - window.start).total_seconds() // 3600)
    query: dict[str, object] = {"hours": hours, **params}
    kept = {key: value for key, value in query.items() if value is not None}
    return path + "?" + urlencode(kept)


def request_detail_link(request_id: str) -> str:
    """The detail page of one request.

    A request id only contains characters that are safe in a path, so it is
    appended as it is rather than percent-encoded.
    """
    return f"/requests/{request_id}"


def crash_detail_link(issue_id: str) -> str:
    """The full page of one crash issue.

    An issue id comes from the export, so it is percent-encoded rather than
    trusted to be path-safe.
    """
    return f"/crashes/{quote(issue_id, safe='')}"


def crash_panel_link(issue_id: str) -> str:
    """The partial that swaps one crash issue's panel into the list."""
    return f"/partials/crashes/{quote(issue_id, safe='')}/panel"


def chart_label(moment: datetime, window: TimeWindow) -> str:
    """A compact chart label: HH:MM, with the date for multi-day windows."""
    shape = "%d %b %H:%M" if window.end - window.start > timedelta(days=1) else "%H:%M"
    return moment.strftime(shape)
