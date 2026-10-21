"""Read backend events from Cloud Logging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from functools import partial
from itertools import islice
from typing import Protocol

from app.contract import Contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TelemetryEvent
from app.sources.filtering import matches, newest_first
from app.sources.gcp.entries import LogEntryLike, convert_entries
from app.sources.gcp.errors import guarded
from app.sources.gcp.filters import chunk_request_ids, events_filter
from app.sources.gcp.release_reader import ReleaseReader

NEWEST_FIRST = "timestamp desc"
# An inclusive cursor (``before_id``) re-reads every row sharing the cursor's
# timestamp so they can be trimmed in memory; asking for a few more than a page
# stops those trimmed rows from eating into the page and hiding the extra row
# that tells the list there is more to load.
TIE_MARGIN = 50


class LoggingClient(Protocol):
    """The part of google.cloud.logging.Client this reader uses."""

    def list_entries(
        self,
        *,
        filter_: str | None = None,
        order_by: str | None = None,
        max_results: int | None = None,
        page_size: int | None = None,
    ) -> Iterable[LogEntryLike]:
        """Iterate over matching entries."""
        ...


class LoggingReader:
    """Turns event queries into Cloud Logging reads."""

    def __init__(
        self,
        client: LoggingClient,
        contract: Contract,
        service_name: str,
        page_size: int,
        *,
        release_reader: ReleaseReader | None = None,
    ) -> None:
        self._client = client
        self._contract = contract
        self._service_name = service_name
        self._page_size = page_size
        self._release_reader = release_reader

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first, at most query.limit.

        Cloud Logging orders by timestamp only, so rows sharing a timestamp come
        back in no particular order; the paging cursor assumes the id breaks
        those ties, and chunked id reads have to be merged anyway, so the order
        is settled here rather than trusted from the API.
        """
        found: list[TelemetryEvent] = []
        for part in self._parts(query):
            found.extend(self._read(part))
        found.sort(key=newest_first, reverse=True)
        return found[: query.limit]

    def _parts(self, query: EventQuery) -> list[EventQuery]:
        """Split a multi-id query into chunks that keep one filter short."""
        chunks = chunk_request_ids(query.request_ids)
        if not chunks:
            return [query]
        return [replace(query, request_ids=chunk) for chunk in chunks]

    def _read(self, query: EventQuery) -> list[TelemetryEvent]:
        """Read one query's entries and drop what the filter could not express."""
        if query.release.kind != "all":
            if self._release_reader is None:
                raise SourceUnavailableError(
                    "unavailable", "bounded release reader is not configured"
                )
            return self._release_reader.selected_events(query)
        log_filter = events_filter(self._service_name, query)
        wanted = query.limit + (TIE_MARGIN if query.before_id is not None else 0)
        entries = guarded("Cloud Logging", partial(self._fetch, log_filter, wanted))
        events = convert_entries(entries, self._contract).events
        return [event for event in events if matches(event, query)][: query.limit]

    def _fetch(self, log_filter: str, limit: int) -> list[LogEntryLike]:
        """Read up to limit entries; consuming the pages here keeps errors guarded."""
        pages = self._client.list_entries(
            filter_=log_filter,
            order_by=NEWEST_FIRST,
            max_results=limit,
            page_size=min(limit, self._page_size),
        )
        return list(islice(pages, limit))
