"""Tests for the Crashlytics BigQuery reader."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from google.api_core import exceptions as api_exceptions
from google.api_core.retry import Retry
from google.cloud import bigquery

from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.gcp.budget import READ_BUDGET_SECONDS, RPC_TIMEOUT_SECONDS
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

    def __init__(
        self,
        rows: Any,
        error: Exception | None = None,
    ) -> None:
        self._rows = rows
        self._error = error
        self.options: dict[str, Any] = {}

    def result(
        self,
        *,
        retry: Retry | None = None,
        timeout: float | None = None,
        job_retry: Retry | None = None,
    ) -> Any:  # Any: canned rows or an expiring test iterator.
        """Record the result options and return the canned rows or raise."""
        self.options = {"retry": retry, "timeout": timeout, "job_retry": job_retry}
        if self._error is not None:
            raise self._error
        return self._rows


class FakeDataset:
    """A dataset as get_dataset returns it: only its location matters here."""

    def __init__(self, location: str) -> None:
        self.location = location


class FakeClient:
    """Records query calls and returns canned rows or raises."""

    def __init__(
        self,
        rows: Any = None,
        error: Exception | None = None,
        dataset: FakeDataset | Exception | None = None,
        result_error: Exception | None = None,
    ) -> None:
        self.rows = [] if rows is None else rows
        self.error = error
        self.dataset = dataset if dataset is not None else FakeDataset("US")
        self.result_error = result_error
        self.calls: list[tuple[str, bigquery.QueryJobConfig, str]] = []
        self.query_options: list[dict[str, Any]] = []
        self.jobs: list[FakeJob] = []
        self.dataset_calls: list[str] = []
        self.dataset_options: list[dict[str, Any]] = []

    def query(
        self,
        sql: str,
        job_config: bigquery.QueryJobConfig,
        location: str,
        *,
        retry: Retry | None = None,
        timeout: float | None = None,
        job_retry: Retry | None = None,
    ) -> FakeJob:
        """Record the call, then answer."""
        self.calls.append((sql, job_config, location))
        self.query_options.append(
            {"retry": retry, "timeout": timeout, "job_retry": job_retry}
        )
        if self.error is not None:
            raise self.error
        job = FakeJob(self.rows, self.result_error)
        self.jobs.append(job)
        return job

    def get_dataset(
        self,
        dataset_id: str,
        *,
        retry: Retry | None = None,
        timeout: float | None = None,
    ) -> FakeDataset:
        """Record the lookup, then answer with the dataset or raise."""
        self.dataset_calls.append(dataset_id)
        self.dataset_options.append({"retry": retry, "timeout": timeout})
        if isinstance(self.dataset, Exception):
            raise self.dataset
        return self.dataset


def _source(
    client: FakeClient,
    *,
    monotonic: Callable[[], float] | None = None,
) -> BigQueryCrashSource:
    """A reader over the fake client with a 1 GB cap and an optional test clock."""
    if monotonic is None:
        return BigQueryCrashSource(lambda: client, TABLE, "US", 1_000_000_000)
    return BigQueryCrashSource(
        lambda: client,
        TABLE,
        "US",
        1_000_000_000,
        monotonic=monotonic,
    )


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
    assert client.dataset_calls[0] == "proj.firebase_crashlytics"


def test_dataset_location_is_compared_without_case() -> None:
    """BigQuery may report the location in another case; that still matches."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"), dataset=FakeDataset("us")
    )
    assert _source(client).crash_events(WINDOW, 500) == []


def test_missing_dataset_is_a_settings_error() -> None:
    """A wrong project or dataset name names the settings, not an empty export."""
    client = FakeClient(
        error=api_exceptions.NotFound("Dataset not found"),
        dataset=api_exceptions.NotFound("Dataset not found"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "not_found"
    assert "proj.firebase_crashlytics" in raised.value.detail
    assert "crashlytics_project_id and crashlytics_dataset" in raised.value.detail


def test_dataset_in_another_location_is_a_settings_error() -> None:
    """A query in the wrong location reports the table missing; say why."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found in location US"),
        dataset=FakeDataset("EU"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).issue_events("i1", WINDOW, 50)
    assert raised.value.kind == "not_found"
    assert "is in EU, not US" in raised.value.detail
    assert "crashlytics_location" in raised.value.detail


def test_dataset_lookup_refused_maps_to_permission_denied() -> None:
    """A refused dataset lookup is the shared permission banner."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"),
        dataset=api_exceptions.PermissionDenied("no access"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "permission_denied"


def test_dataset_lookup_other_error_is_unavailable() -> None:
    """Any other failure of the lookup shows as the unavailable banner."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"),
        dataset=api_exceptions.BadRequest("bad dataset id"),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"


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


def test_bounds_the_query_and_result_waits() -> None:
    """Both starting the job and waiting for its rows use finite waits."""
    client = FakeClient([ROW])
    _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)

    query = client.query_options[0]
    assert query["timeout"] == RPC_TIMEOUT_SECONDS
    assert isinstance(query["retry"], Retry)
    assert query["retry"].deadline == RPC_TIMEOUT_SECONDS
    assert isinstance(query["job_retry"], Retry)
    assert query["job_retry"].deadline == RPC_TIMEOUT_SECONDS

    result = client.jobs[0].options
    assert result["timeout"] == RPC_TIMEOUT_SECONDS
    assert isinstance(result["retry"], Retry)
    assert result["retry"].deadline == RPC_TIMEOUT_SECONDS
    assert isinstance(result["job_retry"], Retry)
    assert result["job_retry"].deadline == RPC_TIMEOUT_SECONDS


def test_bounds_the_missing_table_dataset_lookup() -> None:
    """The dataset lookup used to explain a missing table is bounded too."""
    client = FakeClient(error=api_exceptions.NotFound("Table not found"))
    _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)

    options = client.dataset_options[0]
    assert options["timeout"] == RPC_TIMEOUT_SECONDS
    assert isinstance(options["retry"], Retry)
    assert options["retry"].deadline == RPC_TIMEOUT_SECONDS


def test_an_expired_budget_does_not_start_the_query() -> None:
    """A budget that is already gone fails before touching BigQuery."""
    client = FakeClient()
    times = iter([0.0, READ_BUDGET_SECONDS + 1.0])
    source = _source(client, monotonic=lambda: next(times))

    with pytest.raises(SourceUnavailableError) as raised:
        source.crash_events(WINDOW, 500)

    assert raised.value.kind == "unavailable"
    assert "BigQuery: read budget exhausted" in raised.value.detail
    assert client.calls == []


class ExpiringRows:
    """One row, followed by a budget that has already run out."""

    def __init__(self) -> None:
        self.expired = False
        self.sent = False

    def __iter__(self) -> Iterator[Any]:
        """Return this one-shot iterator."""
        return self

    def __next__(self) -> Any:
        """Expire the clock while yielding the first row."""
        if self.sent:
            raise StopIteration
        self.sent = True
        self.expired = True
        return ROW


def test_budget_expiry_during_row_iteration_is_a_source_error() -> None:
    """The whole-read budget is checked after each result row."""
    rows = ExpiringRows()
    client = FakeClient(rows)

    def clock() -> float:
        return READ_BUDGET_SECONDS + 1.0 if rows.expired else 0.0

    source = _source(client, monotonic=clock)

    with pytest.raises(SourceUnavailableError) as raised:
        source.crash_events(WINDOW, 500)

    assert raised.value.kind == "unavailable"
    assert "BigQuery: read budget exhausted" in raised.value.detail
    assert len(client.calls) == 1


def test_a_result_wait_timeout_is_a_source_error() -> None:
    """A BigQuery polling timeout becomes the existing source error."""
    client = FakeClient(result_error=concurrent.futures.TimeoutError())
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)

    assert raised.value.kind == "unavailable"
    assert "BigQuery: read budget exhausted" in raised.value.detail


def test_a_dataset_lookup_timeout_is_a_source_error() -> None:
    """A slow table-missing diagnosis also becomes the source error."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"),
        dataset=concurrent.futures.TimeoutError(),
    )
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client).crash_events(WINDOW, 500)

    assert raised.value.kind == "unavailable"
    assert "BigQuery: read budget exhausted" in raised.value.detail
