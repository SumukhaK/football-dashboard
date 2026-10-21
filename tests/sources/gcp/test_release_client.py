"""The real SDK adapter uses one explicit, bounded page and no credentials."""

from collections.abc import Iterator

import pytest
from google.cloud.logging_v2.types import LogEntry
from google.cloud.logging_v2.types.logging import ListLogEntriesResponse

from app.domain.errors import SourceUnavailableError


class FakePager:
    """Any implicit request for a second SDK page fails this check."""

    def __init__(self, size: int = 1) -> None:
        self.size = size

    @property
    def pages(self) -> Iterator[ListLogEntriesResponse]:
        """Yield the already-fetched response, then reject hidden auto-paging."""
        yield ListLogEntriesResponse(
            entries=[
                LogEntry(
                    json_payload={"api_version": "2.6.0"},
                    timestamp="2026-10-08T12:00:00Z",
                    severity="INFO",
                )
            ]
            * self.size,
            next_page_token="next",
        )
        raise AssertionError("SDK auto-paging must not occur")


class FakeRpc:
    """Record supported SDK arguments without constructing a Google client."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], None, float]] = []
        self.pager = FakePager()

    def list_log_entries(
        self, request: dict[str, object], *, retry: None, timeout: float
    ) -> FakePager:
        """Return a canned SDK pager and record timeout and retry policy."""
        self.calls.append((request, retry, timeout))
        return self.pager


def test_sdk_adapter_pins_project_and_consumes_only_the_loaded_page() -> None:
    """Scope, explicit tokens, no retries and enum conversion survive adaptation."""
    from app.sources.gcp.release_client import GapicReleaseClient

    client = FakeRpc()
    builds: list[int] = []

    def build() -> FakeRpc:
        builds.append(1)
        return client

    adapter = GapicReleaseClient(build, "demo-project")
    assert builds == []
    page = adapter.read_page("safe filter", "before", 100, 3.5)
    request, retry, timeout = client.calls[0]
    assert request == {
        "resource_names": ["projects/demo-project"],
        "filter": "safe filter",
        "order_by": "timestamp desc",
        "page_size": 100,
        "page_token": "before",
    }
    assert retry is None and timeout == 3.5 and len(client.calls) == 1
    assert page.next_token == "next"
    assert page.entries[0].severity == "INFO"
    assert page.entries[0].payload == {"api_version": "2.6.0"}
    assert page.entries[0].timestamp is not None
    adapter.read_page("safe filter", "next", 100, 2)
    assert builds == [1] and len(client.calls) == 2


def test_oversized_sdk_response_is_rejected() -> None:
    """An unexpected oversized provider page cannot bypass local scan bounds."""
    from app.sources.gcp.release_client import GapicReleaseClient

    client = FakeRpc()
    client.pager = FakePager(size=101)
    with pytest.raises(SourceUnavailableError, match="oversized page"):
        GapicReleaseClient(lambda: client, "demo").read_page("filter", "", 100, 5)
