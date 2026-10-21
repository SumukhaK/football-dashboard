"""Bounded explicit Logging scans for discovery and selected-release reads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from app.contract import Contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TelemetryEvent, TimeWindow
from app.domain.releases import ReleaseCatalogue
from app.sources.filtering import matches, newest_first
from app.sources.gcp.entries import LogEntryLike, convert_entries
from app.sources.gcp.errors import guarded
from app.sources.gcp.filters import events_filter
from app.sources.release_catalogue import catalogue_from_events

SCAN_MAX_PAGES = 5
SCAN_PAGE_SIZE = 1000
SCAN_SECONDS = 5.0


@dataclass(frozen=True)
class LogPage:
    """One already-fetched page; reading it performs no implicit RPC."""

    entries: tuple[LogEntryLike, ...]
    next_token: str


class ReleaseLogClient(Protocol):
    """An explicitly bounded one-page Logging operation."""

    def read_page(
        self, log_filter: str, token: str, size: int, timeout: float
    ) -> LogPage:
        """Read one page with retries disabled and a remaining RPC timeout."""
        ...


@dataclass(frozen=True)
class _Scan:
    """Validated selected events plus conservative scan completeness."""

    events: list[TelemetryEvent]
    limited: bool
    skipped: int


def _page_complete(
    events: list[TelemetryEvent], candidates: list[TelemetryEvent], limit: int
) -> bool:
    """Close the timestamp tie boundary before trusting the ID-sorted prefix."""
    if len(events) < limit:
        return False
    events.sort(key=newest_first, reverse=True)
    boundary = events[limit - 1].timestamp
    return any(event.timestamp < boundary for event in candidates)


class ReleaseReader:
    """Scan at most 5,000 candidates/five pages within a five-second RPC budget."""

    def __init__(
        self,
        client: ReleaseLogClient,
        contract: Contract,
        service: str,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._client = client
        self._contract = contract
        self._service = service
        self._clock = clock

    def release_catalogue(self, window: TimeWindow) -> ReleaseCatalogue:
        """Return exact observed labels without claiming capped data is complete."""
        scan = guarded(
            "Cloud Logging",
            lambda: self._scan(EventQuery(window=window, limit=MAX_QUERY_LIMIT)),
        )
        return catalogue_from_events(
            scan.events, truncated=scan.limited or scan.skipped > 0
        )

    def selected_events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Fill after strict local typing or fail rather than hide unread matches."""
        scan = guarded("Cloud Logging", lambda: self._scan(query))
        if scan.limited:
            raise SourceUnavailableError(
                "unavailable",
                "Cloud Logging: release scan limit reached; narrow the window",
            )
        return scan.events

    def _scan(self, query: EventQuery) -> _Scan:
        """Read explicit pages with one deadline and a hard raw-record cap."""
        deadline = self._clock() + SCAN_SECONDS
        log_filter = events_filter(self._service, query)
        token = ""
        seen: set[str] = set()
        events: list[TelemetryEvent] = []
        rows = skipped = 0
        limited = True
        for _ in range(SCAN_MAX_PAGES):
            remaining = deadline - self._clock()
            if remaining <= 0 or token in seen:
                break
            seen.add(token)
            page = self._client.read_page(
                log_filter,
                token,
                min(SCAN_PAGE_SIZE, MAX_QUERY_LIMIT - rows),
                remaining,
            )
            batch = page.entries[: MAX_QUERY_LIMIT - rows]
            converted = convert_entries(batch, self._contract)
            events.extend(event for event in converted.events if matches(event, query))
            rows += len(batch)
            skipped += converted.skipped
            token = page.next_token
            if not token and len(batch) == len(page.entries):
                limited = False
                break
            if _page_complete(events, converted.events, query.limit):
                limited = False
                break
            if rows >= MAX_QUERY_LIMIT:
                break
        events.sort(key=newest_first, reverse=True)
        return _Scan(events[: query.limit], limited, skipped)
