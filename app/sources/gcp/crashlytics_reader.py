"""Read Crashlytics events from the Firebase BigQuery batch export.

Every query is parameterised, filters on ``event_timestamp`` from the window
start (so BigQuery can skip the days outside the window when the table is
partitioned on it) and carries ``maximum_bytes_billed`` as a cost guard. A table that
does not exist yet means the first daily export has not run: that reads as no
events, not as an error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.api_core import exceptions as api_exceptions
from google.cloud import bigquery

from app.domain.crashes import CrashEvent
from app.domain.errors import SourceUnavailableError
from app.domain.models import TimeWindow
from app.sources.crash_rows import to_crash_event
from app.sources.gcp.errors import guarded

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
    ) -> None:
        """Build the client with ``make_client`` on the first query, not before."""
        # Any: bigquery.Client, or a test fake with the same query() method.
        self._make_client = make_client
        self._client: Any = None
        self._table = table
        self._location = location
        self._max_bytes = max_bytes_billed

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
        config = self._job_config(window, limit, extra)
        try:
            rows = guarded("BigQuery", lambda: self._query(sql, config))
        except api_exceptions.NotFound:
            return []
        except api_exceptions.GoogleAPIError as exc:
            raise SourceUnavailableError("unavailable", f"BigQuery: {exc}") from exc
        return [to_crash_event(dict(row.items())) for row in rows]

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

    def _query(self, sql: str, config: bigquery.QueryJobConfig) -> list[Any]:
        """Run the query and fetch every row, building the client if needed."""
        if self._client is None:
            self._client = self._make_client()
        job = self._client.query(sql, job_config=config, location=self._location)
        return list(job.result())


def bigquery_client(project: str, location: str) -> Any:
    """A BigQuery client for ``project``, using application default credentials."""
    return bigquery.Client(project=project, location=location)
