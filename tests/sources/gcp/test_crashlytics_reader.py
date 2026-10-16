"""Tests for the Crashlytics BigQuery reader."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery

from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.gcp.crashlytics_reader import BigQueryCrashSource

START = datetime(2026, 10, 9, tzinfo=UTC)
WINDOW = TimeWindow(start=START, end=START + timedelta(days=7))
TABLE = "proj.firebase_crashlytics.com_footballintelligence_app_stg_ANDROID"
ROW = {
    "event_id": "e1",
    "event_timestamp": START + timedelta(days=1),
    "issue_id": "i1",
    "error_type": "FATAL",
    "application": {"display_version": "2.5.0"},
    "device": {"manufacturer": "Google", "model": "Pixel 7"},
    "operating_system": {"display_version": "14"},
    "installation_uuid": "u1",
    "exceptions": [{"type": "E", "exception_message": "m", "nested": False}],
}


class FakeJob:
    """A finished query job."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def result(self) -> list[dict[str, Any]]:
        """The canned rows (dicts have items(), like bigquery.Row)."""
        return self._rows


class FakeClient:
    """Records query calls and returns canned rows or raises."""

    def __init__(
        self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None
    ) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, bigquery.QueryJobConfig, str]] = []

    def query(
        self, sql: str, job_config: bigquery.QueryJobConfig, location: str
    ) -> FakeJob:
        """Record the call, then answer."""
        self.calls.append((sql, job_config, location))
        if self.error is not None:
            raise self.error
        return FakeJob(self.rows)


def _source(client: FakeClient) -> BigQueryCrashSource:
    """A reader over the fake client with a 1 GB cap."""
    return BigQueryCrashSource(lambda: client, TABLE, "US", 1_000_000_000)


def _params(config: bigquery.QueryJobConfig) -> dict[str, Any]:
    """The query parameters by name."""
    return {p.name: p.value for p in config.query_parameters}


def test_list_query_is_parameterised_filtered_and_capped() -> None:
    """The SQL filters on the window, binds parameters and caps bytes billed."""
    client = FakeClient([ROW])
    events = _source(client).crash_events(WINDOW, 500)
    sql, config, location = client.calls[0]
    assert f"FROM `{TABLE}`" in sql
    assert "WHERE event_timestamp >= @start AND event_timestamp < @end" in sql
    assert "LIMIT @limit" in sql and "issue_id = @issue_id" not in sql
    assert "frames" not in sql and "blame_frame" not in sql
    assert _params(config) == {"start": WINDOW.start, "end": WINDOW.end, "limit": 500}
    assert config.maximum_bytes_billed == 1_000_000_000
    assert location == "US"
    assert [e.event_id for e in events] == ["e1"]


def test_issue_query_binds_the_issue_and_reads_frames() -> None:
    """The detail query narrows by a bound issue id and selects the stack."""
    client = FakeClient([ROW])
    _source(client).issue_events("i1", WINDOW, 50)
    sql, config, _ = client.calls[0]
    assert "AND issue_id = @issue_id" in sql
    assert "event_timestamp >= @start" in sql
    assert "exceptions, blame_frame" in sql
    assert _params(config)["issue_id"] == "i1"
    assert config.maximum_bytes_billed == 1_000_000_000


def test_missing_table_is_no_events() -> None:
    """Before the first daily export the table does not exist: no events."""
    client = FakeClient(error=api_exceptions.NotFound("Table not found"))
    assert _source(client).crash_events(WINDOW, 500) == []
    assert _source(client).issue_events("i1", WINDOW, 50) == []


def test_permission_errors_map_to_permission_denied() -> None:
    """A refused read becomes the shared source error, by kind."""
    client = FakeClient(error=api_exceptions.PermissionDenied("no access"))
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "permission_denied"


def test_other_google_errors_become_unavailable() -> None:
    """Anything else from Google, such as the byte cap, shows as a banner."""
    client = FakeClient(error=api_exceptions.BadRequest("bytesBilledLimitExceeded"))
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"
    assert "bytesBilledLimitExceeded" in raised.value.detail


def test_client_is_built_once_on_first_query() -> None:
    """Building the reader never calls Google; the first query builds the client."""
    built: list[FakeClient] = []

    def make() -> FakeClient:
        built.append(FakeClient())
        return built[-1]

    source = BigQueryCrashSource(make, TABLE, "US", 1)
    assert built == []
    source.crash_events(WINDOW, 1)
    source.crash_events(WINDOW, 1)
    assert len(built) == 1
