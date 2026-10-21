"""Explicit paging and budget/identity correctness without a Google call."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_release_predicates import entries

from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.domain.releases import ReleaseSelection
from app.sources.gcp.release_reader import LogPage, ReleaseReader

WINDOW = TimeWindow(
    start=datetime(2026, 10, 8, 12, tzinfo=UTC),
    end=datetime(2026, 10, 8, 13, tzinfo=UTC),
)


class FakePages:
    """Explicit pages with controllable elapsed time and safe failure injection."""

    def __init__(self, pages: list[LogPage | Exception], advance: float = 0) -> None:
        self.pages = pages
        self.calls: list[tuple[str, str, int, float]] = []
        self.now = 0.0
        self.advance = advance

    def read_page(
        self, log_filter: str, token: str, size: int, timeout: float
    ) -> LogPage:
        """Record a page request, without automatic paging or sleeping."""
        self.calls.append((log_filter, token, size, timeout))
        self.now += self.advance
        page = self.pages[min(len(self.calls) - 1, len(self.pages) - 1)]
        if isinstance(page, Exception):
            raise page
        return page


def reader(client: FakePages) -> ReleaseReader:
    """Use a fake monotonic clock for all bounded-scan checks."""
    from app.sources.gcp.release_reader import ReleaseReader

    return ReleaseReader(
        client, load_contract(), "football-api", clock=lambda: client.now
    )


def test_catalogue_scope_tokens_and_remaining_rpc_timeout() -> None:
    """Each next page gets the remaining deadline and the same source/window."""
    from app.sources.gcp.release_reader import LogPage

    client = FakePages(
        [LogPage(tuple(entries()[:2]), "next"), LogPage(tuple(entries()[2:]), "")],
        advance=1,
    )
    result = reader(client).release_catalogue(WINDOW)
    assert result.versions == ("2.5.0", "V2.6.0", "v2.6.0")
    assert not result.truncated and not result.has_unknown
    assert [call[1] for call in client.calls] == ["", "next"]
    assert [call[3] for call in client.calls] == [5.0, 4.0]
    assert all(
        'resource.labels.service_name="football-api"' in call[0]
        and "timestamp>=" in call[0]
        for call in client.calls
    )


@pytest.mark.parametrize("mode", ["time", "pages", "rows", "repeated_token"])
def test_catalogue_marks_every_budget_limit_incomplete(mode: str) -> None:
    """Limits terminate scans without presenting their sample as complete."""
    from app.sources.gcp.release_reader import LogPage

    row = entries()[0]
    if mode == "rows":
        client = FakePages([LogPage((row,) * 6000, "oversize")])
    elif mode == "repeated_token":
        client = FakePages([LogPage((row,), "same")])
    else:
        client = FakePages(
            [LogPage((row,), str(i)) for i in range(1, 8)],
            advance=6 if mode == "time" else 0,
        )
    result = reader(client).release_catalogue(WINDOW)
    assert result.truncated
    assert len(client.calls) <= 5
    assert (
        len(client.calls)
        == {"time": 1, "pages": 5, "rows": 1, "repeated_token": 2}[mode]
    )
    assert all(0 < call[3] <= 5 for call in client.calls)


def test_provider_failure_is_not_a_successful_empty_catalogue() -> None:
    """Exhausted transport retries still use A1's existing safe source error."""
    from google.api_core.exceptions import RetryError, ServiceUnavailable

    client = FakePages([RetryError("private-wrapper", ServiceUnavailable("secret"))])
    with pytest.raises(SourceUnavailableError) as raised:
        reader(client).release_catalogue(WINDOW)
    assert raised.value.kind == "unavailable"
    assert (
        "secret" not in raised.value.detail
        and "private-wrapper" not in raised.value.detail
    )


@pytest.mark.parametrize("value", [None, "", " ", "unknown", 42, {}, [], ["2.6.0"]])
def test_unknown_metadata_has_strict_scalar_parity(value: object) -> None:
    """Arrays/objects and invalid labels remain unknown instead of false exacts."""
    from app.sources.gcp.release_reader import LogPage

    original = entries()[0]
    original.payload["api_version"] = value
    client = FakePages([LogPage((original,), "")])
    found = reader(client).selected_events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("unknown"))
    )
    assert len(found) == 1 and found[0].api_version is None


def test_exact_array_false_positive_does_not_consume_final_limit() -> None:
    """A provider array match is rejected before filling the selected page."""
    from app.sources.gcp.release_reader import LogPage

    array = entries()[0]
    array.payload["api_version"] = ["2.5.0"]
    client = FakePages([LogPage((array,), "next"), LogPage((entries()[2],), "")])
    found = reader(client).selected_events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"), limit=1)
    )
    assert [e.api_version for e in found] == ["2.5.0"]
    assert len(client.calls) == 2


def test_incomplete_selected_scan_is_unavailable_not_empty() -> None:
    """A bounded unknown scan cannot silently turn unexamined history into zero."""
    from app.sources.gcp.release_reader import LogPage

    client = FakePages([LogPage(tuple(entries()), str(i)) for i in range(1, 8)])
    with pytest.raises(SourceUnavailableError, match="scan limit"):
        reader(client).selected_events(
            EventQuery(
                window=WINDOW, release=ReleaseSelection.from_query("unknown"), limit=1
            )
        )


def test_later_page_failure_does_not_turn_into_partial_success() -> None:
    """A provider failure after valid rows still reaches the source-error path."""
    from google.api_core.exceptions import PermissionDenied

    client = FakePages([LogPage(tuple(entries()), "next"), PermissionDenied("denied")])
    with pytest.raises(SourceUnavailableError) as raised:
        reader(client).release_catalogue(WINDOW)
    assert raised.value.kind == "permission_denied"


def test_missing_metadata_stays_invalid_and_catalogue_is_not_complete() -> None:
    """Malformed contract records cannot manufacture unknown-release history."""
    bad = entries()[0]
    del bad.payload["api_version"]
    client = FakePages([LogPage((bad, entries()[2]), "")])
    result = reader(client).release_catalogue(WINDOW)
    assert result.versions == ("2.5.0",) and result.truncated
    assert not result.has_unknown


def test_gcp_source_uses_the_configured_bounded_reader() -> None:
    """The real source dispatches both discovery and selected events offline."""
    from dataclasses import replace

    from gcp_fakes import FakeLoggingClient
    from test_gcp_source import readers

    from app.sources.gcp.logging_reader import LoggingReader
    from app.sources.gcp.source import GcpSource

    client = FakePages([LogPage(tuple(entries()), "")])
    bounded = reader(client)
    configured = replace(
        readers(FakeLoggingClient()),
        releases=bounded,
        logging=LoggingReader(
            FakeLoggingClient(),
            load_contract(),
            "football-api",
            100,
            release_reader=bounded,
        ),
    )
    source = GcpSource(lambda: configured)
    assert source.release_catalogue(WINDOW).versions == ("2.5.0", "V2.6.0", "v2.6.0")
    found = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"))
    )
    assert [e.api_version for e in found] == ["2.5.0"]


def test_unconfigured_google_discovery_is_an_explicit_error() -> None:
    """Older custom reader factories do not silently pretend discovery works."""
    from gcp_fakes import FakeLoggingClient
    from test_gcp_source import readers

    from app.sources.gcp.source import GcpSource

    with pytest.raises(SourceUnavailableError, match="not configured"):
        GcpSource(lambda: readers(FakeLoggingClient())).release_catalogue(WINDOW)


@pytest.mark.parametrize("cursor", [False, True])
def test_timestamp_ties_cross_provider_pages_before_selection_limit(
    cursor: bool,
) -> None:
    """Unordered IDs at one timestamp are resolved before cutting a page."""
    from dataclasses import replace

    low, high = entries()[:2]
    low.payload.update(api_version="2.5.0", request_id="request-00000001")
    high = replace(high, timestamp=low.timestamp)
    high.payload.update(api_version="2.5.0", request_id="request-00000004")
    client = FakePages([LogPage((low,), "next"), LogPage((high,), "")])
    found = reader(client).selected_events(
        EventQuery(
            window=WINDOW,
            release=ReleaseSelection.from_query("2.5.0"),
            limit=1,
            before=low.timestamp if cursor else None,
            before_id="request-00000005" if cursor else None,
        )
    )
    assert [event.request_id for event in found] == ["request-00000004"]
    assert len(client.calls) == 2


def test_unresolved_tie_at_scan_budget_is_unavailable() -> None:
    """Enough rows cannot prove a stable page when more tied IDs are unread."""
    row = entries()[2]
    client = FakePages([LogPage((row,), str(i)) for i in range(1, 8)])
    with pytest.raises(SourceUnavailableError, match="scan limit"):
        reader(client).selected_events(
            EventQuery(
                window=WINDOW, release=ReleaseSelection.from_query("2.5.0"), limit=1
            )
        )


def test_older_timestamp_proves_selected_page_without_exhausting_history() -> None:
    """One older validated candidate closes a tie boundary without another RPC."""
    row = entries()[0]
    older = entries()[2]
    row.payload["api_version"] = "2.5.0"
    client = FakePages([LogPage((row, older), "unneeded"), RuntimeError("extra RPC")])
    found = reader(client).selected_events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"), limit=1)
    )
    assert [event.request_id for event in found] == [row.payload["request_id"]]
    assert len(client.calls) == 1
