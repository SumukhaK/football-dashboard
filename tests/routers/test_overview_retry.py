"""Retry exhaustion renders the normal Overview source-error banner offline."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

import pytest
from google.api_core import exceptions as api_exceptions

from app.config import Config
from app.contract import load_contract
from app.dependencies import get_overview
from app.domain.models import EventQuery, TelemetryEvent
from app.services.overview import OverviewService
from app.sources.gcp.entries import LogEntryLike
from app.sources.gcp.logging_reader import LoggingReader
from tests.auth.console import console
from tests.routers.pages_helpers import BrokenSource

NOW = datetime(2026, 10, 8, 18, tzinfo=UTC)


class RetryLoggingClient:
    """A Logging client that fails locally with private SDK error details."""

    def __init__(self) -> None:
        self.calls = 0

    def list_entries(self, **kwargs: object) -> Iterable[LogEntryLike]:
        """Record one call and simulate retry exhaustion without any sleeping."""
        self.calls += 1
        raise api_exceptions.RetryError(
            "deadline exhausted private-wrapper",
            api_exceptions.ServiceUnavailable("credential-private-payload"),
        )


class RetrySource(BrokenSource):
    """Use the real Logging adapter over a client that exhausts its retries."""

    def __init__(self, reader: LoggingReader) -> None:
        self.reader = reader

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Read through the production adapter without calling Google."""
        return self.reader.events(query)


@pytest.mark.parametrize("path", ["/", "/partials/overview?hours=24"])
def test_retry_exhaustion_shows_a_safe_source_banner(path: str) -> None:
    """Full and partial pages expose a safe unavailable banner, never a 500."""
    sdk = RetryLoggingClient()
    contract = load_contract()
    reader = LoggingReader(sdk, contract, "backend", 100)
    signed = console(clock=lambda: NOW)
    service = OverviewService(
        RetrySource(reader), lambda: NOW, Config(), tuple(contract.components)
    )
    signed.app.dependency_overrides[get_overview] = lambda: service

    response = signed.client.get(path)

    assert response.status_code == 200
    assert 'role="alert"' in response.text
    assert "Telemetry is unavailable (unavailable)" in response.text
    assert "Cloud Logging: retries exhausted; try again later" in response.text
    for private in ("private-wrapper", "credential-private-payload", "Traceback"):
        assert private not in response.text
    assert sdk.calls == 1
