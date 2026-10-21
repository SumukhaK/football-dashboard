"""Bounded log browsing reuses source predicates and timeline presentation."""

import json
from dataclasses import replace
from datetime import datetime
from urllib.parse import urlencode

from app.config import Config
from app.domain.logs import LogsPage
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, TimeWindow
from app.services.request_detail import timeline_entry
from app.services.view_scope import ViewScope
from app.sources.base import TelemetrySource

PAGE_SIZE = 100


def logs_page(
    source: TelemetrySource,
    settings: Config,
    scope: ViewScope,
    now: datetime,
    *,
    page: int = 0,
    severity: str | None = None,
    event: str | None = None,
) -> LogsPage:
    """Browse at most 5000 matching rows; never skip tied timestamps by cursor."""
    if not 0 <= page < MAX_QUERY_LIMIT // PAGE_SIZE:
        raise ValueError("log page exceeds the bounded sample")
    window = TimeWindow(scope.window.start, min(scope.window.end, now))
    query = EventQuery(
        window,
        events=(event,) if event else (),
        release=scope.release,
        severity=severity,
        limit=MAX_QUERY_LIMIT,
    )
    events = sorted(source.events(query), key=_order, reverse=True)
    offset = page * PAGE_SIZE
    return LogsPage(
        tuple(timeline_entry(e, settings) for e in events[offset : offset + PAGE_SIZE]),
        _next_link(scope, window, page, len(events), severity, event),
        len(events) == MAX_QUERY_LIMIT,
    )


def _order(event: TelemetryEvent) -> tuple[datetime, str, str, str, str]:
    """Stable ties include content so repeated cached pages never depend on ID alone."""
    return (
        event.timestamp,
        event.request_id or "",
        event.event or "",
        event.message,
        json.dumps(dict(event.attributes), sort_keys=True, default=str),
    )


def _next_link(
    scope: ViewScope,
    window: TimeWindow,
    page: int,
    count: int,
    severity: str | None,
    event: str | None,
) -> str | None:
    """Freeze time for bounded sample pagination, retaining release and filters."""
    if (page + 1) * PAGE_SIZE >= count:
        return None
    frozen = replace(scope, window=window, custom=True)
    params = {**frozen.params(), "tab": "logs", "log_page": str(page + 1)}
    params.update(
        {k: v for k, v in {"severity": severity, "event": event}.items() if v}
    )
    return "/requests?" + urlencode(params)
