"""Builds the requests list from the telemetry source.

The list page reads one page of ``http.request`` lines: ``PAGE_SIZE + 1`` at
most, so the extra line decides whether "load more" appears. When an event filter
is set, the matching request ids are read first and the request lines are then
read by id, so a matching request is found however old it is. The request detail
page lives in :mod:`app.services.request_detail`.
"""

from __future__ import annotations

from datetime import datetime

from app.config import WINDOW_HOURS, Config
from app.domain.clock import Clock
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    MAX_QUERY_LIMIT,
    UNMATCHED_ROUTE,
    EventQuery,
    TelemetryEvent,
    TimeWindow,
    is_route_filter,
)
from app.domain.releases import ReleaseSelection
from app.domain.requests import (
    FilterChip,
    RequestDetail,
    RequestFilters,
    RequestPage,
    RequestPanel,
    RequestRow,
    StatusRange,
)
from app.services.events import duration_ms, status, status_tone, text
from app.services.labels import format_duration_ms, relative_time
from app.services.links import request_detail_link, requests_link
from app.services.request_detail import build_panel, request_detail
from app.services.request_links import (
    PAGE_SIZE,
    filter_params,
    next_link,
    open_link,
    panel_link,
)
from app.services.windows import resolve_window_hours, window_for_hours
from app.sources.base import TelemetrySource

__all__ = [
    "IDS_FOR_REQUESTS",
    "PAGE_SIZE",
    "WINDOW_HOURS",
    "FilterChip",
    "InvalidFilter",
    "RequestFilters",
    "RequestPage",
    "RequestPanel",
    "RequestsService",
    "SourceUnavailableError",
    "clean_text",
    "parse_status",
]

REQUESTS_EVENT: tuple[str, ...] = ("http.request",)

# The results table shows this many rows, and the query reads one more so the
# extra line can decide whether a "load more" cursor is needed.

# Reading a request per id costs one Cloud Logging call per 100 ids, against a
# default quota of about 60 calls a minute, so an event filter narrows the
# request read to at most this many ids: two calls per page, newest first.
IDS_FOR_REQUESTS = 200

STATUS_CLASSES: tuple[tuple[str, int, int], ...] = (
    ("2xx", 200, 300),
    ("4xx", 400, 500),
    ("5xx", 500, 600),
)

# The one event whose lines carry a ``component`` attribute, so the one a
# component filter can narrow.
DEGRADED_EVENT = "component.degraded"

# The "load more" button fetches appended rows from this endpoint, not the page.


def clean_text(value: str | None) -> str | None:
    """Normalise a filter box: empty or whitespace-only text becomes None.

    The filter form submits every field, so a plain submit sends empty strings;
    treating those as no filter keeps a bare submit the same as no query string.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


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


def _error_text(code: int | None, event: TelemetryEvent) -> str | None:
    """The line under a row's route: the error code, or the message when it failed."""
    error_code = text(event.attributes.get("error_code"))
    if error_code:
        return error_code
    if (code or 0) >= 400:
        return event.message
    return None


class InvalidFilter(ValueError):
    """A filter box holds a value the page cannot query.

    Carries the box's name and the filters as parsed, so the page can draw the
    form around that box instead of losing what was typed.
    """

    def __init__(self, field: str, message: str, filters: RequestFilters) -> None:
        """Record which box failed and the filters it was parsed into."""
        super().__init__(message)
        self.field = field
        self.filters = filters


class RequestsService:
    """Turns request filters into the results page and the detail page."""

    def __init__(
        self,
        source: TelemetrySource,
        clock: Clock,
        settings: Config,
        *,
        detail_source: TelemetrySource | None = None,
        window: TimeWindow | None = None,
        release: ReleaseSelection | None = None,
    ) -> None:
        """Store the source, clock and settings the service reads through."""
        self._source = source
        self._clock = clock
        self._settings = settings
        self._detail_source = detail_source or source
        self._window = window
        self._release = release or ReleaseSelection()

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
        """Validate filters; a component only belongs to component.degraded.

        Reject malformed routes before source reads so they cannot cause a 500.
        """
        resolved = self.resolve_hours(hours)
        wanted = clean_text(event)
        parsed = RequestFilters(
            window=window_for_hours(resolved, self._clock()),
            hours=resolved,
            route=clean_text(route),
            status=parse_status(status_text),
            event=wanted,
            component=clean_text(component) if wanted == DEGRADED_EVENT else None,
            before=before,
            before_id=before_id,
        )
        if parsed.route is not None and not is_route_filter(parsed.route):
            raise InvalidFilter(
                "route",
                f"Enter a route starting with / (or {UNMATCHED_ROUTE}).",
                parsed,
            )
        return parsed

    def search(self, filters: RequestFilters) -> RequestPage:
        """Read one page of requests matching the filters."""
        matched, truncated = self._read_requests(filters)
        now = self._clock()
        return RequestPage(
            window=filters.window,
            hours=filters.hours,
            filters=filters,
            rows=tuple(self._row(event, filters, now) for event in matched[:PAGE_SIZE]),
            next_link=next_link(filters, matched),
            truncated=truncated,
        )

    def detail(
        self, request_id: str, window: TimeWindow | None = None
    ) -> RequestDetail | None:
        """Everything the detail page shows, or None when the id has no lines."""
        return request_detail(
            self._detail_source,
            self._clock,
            self._settings,
            request_id,
            window=window or self._window,
            release=self._release,
        )

    def panel(self, request_id: str, filters: RequestFilters) -> RequestPanel | None:
        """The side panel for one request, or None when the id has no lines.

        The panel is the detail page's compact form, so it reads the same lines
        and trace and only narrows them; the close link keeps the list's filters.
        """
        detail = self.detail(request_id, filters.window)
        if detail is None:
            return None
        return build_panel(detail, self._clock(), self.list_link(filters))

    def chips(self, filters: RequestFilters) -> tuple[FilterChip, ...]:
        """One chip per active filter, each removing only what it names."""
        chips: list[FilterChip] = []
        for field in ("status", "event", "component"):
            label = self._chip_label(filters, field)
            if label is not None:
                chips.append(
                    FilterChip(
                        field=field,
                        label=label,
                        remove_link=self._link_without(filters, field),
                    )
                )
        return tuple(chips)

    def list_link(self, filters: RequestFilters) -> str:
        """The current list with every active filter, for the panel's Close."""
        return requests_link(filters.window, "/requests", **filter_params(filters))

    @staticmethod
    def clear_link(filters: RequestFilters) -> str:
        """The list with every filter dropped, for "Clear all"."""
        return requests_link(filters.window, "/requests")

    @staticmethod
    def _chip_label(filters: RequestFilters, field: str) -> str | None:
        """The value an active filter shows on its chip, or None when it is off."""
        if field == "status":
            return filters.status.label if filters.status else None
        if field == "event":
            return filters.event
        return filters.component

    def _link_without(self, filters: RequestFilters, field: str) -> str:
        """The list with one filter dropped and every other one kept.

        A component only means something beside the degraded event, so removing
        the event removes the component with it rather than leaving it stranded.
        """
        kept = filter_params(filters)
        kept[field] = None
        if field == "event":
            kept["component"] = None
        return requests_link(filters.window, "/requests", **kept)

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
        """The request ids carrying the filtered event, and whether the list is partial.

        The ids are taken newest first and at most ``IDS_FOR_REQUESTS`` of them
        are used, so a coarse event filter costs two Cloud Logging calls instead
        of spending the page's quota; ``truncated`` then says the list is partial.
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
        ordered: list[str] = []
        seen: set[str] = set()
        for event in events:  # newest first, as every source returns them
            if event.request_id is None or event.request_id in seen:
                continue
            seen.add(event.request_id)
            ordered.append(event.request_id)
        return (
            tuple(ordered[:IDS_FOR_REQUESTS]),
            capped or len(ordered) > IDS_FOR_REQUESTS,
        )

    def _row(
        self, event: TelemetryEvent, filters: RequestFilters, now: datetime
    ) -> RequestRow:
        """One list row from an ``http.request`` line."""
        code = status(event)
        request_id = event.request_id
        return RequestRow(
            api_version=event.api_version,
            timestamp=event.timestamp,
            relative_time=relative_time(event.timestamp, now),
            method=text(event.attributes.get("method")) or "",
            route=text(event.attributes.get("route")) or "<unknown>",
            status=code,
            status_tone=status_tone(code),
            duration_label=format_duration_ms(duration_ms(event)),
            error_text=_error_text(code, event),
            request_id=request_id,
            link=request_detail_link(request_id) if request_id else None,
            panel_link=(panel_link(filters, request_id) if request_id else None),
            open_link=open_link(filters, request_id) if request_id else None,
        )
