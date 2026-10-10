"""Fakes for the Google clients, shared by the GCP reader tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.sources.gcp.entries import SPAN_KEY, TRACE_KEY

LIFTED_KEYS = ("timestamp", "severity", TRACE_KEY, SPAN_KEY)


@dataclass
class FakeResource:
    """A monitored resource with labels."""

    labels: Mapping[str, str] = field(default_factory=dict)


@dataclass
class FakeEntry:
    """A Cloud Logging entry as the client library returns it."""

    payload: Any
    timestamp: datetime | None
    severity: str | None = None
    trace: str | None = None
    span_id: str | None = None
    resource: FakeResource | None = None


class FakeLoggingClient:
    """Records list_entries calls and yields canned entries or raises."""

    def __init__(self, entries: Iterable[Any] = (), error: Exception | None = None):
        self.entries = list(entries)
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def list_entries(self, **kwargs: Any) -> Iterable[Any]:
        """Return the canned entries, or raise the canned error."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return iter(self.entries)


def as_cloud_entry(line: dict[str, Any]) -> FakeEntry:
    """Turn a contract line into an entry, lifting keys as Cloud Logging does."""
    payload = {k: v for k, v in line.items() if k not in LIFTED_KEYS}
    trace_id = line.get("trace_id")
    return FakeEntry(
        payload=payload,
        timestamp=datetime.fromisoformat(line["timestamp"]),
        severity=line["severity"],
        trace=f"projects/demo/traces/{trace_id}" if trace_id else None,
        span_id=line.get(SPAN_KEY),
    )
