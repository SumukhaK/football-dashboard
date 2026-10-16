"""Builds the requests page and the request detail from the telemetry source.

The list page reads one page of ``http.request`` lines: ``PAGE_SIZE + 1`` at
most, so the extra line decides whether "load more" appears. When an event
filter is set, the matching request ids are read first and the request lines are
then read by id, so a matching request is found however old it is. The detail
page reads every line of one request, oldest first, and turns its trace into
waterfall rows with :mod:`app.services.waterfall`.
"""

from __future__ import annotations

from datetime import datetime

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    EventQuery,
    TelemetryEvent,
    Trace,
    is_route_template,
)
from app.domain.requests import (
    RequestDetail,
    RequestFilters,
    RequestPage,
    RequestRow,
    StatusRange,
    TimelineEntry,
)
from app.services.events import duration_ms, status, text
from app.services.links import requests_link
from app.services.waterfall import build_waterfall
from app.services.windows import resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "EVENT_OPTIONS",
    "PAGE_SIZE",
    "STATUS_OPTIONS",
    "WINDOW_HOURS",
    "RequestFilters",
    "RequestPage",
    "RequestsService",
    "SourceUnavailableError",
    "clean_text",
    "parse_status",
]

REQUESTS_EVENT: tuple[str, ...] = ("http.request",)

# The results table shows this many rows, and the query reads one more so the
# extra line can decide whether a "load more" cursor is needed.
PAGE_SIZE = 100

STATUS_CLASSES: tuple[tuple[str, int, int], ...] = (
    ("2xx", 200, 300),
    ("4xx", 400, 500),
    ("5xx", 500, 600),
)
STATUS_OPTIONS: tuple[str, ...] = tuple(label for label, _, _ in STATUS_CLASSES)

# The events the filter select offers. The Overview also links here with
# ``event=component.degraded&component=<name>``, which this page understands.
EVENT_OPTIONS: tuple[str, ...] = (
    "app.crash",
    "retry",
    "fallback",
    "ratelimit.rejected",
)

# The one event whose lines carry a ``component`` attribute, so the one a
# component filter can narrow.
DEGRADED_EVENT = "component.degraded"

# An event filter reads the requests for at most this many ids, the newest
# first. Google Cloud reads ids 100 per call against a quota of about 60 reads a
# minute, so the full 5,000 would be 50 reads for every page and "load more".
MAX_EVENT_REQUESTS = 200

# The detail page has no window of its own, so it looks back over the longest
# window the picker offers and finds a request linked from any of them.
DETAIL_HOURS = max(WINDOW_HOURS)

# The "load more" button fetches appended rows from this endpoint, not the page.
ROWS_PATH = "/partials/request_rows"

TRACE_CONSOLE = "https://console.cloud.google.com/traces/list"

# Shown on the detail page when the trace read fails but the log lines did not.
TRACE_ERROR_MESSAGE = "The trace could not be loaded from Cloud Trace."


def clean_text(value: str | None) -> str | None:
    """Normalise a filter box: empty or whitespace-only text becomes None.

    The filter form submits every field, so a plain submit sends empty strings;
    treating those as no filter keeps a bare submit the same as no query string.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def status_class(code: int | None) -> str:
    """The CSS class a status code maps to."""
    if code is None:
        return "status-none"
    if code >= 500:
        return "status-error"
    if code >= 400:
        return "status-warning"
    return "status-healthy"


def severity_class(severity: str) -> str:
    """The CSS class a log severity maps to."""
    if severity in ("ERROR", "CRITICAL"):
        return "status-error"
    if severity == "WARNING":
        return "status-warning"
    return "status-healthy"


def parse_route(value: str | None) -> str | None:
    """Parse a route filter: a route template such as ``/v2/predict``, or None.

    Rejecting anything else here makes a typo a 422 on every source, instead of
    an empty list on the sample data and a failed read on Google Cloud.
    """
    cleaned = clean_text(value)
    if cleaned is not None and not is_route_template(cleaned):
        raise ValueError(f"invalid route filter: {value!r} (routes start with /)")
    return cleaned


def parse_status(value: str | None) -> StatusRange | None:
    """Parse a status filter: a class such as ``5xx``, an exact code, or None."""
    cleaned = clean_text(value)
    if cleaned is None:
        return None
    for label, low, high in STATUS_CLASSES:
        if cleaned == label:
            return StatusRange(low=low, high=high, label=label)
    if cleaned.isdigit() and 100 <= int(cleaned) <= 599:
        return StatusRange(low=int(cleaned), high=int(cleaned) + 1, label=cleaned)
    raise ValueError(f"invalid status filter: {value!r}")


class RequestsService:
    """Turns request filters into the results page and the detail page."""

    def __init__(self, source: TelemetrySource, clock: Clock, settings: Config) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings

    def resolve_hours(self, hours: int | None) -> int:
        """Return the requested window size, defaulting and validating it."""
        return resolve_window_hours(hours, self._settings.default_window_hours)

    def filters(
        self,
        hours: int | None,
        route: str | None,
        status_text: str | None,
        event: str | None,
        component: str | None,
        before: datetime | None,
        before_id: str | None = None,
    ) -> RequestFilters:
        """Validate and parse every filter the page accepts.

        ``component`` is only honoured alongside the degraded event, which is the
        only event that carries one; a component sent with another event is
        stale form state (the hidden field from a link's degraded view) and would
        otherwise quietly narrow the new filter to nothing.
        """
        resolved = self.resolve_hours(hours)
        wanted = clean_text(event)
        return RequestFilters(
            window=window_for_hours(resolved, self._clock()),
            hours=resolved,
            route=parse_route(route),
            status=parse_status(status_text),
            event=wanted,
            component=clean_text(component) if wanted == DEGRADED_EVENT else None,
            before=before,
            before_id=before_id,
        )

    def search(self, filters: RequestFilters) -> RequestPage:
        """Read one page of requests matching the filters."""
        matched, truncated = self._read_requests(filters)
        return RequestPage(
            window=filters.window,
            hours=filters.hours,
            filters=filters,
            rows=tuple(self._row(event) for event in matched[:PAGE_SIZE]),
            next_link=self._next_link(filters, matched),
            truncated=truncated,
        )

    def detail(self, request_id: str) -> RequestDetail | None:
        """Everything the detail page shows, or None when the id has no lines."""
        events = self._detail_events(request_id)
        if not events:
            return None
        request = _request_line(events)
        trace_id = _first_trace(events)
        trace, trace_error = self._trace(trace_id)
        return RequestDetail(
            request_id=request_id,
            route=text(request.attributes.get("route")),
            status=status(request),
            status_class=status_class(status(request)),
            duration_ms=duration_ms(request),
            revision=request.revision,
            error_code=text(request.attributes.get("error_code")),
            user_ref=_user_ref(events),
            timeline=tuple(_entry(event) for event in events),
            waterfall=tuple(build_waterfall(trace)) if trace else (),
            trace_id=trace_id,
            trace_url=_trace_url(self._settings, trace_id),
            trace_error=trace_error,
        )

    def _trace(self, trace_id: str | None) -> tuple[Trace | None, str | None]:
        """Read the trace, turning a source failure into a message for the page."""
        if not trace_id:
            return None, None
        try:
            return self._source.trace(trace_id), None
        except SourceUnavailableError:
            return None, TRACE_ERROR_MESSAGE

    def _read_requests(
        self, filters: RequestFilters
    ) -> tuple[list[TelemetryEvent], bool]:
        """One page of request lines, newest first, and whether the event read capped.

        Reading by id when an event filter is set means an old matching request
        is found even when the window holds far more requests than one read
        returns. The extra row is what lets the template offer "load more".
        """
        ids, truncated = self._event_request_ids(filters)
        if ids is not None and not ids:
            # The event matched no request, so no request can match: reading
            # every request here would list rows that never carried the event.
            return [], truncated
        events = self._source.events(
            EventQuery(
                window=filters.window,
                events=REQUESTS_EVENT,
                request_ids=ids or (),
                route=filters.route,
                min_status=filters.status.low if filters.status else None,
                max_status=filters.status.high if filters.status else None,
                before=filters.before,
                before_id=filters.before_id,
                limit=PAGE_SIZE + 1,
            )
        )
        return events, truncated

    def _event_request_ids(
        self, filters: RequestFilters
    ) -> tuple[tuple[str, ...] | None, bool]:
        """The newest request ids carrying the filtered event, and whether any were cut.

        Events come newest first, so keeping the first ids keeps the newest
        requests; the page shows the "narrow the filter" banner when the event
        read or the id list hit its cap.
        """
        if filters.event is None:
            return None, False
        events = self._source.events(
            EventQuery(
                window=filters.window,
                events=(filters.event,),
                limit=MAX_QUERY_LIMIT,
            )
        )
        capped = len(events) == MAX_QUERY_LIMIT
        if filters.component is not None:
            events = [
                event
                for event in events
                if event.attributes.get("component") == filters.component
            ]
        ids = dict.fromkeys(
            event.request_id for event in events if event.request_id is not None
        )
        newest = tuple(ids)[:MAX_EVENT_REQUESTS]
        return newest, capped or len(ids) > MAX_EVENT_REQUESTS

    def _detail_events(self, request_id: str) -> list[TelemetryEvent]:
        """Every line of one request, oldest first, over the longest window."""
        query = EventQuery(
            window=window_for_hours(DETAIL_HOURS, self._clock()),
            request_id=request_id,
            limit=MAX_QUERY_LIMIT,
        )
        return sorted(self._source.events(query), key=lambda event: event.timestamp)

    @staticmethod
    def _row(event: TelemetryEvent) -> RequestRow:
        """One results-table row from an ``http.request`` line."""
        code = status(event)
        return RequestRow(
            timestamp=event.timestamp,
            method=text(event.attributes.get("method")) or "",
            route=text(event.attributes.get("route")) or "<unknown>",
            status=code,
            status_class=status_class(code),
            duration_ms=duration_ms(event),
            error_code=text(event.attributes.get("error_code")),
            request_id=event.request_id,
            link=f"/requests/{event.request_id}",
        )

    @staticmethod
    def _next_link(
        filters: RequestFilters, matched: list[TelemetryEvent]
    ) -> str | None:
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
        severity_class=severity_class(event.severity),
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
