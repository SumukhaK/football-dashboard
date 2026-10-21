"""Read backend events from Cloud Logging."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from functools import partial
from itertools import islice
from typing import Protocol

from google.api_core.retry import Retry

from app.contract import Contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TelemetryEvent
from app.sources.filtering import matches, newest_first
from app.sources.gcp.budget import RPC_TIMEOUT_SECONDS, ReadBudget
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
        timeout: float | None = None,
        retry: Retry | None = None,
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
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._contract = contract
        self._service_name = service_name
        self._page_size = page_size
        self._release_reader = release_reader
        self._monotonic = monotonic

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first, at most query.limit.

        Cloud Logging orders by timestamp only, so rows sharing a timestamp come
        back in no particular order; the paging cursor assumes the id breaks
        those ties, and chunked id reads have to be merged anyway, so the order
        is settled here rather than trusted from the API.
        """
        budget = ReadBudget("Cloud Logging", self._monotonic)
        found: list[TelemetryEvent] = []
        for part in self._parts(query):
            found.extend(self._read(part, budget))
        found.sort(key=newest_first, reverse=True)
        return found[: query.limit]

    def _parts(self, query: EventQuery) -> list[EventQuery]:
        """Split a multi-id query into chunks that keep one filter short."""
        chunks = chunk_request_ids(query.request_ids)
        if not chunks:
            return [query]
        return [replace(query, request_ids=chunk) for chunk in chunks]

    def _read(self, query: EventQuery, budget: ReadBudget) -> list[TelemetryEvent]:
        """Read one query's entries and drop what the filter could not express."""
        if query.release.kind != "all":
            if self._release_reader is None:
                raise SourceUnavailableError(
                    "unavailable", "bounded release reader is not configured"
                )
            return self._release_reader.selected_events(query)
        budget.check()
        log_filter = events_filter(self._service_name, query)
        wanted = query.limit + (TIE_MARGIN if query.before_id is not None else 0)
        entries = guarded(
            "Cloud Logging", partial(self._fetch, log_filter, wanted, budget)
        )
        events = convert_entries(entries, self._contract).events
        return [event for event in events if matches(event, query)][: query.limit]

    def _fetch(
        self, log_filter: str, limit: int, budget: ReadBudget
    ) -> list[LogEntryLike]:
        """Read up to limit entries; consuming the pages here keeps errors guarded."""
        timeout = budget.timeout(RPC_TIMEOUT_SECONDS)
        pages = self._client.list_entries(
            filter_=log_filter,
            order_by=NEWEST_FIRST,
            max_results=limit,
            page_size=min(limit, self._page_size),
            timeout=timeout,
            retry=Retry(deadline=timeout),
        )
        return list(islice(self._budgeted(pages, budget), limit))

    @staticmethod
    def _budgeted(
        entries: Iterable[LogEntryLike], budget: ReadBudget
    ) -> Iterable[LogEntryLike]:
        """Stop consuming a pager once the whole read budget has expired."""
        for entry in entries:
            budget.check()
            yield entry
