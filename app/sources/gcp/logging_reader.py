"""Read backend events from Cloud Logging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from functools import partial
from itertools import islice
from typing import Protocol

from app.contract import Contract
from app.domain.models import EventQuery, TelemetryEvent
from app.sources.filtering import matches, newest_first
from app.sources.gcp.entries import LogEntryLike, convert_entries
from app.sources.gcp.errors import guarded
from app.sources.gcp.filters import chunk_request_ids, events_filter

NEWEST_FIRST = "timestamp desc"


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
    ) -> None:
        self._client = client
        self._contract = contract
        self._service_name = service_name
        self._page_size = page_size

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first, at most query.limit."""
        parts = self._parts(query)
        found: list[TelemetryEvent] = []
        for part in parts:
            found.extend(self._read(part))
        if len(parts) > 1:
            # One read per id chunk, so the chunks have to be merged back into
            # one newest-first page here; a single read already comes sorted.
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
        log_filter = events_filter(self._service_name, query)
        entries = guarded(
            "Cloud Logging", partial(self._fetch, log_filter, query.limit)
        )
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
