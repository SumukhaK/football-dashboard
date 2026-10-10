"""Read backend events from Cloud Logging."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import Protocol

from app.contract import Contract
from app.domain.models import EventQuery, TelemetryEvent
from app.sources.gcp.entries import LogEntryLike, convert_entries
from app.sources.gcp.errors import guarded
from app.sources.gcp.filters import events_filter

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
        log_filter = events_filter(self._service_name, query)
        entries = guarded("Cloud Logging", lambda: self._fetch(log_filter, query.limit))
        return convert_entries(entries, self._contract).events

    def _fetch(self, log_filter: str, limit: int) -> list[LogEntryLike]:
        """Read up to limit entries; consuming the pages here keeps errors guarded."""
        pages = self._client.list_entries(
            filter_=log_filter,
            order_by=NEWEST_FIRST,
            max_results=limit,
            page_size=min(limit, self._page_size),
        )
        return list(islice(pages, limit))
