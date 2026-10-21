"""Google SDK adapter for exactly one explicitly budgeted Logging page."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client
from google.cloud.logging_v2.types import LogEntry
from google.cloud.logging_v2.types.logging import ListLogEntriesResponse

from app.contract import Contract
from app.domain.errors import SourceUnavailableError
from app.sources.gcp.release_reader import LogPage, ReleaseReader


class _Pager(Protocol):
    """The first already-loaded SDK response, without implicit iteration."""

    @property
    def pages(self) -> Iterator[ListLogEntriesResponse]: ...


class RpcLoggingClient(Protocol):
    """The supported GAPIC one-call interface used by the adapter."""

    def list_log_entries(
        self, request: dict[str, object], *, retry: None, timeout: float
    ) -> _Pager:
        """Fetch a first page with an explicit timeout and no retries."""
        ...


@dataclass(frozen=True)
class _Entry:
    """The same structural entry fields the existing validator consumes."""

    payload: object
    timestamp: datetime | None
    severity: str | None
    trace: str | None
    span_id: str | None


def _entry(entry: LogEntry) -> _Entry:
    """Decode SDK enums and JSON through its supported public conversion."""
    raw = LogEntry.to_dict(
        entry, use_integers_for_enums=False, preserving_proto_field_name=False
    )
    severity = raw.get("severity")
    return _Entry(
        raw.get("jsonPayload"),
        entry.timestamp,
        severity if isinstance(severity, str) else None,
        entry.trace or None,
        entry.span_id or None,
    )


class GapicReleaseClient:
    """Adapt one RPC response; caller controls all pagination and budget."""

    def __init__(
        self, build_client: Callable[[], RpcLoggingClient], project_id: str
    ) -> None:
        self._build_client = build_client
        self._client: RpcLoggingClient | None = None
        self._project_id = project_id

    def read_page(
        self, log_filter: str, token: str, size: int, timeout: float
    ) -> LogPage:
        """Fetch only the already-loaded response, with retries disabled."""
        if self._client is None:
            self._client = self._build_client()
        pager = self._client.list_log_entries(
            request={
                "resource_names": [f"projects/{self._project_id}"],
                "filter": log_filter,
                "order_by": "timestamp desc",
                "page_size": size,
                "page_token": token,
            },
            retry=None,
            timeout=timeout,
        )
        page = next(pager.pages)
        if len(page.entries) > size:
            raise SourceUnavailableError(
                "invalid_data", "Cloud Logging: oversized page"
            )
        return LogPage(
            tuple(_entry(entry) for entry in page.entries), page.next_page_token
        )


def google_release_reader(
    project_id: str, contract: Contract, service: str
) -> ReleaseReader:
    """Build a bounded reader while deferring SDK client/credential creation."""
    return ReleaseReader(
        GapicReleaseClient(LoggingServiceV2Client, project_id), contract, service
    )
