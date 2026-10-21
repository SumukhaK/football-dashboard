"""Builders shared by the LocalLogSource tests: a fixed clock, log lines and files."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from app.config import REPO_ROOT
from app.contract import Contract
from app.domain.models import MAX_QUERY_LIMIT, EventQuery, TimeWindow
from app.sources.local_log_source import (
    LocalLogSource,
)

CLOCK_TIME = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)


WINDOW = TimeWindow(
    start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2027, 1, 1, tzinfo=UTC)
)


CRASH_ROUTE = "/v2/teams/{team}/outlook"


# Every query a test reads with, unless the test needs another one.
EVERYTHING = EventQuery(window=WINDOW, limit=MAX_QUERY_LIMIT)


def make_source(
    path: Path, contract: Contract, max_bytes: int = 50_000_000
) -> LocalLogSource:
    """A local log source over the given file, with a fixed clock."""
    return LocalLogSource(path, max_bytes, contract, lambda: CLOCK_TIME)


def write_log(path: Path, lines: Iterable[str]) -> Path:
    """Write the given raw lines to a log file, one per line."""
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def request_line(
    request_id: str = "req-00000001",
    timestamp: str = "2026-10-08T17:00:00.000Z",
    severity: str = "INFO",
) -> str:
    """One contract-shaped http.request line, as the backend writes it."""
    return json.dumps(
        {
            "timestamp": timestamp,
            "severity": severity,
            "message": "GET /v2/fixtures 200 in 12ms",
            "logger": "backend.app.main",
            "event": "http.request",
            "request_id": request_id,
            "logging.googleapis.com/trace": None,
            "logging.googleapis.com/spanId": None,
            "trace_id": None,
            "service": "football-api",
            "revision": None,
            "api_version": "2.0.0",
            "contract_version": "1.1.0",
            "attributes": {
                "method": "GET",
                "route": "/v2/fixtures",
                "status": 200,
                "duration_ms": 12.5,
                "error_code": None,
            },
        }
    )


def crash_line(
    exception_type: str = "builtins.ZeroDivisionError",
    timestamp: str = "2026-10-08T17:00:00.000Z",
    route: str = CRASH_ROUTE,
) -> str:
    """One contract-shaped app.crash line; its message is the traceback."""
    message = (
        "Traceback (most recent call last):\n"
        '  File "app/main.py", line 42, in handler\n'
        "    1 / 0\n"
        f"{exception_type}: division by zero"
    )
    return json.dumps(
        {
            "timestamp": timestamp,
            "severity": "ERROR",
            "message": message,
            "logger": "backend.app.main",
            "event": "app.crash",
            "request_id": "req-00000009",
            "logging.googleapis.com/trace": None,
            "logging.googleapis.com/spanId": None,
            "trace_id": None,
            "service": "football-api",
            "revision": None,
            "api_version": "2.0.0",
            "contract_version": "1.1.0",
            "attributes": {"route": route, "exception_type": exception_type},
        }
    )


def fixture_log_lines(count: int = 5) -> list[str]:
    """The first lines of the committed sample events, as raw log lines."""
    text = (REPO_ROOT / "fixtures" / "events.jsonl").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[:count]
