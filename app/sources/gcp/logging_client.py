"""A bounded adapter over the Cloud Logging ListLogEntries RPC.

The high-level ``google.cloud.logging.Client.list_entries`` helper does not
expose the transport ``timeout`` or ``retry`` arguments, so a reader cannot
stop a slow page through that API. This adapter uses the supported
``LoggingServiceV2Client.list_log_entries`` arguments and rebuilds the entry
shape the existing readers consume.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import Any, Protocol, cast

from google.api_core.retry import Retry
from google.cloud.logging_v2.entries import LogEntry, StructEntry, TextEntry
from google.cloud.logging_v2.services.logging_service_v2 import (
    LoggingServiceV2Client,
)
from google.cloud.logging_v2.types import ListLogEntriesRequest
from google.cloud.logging_v2.types import LogEntry as LogEntryPB
from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]

from app.sources.gcp.entries import LogEntryLike

_SEVERITY_NAMES = {
    0: "DEFAULT",
    100: "DEBUG",
    200: "INFO",
    300: "NOTICE",
    400: "WARNING",
    500: "ERROR",
    600: "CRITICAL",
    700: "ALERT",
    800: "EMERGENCY",
}


class LoggingRpcClient(Protocol):
    """The low-level ListLogEntries method this adapter uses."""

    def list_log_entries(
        self,
        *,
        request: Any,
        retry: Retry | None = None,
        timeout: float | None = None,
    ) -> Iterable[Any]:
        """Return one page of low-level entries."""
        ...


class _EntryClient:
    """The tiny client surface ``LogEntry.from_api_repr`` needs."""

    def __init__(self, project_id: str) -> None:
        self.project = project_id

    @staticmethod
    def logger(name: str) -> None:
        """Entries are read-only here; no logger object is needed."""
        return


class GoogleLoggingClient:
    """List log entries through the SDK RPC with finite call arguments."""

    def __init__(
        self,
        project_id: str,
        client: LoggingRpcClient | None = None,
    ) -> None:
        self._project_id = project_id
        self._client = client or LoggingServiceV2Client()
        self._entry_client = _EntryClient(project_id)

    def list_entries(
        self,
        *,
        filter_: str | None = None,
        order_by: str | None = None,
        max_results: int | None = None,
        page_size: int | None = None,
        page_token: str | None = None,
        timeout: float | None = None,
        retry: Retry | None = None,
    ) -> Iterable[LogEntryLike]:
        """Return high-level entries, bounded by the supplied call options."""
        request = ListLogEntriesRequest(
            resource_names=[f"projects/{self._project_id}"],
            filter=filter_,
            order_by=order_by,
            page_size=page_size,
            page_token=page_token,
        )
        call_options: dict[str, Any] = {}
        if timeout is not None:
            call_options["timeout"] = timeout
        if retry is not None:
            call_options["retry"] = retry
        pages = self._client.list_log_entries(request=request, **call_options)
        entries = (self._entry(entry) for entry in pages)
        if max_results is None:
            return entries
        return islice(entries, max(0, max_results))

    def _entry(self, entry: Any) -> LogEntryLike:
        """Convert one proto-plus entry to the hand-written entry classes."""
        resource = MessageToDict(LogEntryPB.pb(entry))
        resource.setdefault(
            "logName", f"projects/{self._project_id}/logs/football-dashboard"
        )
        severity = resource.get("severity")
        if isinstance(severity, int):
            resource["severity"] = _SEVERITY_NAMES.get(severity, str(severity))
        entry_type = (
            StructEntry
            if "jsonPayload" in resource
            else TextEntry if "textPayload" in resource else LogEntry
        )
        return cast(
            LogEntryLike,
            entry_type.from_api_repr(  # type: ignore[no-untyped-call]
                resource, self._entry_client
            ),
        )
