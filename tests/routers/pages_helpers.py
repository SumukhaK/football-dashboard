"""Clients, fakes and log files shared by the route tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import REPO_ROOT, Config
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from tests.auth.console import console_client

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


def make_client() -> TestClient:
    """A signed-in test client over the fixture source with a fixed clock."""
    return console_client(clock=lambda: CLOCK_TIME)


def fixture_line(event: str) -> dict[str, Any]:
    """The first committed sample line for one event name."""
    text = (REPO_ROOT / "fixtures" / "events.jsonl").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        if payload.get("event") == event:
            return payload
    raise AssertionError(f"the fixtures hold no {event} line")


def make_local_log(tmp_path: Path) -> tuple[Path, str]:
    """A local log file, and the request id of the request line inside it.

    It holds a real request line, a real crash line and a line that is not
    JSON, so one file covers a page's data, its crash group and a skipped line.
    """
    request = fixture_line("http.request")
    crash = fixture_line("app.crash")
    path = tmp_path / "api.jsonl"
    path.write_text(
        "\n".join([json.dumps(request), json.dumps(crash), "INFO:     not json at all"])
        + "\n",
        encoding="utf-8",
    )
    return path, str(request["request_id"])


def make_local_client(path: Path) -> TestClient:
    """A signed-in test client reading the given local log file."""
    settings = Config(source="local", local_log_path=path)
    return console_client(settings, clock=lambda: CLOCK_TIME)


class BrokenSource:
    """A telemetry source whose reads always fail."""

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def trace(self, trace_id: str) -> Trace | None:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Always fails."""
        raise SourceUnavailableError("unavailable", "google is down")

    def capabilities(self) -> SourceCapabilities:
        """Reads fail, but the source still says what it can answer."""
        return ALL_CAPABILITIES
