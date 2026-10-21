"""Fakes for the BigQuery client, shared by the Crashlytics reader tests."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core.retry import Retry
from google.cloud import bigquery

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
        on_query: Callable[[], None] | None = None,
    ) -> None:
        self.rows = [] if rows is None else rows
        self.error = error
        self.dataset = dataset if dataset is not None else FakeDataset("US")
        self.result_error = result_error
        self.on_query = on_query
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
        if self.on_query is not None:
            self.on_query()
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


def crash_source(
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
