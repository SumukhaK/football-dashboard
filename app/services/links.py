"""Links and short labels the pages render.

Building them here keeps the routes and the templates free of string arithmetic,
and means a route pattern is percent-encoded in exactly one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode

from app.domain.models import TimeWindow


def requests_link(window: TimeWindow, **params: object) -> str:
    """Build a /requests link for the window plus any non-null filter values."""
    hours = int((window.end - window.start).total_seconds() // 3600)
    query: dict[str, object] = {"hours": hours, **params}
    kept = {key: value for key, value in query.items() if value is not None}
    return "/requests?" + urlencode(kept)


def chart_label(moment: datetime, window: TimeWindow) -> str:
    """A compact chart label: HH:MM, with the date for multi-day windows."""
    shape = "%d %b %H:%M" if window.end - window.start > timedelta(days=1) else "%H:%M"
    return moment.strftime(shape)
