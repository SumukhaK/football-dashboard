"""Builds the request detail page from the telemetry source.

The detail page has no window of its own, so it reads every line of one request
over the longest window the picker offers, oldest first, and turns the request's
trace into waterfall rows with :mod:`app.services.waterfall`. The list side of
the page lives in :mod:`app.services.requests`.
"""

from __future__ import annotations

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, Trace
from app.domain.requests import RequestDetail, TimelineEntry
from app.services.events import (
    duration_ms,
    severity_tone,
    status,
    status_tone,
    text,
)
from app.services.waterfall import build_waterfall
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource

__all__ = ["DETAIL_HOURS", "request_detail"]

# The detail page has no window of its own, so it looks back over the longest
# window the picker offers and finds a request linked from any of them.
DETAIL_HOURS = max(WINDOW_HOURS)

TRACE_CONSOLE = "https://console.cloud.google.com/traces/list"

# Shown on the detail page when the trace read fails but the log lines did not.
TRACE_ERROR_MESSAGE = "The trace could not be loaded from Cloud Trace."


def request_detail(
    source: TelemetrySource, clock: Clock, settings: Config, request_id: str
) -> RequestDetail | None:
    """Everything the detail page shows, or None when the id has no lines."""
    events = _detail_events(source, clock, request_id)
    if not events:
        return None
    capabilities = source.capabilities()
    request = _request_line(events)
    trace_id = _first_trace(events)
    trace, trace_error = (
        _trace(source, trace_id) if capabilities.traces else (None, None)
    )
    return RequestDetail(
        request_id=request_id,
        route=text(request.attributes.get("route")),
        status=status(request),
        status_tone=status_tone(status(request)),
        duration_ms=duration_ms(request),
        revision=request.revision,
        error_code=text(request.attributes.get("error_code")),
        user_ref=_user_ref(events),
        timeline=tuple(_entry(event) for event in events),
        waterfall=tuple(build_waterfall(trace)) if trace else (),
        trace_id=trace_id,
        trace_url=_trace_url(settings, trace_id),
        trace_error=trace_error,
        traces_available=capabilities.traces,
    )


def _detail_events(
    source: TelemetrySource, clock: Clock, request_id: str
) -> list[TelemetryEvent]:
    """Every line of one request, oldest first, over the longest window."""
    query = EventQuery(
        window=window_for_hours(DETAIL_HOURS, clock()),
        request_id=request_id,
        limit=MAX_QUERY_LIMIT,
    )
    return sorted(source.events(query), key=lambda event: event.timestamp)


def _trace(
    source: TelemetrySource, trace_id: str | None
) -> tuple[Trace | None, str | None]:
    """Read the trace, turning a source failure into a message for the page."""
    if not trace_id:
        return None, None
    try:
        return source.trace(trace_id), None
    except SourceUnavailableError:
        return None, TRACE_ERROR_MESSAGE


def _request_line(events: list[TelemetryEvent]) -> TelemetryEvent:
    """The request's own line, or the first line when none is present."""
    return next((event for event in events if event.event == "http.request"), events[0])


def _first_trace(events: list[TelemetryEvent]) -> str | None:
    """The first trace id on the request's lines, or None when there is none."""
    for event in events:
        if event.trace_id:
            return event.trace_id
    return None


def _user_ref(events: list[TelemetryEvent]) -> str | None:
    """The user reference from any of the request's lines, or None."""
    for event in events:
        found = text(event.attributes.get("user_ref"))
        if found:
            return found
    return None


def _entry(event: TelemetryEvent) -> TimelineEntry:
    """One timeline row, with the attributes as sorted key-value pairs."""
    return TimelineEntry(
        timestamp=event.timestamp,
        severity=event.severity,
        severity_tone=severity_tone(event.severity),
        event=event.event,
        message=event.message,
        attributes=tuple(
            sorted(
                (key, "null" if value is None else str(value))
                for key, value in event.attributes.items()
            )
        ),
    )


def _trace_url(settings: Config, trace_id: str | None) -> str | None:
    """The Cloud Console link to a trace, only when reading from Google Cloud."""
    if settings.source != "gcp" or not trace_id or not settings.gcp_project_id:
        return None
    return f"{TRACE_CONSOLE}?project={settings.gcp_project_id}&tid={trace_id}"
