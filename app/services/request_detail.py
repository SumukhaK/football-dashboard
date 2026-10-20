"""Builds the request detail page from the telemetry source.

The detail page has no window of its own, so it reads every line of one request
over the longest window the picker offers, oldest first, and turns the request's
trace into waterfall rows with :mod:`app.services.waterfall`. The list side of
the page lives in :mod:`app.services.requests`.
"""

from __future__ import annotations

from datetime import datetime

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, Trace
from app.domain.requests import RequestDetail, RequestPanel, TimelineEntry
from app.services.currency import conversion_note, display_attributes
from app.services.events import (
    duration_ms,
    severity_tone,
    status,
    status_tone,
    text,
)
from app.services.labels import format_duration_ms, relative_time
from app.services.waterfall import build_waterfall
from app.services.windows import window_for_hours
from app.sources.base import TelemetrySource

__all__ = ["DETAIL_HOURS", "build_panel", "request_detail"]

# The detail page has no window of its own, so it looks back over the longest
# window the picker offers and finds a request linked from any of them.
DETAIL_HOURS = max(WINDOW_HOURS)

TRACE_CONSOLE = "https://console.cloud.google.com/traces/list"

# Shown on the detail page when the trace read fails but the log lines did not.
TRACE_ERROR_MESSAGE = "The trace could not be loaded from Cloud Trace."

# The one event that marks a request that crashed the server.
CRASH_EVENT = "app.crash"


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
        timestamp=request.timestamp,
        route=text(request.attributes.get("route")),
        status=status(request),
        status_tone=status_tone(status(request)),
        duration_ms=duration_ms(request),
        revision=request.revision,
        error_code=text(request.attributes.get("error_code")),
        user_ref=_user_ref(events),
        timeline=tuple(_entry(event, settings) for event in events),
        waterfall=tuple(build_waterfall(trace, settings)) if trace else (),
        trace_id=trace_id,
        trace_url=_trace_url(settings, trace_id),
        trace_error=trace_error,
        traces_available=capabilities.traces,
        cost_conversion_note=(
            conversion_note(settings)
            if any("cost_usd" in event.attributes for event in events)
            or (
                trace is not None
                and any(
                    "cost_usd" in span.attributes
                    or any("cost_usd" in marker.attributes for marker in span.events)
                    for span in trace.spans
                )
            )
            else None
        ),
    )


def build_panel(detail: RequestDetail, now: datetime, close_link: str) -> RequestPanel:
    """The side panel's compact view of a detail the page has already read.

    The panel reuses the detail's trace rows and trace state; it adds the
    request's age, its formatted duration and a one-line reason it failed.
    """
    summary, tone = _summary(detail)
    return RequestPanel(
        request_id=detail.request_id,
        route=detail.route,
        status=detail.status,
        status_tone=detail.status_tone,
        timestamp=detail.timestamp,
        relative_time=relative_time(detail.timestamp, now),
        duration_label=format_duration_ms(detail.duration_ms),
        summary=summary,
        summary_tone=tone,
        waterfall=detail.waterfall,
        trace_id=detail.trace_id,
        trace_url=detail.trace_url,
        trace_error=detail.trace_error,
        traces_available=detail.traces_available,
        close_link=close_link,
    )


def _summary(detail: RequestDetail) -> tuple[str | None, str]:
    """One line naming why a request failed, and the tone to show it in.

    A crash is named by the last line of its traceback, which carries the
    exception; failing that an error code, if the request recorded one.
    """
    crash = next(
        (entry for entry in detail.timeline if entry.event == CRASH_EVENT), None
    )
    if crash is not None:
        return _crash_line(crash.message), "fail"
    if detail.error_code:
        tone = "fail" if (detail.status or 0) >= 500 else "warn"
        return detail.error_code, tone
    return None, "neutral"


def _crash_line(message: str) -> str:
    """The last non-blank line of a traceback, or "App crash" when it is empty."""
    lines = [line for line in message.splitlines() if line.strip()]
    return lines[-1] if lines else "App crash"


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


def _entry(event: TelemetryEvent, settings: Config) -> TimelineEntry:
    """One timeline row, with the attributes as sorted key-value pairs."""
    return TimelineEntry(
        timestamp=event.timestamp,
        severity=event.severity,
        severity_tone=severity_tone(event.severity),
        event=event.event,
        message=event.message,
        attributes=display_attributes(event.attributes, settings),
    )


def _trace_url(settings: Config, trace_id: str | None) -> str | None:
    """The Cloud Console link to a trace, only when reading from Google Cloud."""
    if settings.source != "gcp" or not trace_id or not settings.gcp_project_id:
        return None
    return f"{TRACE_CONSOLE}?project={settings.gcp_project_id}&tid={trace_id}"
