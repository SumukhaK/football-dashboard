"""Tests for the Crashlytics reader's read budget, timeouts and retry rules."""

from __future__ import annotations

import concurrent.futures
from typing import Any

import pytest
import requests
from bigquery_fakes import ROW, WINDOW, ExpiringRows, FakeClient
from bigquery_fakes import crash_source as _source
from google.api_core import exceptions as api_exceptions
from google.cloud.bigquery import retry as bq_retry

from app.domain.errors import SourceUnavailableError
from app.sources.gcp.budget import READ_BUDGET_SECONDS, RPC_TIMEOUT_SECONDS

EXHAUSTED = "BigQuery: read budget exhausted; try again later"


def _assert_bigquery_waits(options: dict[str, Any], seconds: float) -> None:
    """The call got BigQuery's own retry rules, cut to the given seconds."""
    assert options["timeout"] == seconds
    assert options["retry"].timeout == seconds
    assert options["retry"]._predicate is bq_retry.DEFAULT_RETRY._predicate
    assert options["job_retry"].timeout == seconds
    assert options["job_retry"]._predicate is bq_retry.DEFAULT_JOB_RETRY._predicate


def _unavailable(client: FakeClient) -> SourceUnavailableError:
    """Read crash events and return the source error it raises."""
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)
    return raised.value


def test_starting_the_query_gets_the_request_cap() -> None:
    """Starting the job is one request, so it gets the 2-second cap."""
    client = FakeClient([ROW])
    _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)
    _assert_bigquery_waits(client.query_options[0], RPC_TIMEOUT_SECONDS)


def test_waiting_for_the_result_gets_the_rest_of_the_budget() -> None:
    """The job wait covers the whole query run, so it gets what is left."""
    now = [0.0]

    def started() -> None:
        now[0] = 1.0

    client = FakeClient([ROW], on_query=started)
    _source(client, monotonic=lambda: now[0]).crash_events(WINDOW, 500)
    _assert_bigquery_waits(client.jobs[0].options, READ_BUDGET_SECONDS - 1.0)


def test_retry_rules_still_cover_rate_limits_and_request_timeouts() -> None:
    """BigQuery's rules retry what the generic transient-error rule does not."""
    client = FakeClient([ROW])
    _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)
    retry = client.query_options[0]["retry"]
    rate_limited = api_exceptions.Forbidden(
        "quota", errors=[{"reason": "rateLimitExceeded"}]
    )
    assert retry._predicate(rate_limited)
    assert retry._predicate(requests.exceptions.ReadTimeout())


def test_budget_spent_while_starting_never_waits_for_rows() -> None:
    """A budget gone by the time the job starts fails before result()."""
    now = [0.0]

    def slow_start() -> None:
        now[0] = READ_BUDGET_SECONDS + 1.0

    client = FakeClient([ROW], on_query=slow_start)
    with pytest.raises(SourceUnavailableError) as raised:
        _source(client, monotonic=lambda: now[0]).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"
    assert raised.value.detail == EXHAUSTED
    assert client.jobs[0].options == {}


def test_bounds_the_missing_table_dataset_lookup() -> None:
    """The dataset lookup used to explain a missing table is bounded too."""
    client = FakeClient(error=api_exceptions.NotFound("Table not found"))
    _source(client, monotonic=lambda: 0.0).crash_events(WINDOW, 500)
    options = client.dataset_options[0]
    assert options["timeout"] == RPC_TIMEOUT_SECONDS
    assert options["retry"].timeout == RPC_TIMEOUT_SECONDS
    assert options["retry"]._predicate is bq_retry.DEFAULT_RETRY._predicate


def test_an_expired_budget_does_not_start_the_query() -> None:
    """A budget that is already gone fails before touching BigQuery."""
    client = FakeClient()
    times = iter([0.0, READ_BUDGET_SECONDS + 1.0])
    source = _source(client, monotonic=lambda: next(times))
    with pytest.raises(SourceUnavailableError) as raised:
        source.crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"
    assert raised.value.detail == EXHAUSTED
    assert client.calls == []


def test_budget_expiry_during_row_iteration_is_a_source_error() -> None:
    """The whole-read budget is checked after each result row."""
    rows = ExpiringRows()
    client = FakeClient(rows)

    def clock() -> float:
        return READ_BUDGET_SECONDS + 1.0 if rows.expired else 0.0

    with pytest.raises(SourceUnavailableError) as raised:
        _source(client, monotonic=clock).crash_events(WINDOW, 500)
    assert raised.value.kind == "unavailable"
    assert raised.value.detail == EXHAUSTED
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "timeout",
    [concurrent.futures.TimeoutError(), requests.exceptions.ReadTimeout("slow")],
)
def test_a_result_wait_timeout_is_a_source_error(timeout: Exception) -> None:
    """A job-wait or HTTP timeout shows the banner, not the error page."""
    error = _unavailable(FakeClient(result_error=timeout))
    assert (error.kind, error.detail) == ("unavailable", EXHAUSTED)


def test_a_request_timeout_starting_the_query_is_a_source_error() -> None:
    """An HTTP timeout while starting the job also shows the banner."""
    error = _unavailable(FakeClient(error=requests.exceptions.ReadTimeout("slow")))
    assert (error.kind, error.detail) == ("unavailable", EXHAUSTED)


@pytest.mark.parametrize(
    "timeout",
    [concurrent.futures.TimeoutError(), requests.exceptions.ReadTimeout("slow")],
)
def test_a_dataset_lookup_timeout_is_a_source_error(timeout: Exception) -> None:
    """A slow table-missing diagnosis also becomes the source error."""
    client = FakeClient(
        error=api_exceptions.NotFound("Table not found"), dataset=timeout
    )
    error = _unavailable(client)
    assert (error.kind, error.detail) == ("unavailable", EXHAUSTED)
