"""Read Crashlytics events from the Firebase BigQuery batch export.

Every query is parameterised, filters on ``event_timestamp`` from the window
start (so BigQuery can skip the days outside the window when the table is
partitioned on it) and carries ``maximum_bytes_billed`` as a cost guard. A table that
does not exist yet means the first daily export has not run: that reads as no
events, not as an error. A missing project or dataset, or a dataset in another
location, is a settings mistake instead, so it shows as an error that names the
setting to check.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from typing import Any

import requests
from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery
from google.cloud.bigquery import retry as bq_retry

from app.domain.crashes import CrashEvent
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.crash_rows import to_crash_event
from app.sources.gcp.budget import RPC_TIMEOUT_SECONDS, ReadBudget, budgeted
from app.sources.gcp.errors import guarded

# A finite HTTP timeout raises requests' own error, not a GoogleAPIError.
WAIT_TIMEOUTS = (concurrent.futures.TimeoutError, requests.exceptions.Timeout)
BUDGET_EXHAUSTED = "BigQuery: read budget exhausted; try again later"

BASE_COLUMNS = """event_id, event_timestamp, issue_id, error_type,
  application, device, operating_system, installation_uuid"""
# The list needs each exception's type and message only; naming those leaves
# keeps the frames out of the bytes scanned.
LIST_COLUMNS = f"""{BASE_COLUMNS},
  ARRAY(SELECT AS STRUCT e.type, e.exception_message, e.nested
        FROM UNNEST(exceptions) AS e) AS exceptions"""
DETAIL_COLUMNS = f"{BASE_COLUMNS}, exceptions, blame_frame"


def crash_sql(table: str, columns: str, with_issue: bool) -> str:
    """The query for one window, optionally narrowed to one issue."""
    issue = " AND issue_id = @issue_id" if with_issue else ""
    return (
        f"SELECT {columns}\nFROM `{table}`\n"
        f"WHERE event_timestamp >= @start AND event_timestamp < @end{issue}\n"
        "ORDER BY event_timestamp DESC\nLIMIT @limit"
    )


class BigQueryCrashSource:
    """Crash events from one Crashlytics export table, read-only."""

    def __init__(
        self,
        make_client: Callable[[], Any],
        table: str,
        location: str,
        max_bytes_billed: int,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build the client with ``make_client`` on the first query, not before."""
        # Any: bigquery.Client, or a test fake with the same query() method.
        self._make_client = make_client
        self._client: Any = None
        self._table = table
        self._location = location
        self._max_bytes = max_bytes_billed
        self._monotonic = monotonic

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """Return up to limit events inside the window, newest first."""
        sql = crash_sql(self._table, LIST_COLUMNS, with_issue=False)
        return self._run(sql, window, limit)

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Return up to limit events of one issue in the window, with frames."""
        sql = crash_sql(self._table, DETAIL_COLUMNS, with_issue=True)
        issue = bigquery.ScalarQueryParameter("issue_id", "STRING", issue_id)
        return self._run(sql, window, limit, issue)

    def _run(
        self,
        sql: str,
        window: TimeWindow,
        limit: int,
        *extra: bigquery.ScalarQueryParameter,
    ) -> list[CrashEvent]:
        """Run one query; a missing table is no events, other failures a banner."""
        budget = ReadBudget("BigQuery", self._monotonic)
        budget.check()
        config = self._job_config(window, limit, extra)
        try:
            rows = guarded("BigQuery", lambda: self._query(sql, config, budget))
        except api_exceptions.NotFound:
            return self._empty_if_only_table_missing(budget)
        except WAIT_TIMEOUTS as exc:
            raise SourceUnavailableError("unavailable", BUDGET_EXHAUSTED) from exc
        except api_exceptions.GoogleAPIError as exc:
            raise SourceUnavailableError("unavailable", f"BigQuery: {exc}") from exc
        return [to_crash_event(dict(row.items())) for row in rows]

    def _empty_if_only_table_missing(self, budget: ReadBudget) -> list[CrashEvent]:
        """No events when the dataset is there; a settings error when it is not."""
        dataset_id = self._table.rsplit(".", 1)[0]
        timeout = budget.timeout(RPC_TIMEOUT_SECONDS)
        try:
            dataset = guarded(
                "BigQuery",
                lambda: self._client.get_dataset(
                    dataset_id,
                    retry=bq_retry.DEFAULT_RETRY.with_timeout(timeout),
                    timeout=timeout,
                ),
            )
        except api_exceptions.NotFound as exc:
            raise SourceUnavailableError(
                "not_found",
                f"BigQuery dataset {dataset_id} does not exist; check "
                "crashlytics_project_id and crashlytics_dataset",
            ) from exc
        except WAIT_TIMEOUTS as exc:
            raise SourceUnavailableError("unavailable", BUDGET_EXHAUSTED) from exc
        except api_exceptions.GoogleAPIError as exc:
            raise SourceUnavailableError("unavailable", f"BigQuery: {exc}") from exc
        # A query run in the wrong location also reports the table as missing.
        if str(dataset.location).upper() != self._location.upper():
            raise SourceUnavailableError(
                "not_found",
                f"BigQuery dataset {dataset_id} is in {dataset.location}, not "
                f"{self._location}; check crashlytics_location",
            )
        return []

    def _job_config(
        self,
        window: TimeWindow,
        limit: int,
        extra: tuple[bigquery.ScalarQueryParameter, ...],
    ) -> bigquery.QueryJobConfig:
        """The window, limit and any extra parameters, plus the byte cap."""
        return bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start", "TIMESTAMP", window.start),
                bigquery.ScalarQueryParameter("end", "TIMESTAMP", window.end),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
                *extra,
            ],
            maximum_bytes_billed=self._max_bytes,
        )

    def _query(
        self,
        sql: str,
        config: bigquery.QueryJobConfig,
        budget: ReadBudget,
    ) -> list[Any]:
        """Run the query and fetch every row, building the client if needed."""
        if self._client is None:
            self._client = self._make_client()
        start = budget.timeout(RPC_TIMEOUT_SECONDS)
        job = self._client.query(
            sql, job_config=config, location=self._location, **_waits(start)
        )
        # result() waits for the whole query to run, so it gets what is left of
        # the read budget rather than the per-request cap.
        budget.check()
        rows = job.result(**_waits(budget.remaining()))
        return list(budgeted(rows, budget))


def _waits(seconds: float) -> dict[str, Any]:
    """BigQuery's own retry rules, cut to ``seconds``, plus the matching timeout."""
    return {
        "retry": bq_retry.DEFAULT_RETRY.with_timeout(seconds),
        "timeout": seconds,
        "job_retry": bq_retry.DEFAULT_JOB_RETRY.with_timeout(seconds),
    }


def bigquery_client(project: str, location: str) -> Any:
    """A BigQuery client for ``project``, using application default credentials."""
    return bigquery.Client(project=project, location=location)
