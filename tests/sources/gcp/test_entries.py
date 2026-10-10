"""Tests for rebuilding contract lines from Cloud Logging entries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from gcp_fakes import FakeEntry, as_cloud_entry

from app.contract import load_contract
from app.sources.gcp.entries import (
    SPAN_KEY,
    TRACE_KEY,
    convert_entries,
    to_contract_line,
)


def traced_line(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the first fixture line that carries a trace."""
    return next(line for line in lines if line.get("trace_id"))


def test_lifted_keys_are_restored(fixture_lines: list[dict[str, Any]]) -> None:
    """Severity, timestamp, trace and span ID come back from the entry."""
    original = traced_line(fixture_lines)
    rebuilt = to_contract_line(as_cloud_entry(original))
    assert rebuilt["severity"] == original["severity"]
    assert rebuilt["timestamp"] == original["timestamp"]
    assert rebuilt[TRACE_KEY].endswith(original["trace_id"])
    assert rebuilt[SPAN_KEY] == original[SPAN_KEY]


def test_null_trace_and_span_stay_null() -> None:
    """Entries without a trace get explicit nulls, as the contract requires."""
    entry = FakeEntry(payload={}, timestamp=datetime(2026, 10, 8, tzinfo=UTC))
    rebuilt = to_contract_line(entry)
    assert rebuilt[TRACE_KEY] is None
    assert rebuilt[SPAN_KEY] is None


def test_text_payload_becomes_an_empty_line() -> None:
    """A text entry has no JSON fields to keep."""
    entry = FakeEntry(payload="plain text", timestamp=None, severity="INFO")
    assert set(to_contract_line(entry)) == {"severity", TRACE_KEY, SPAN_KEY}


def test_convert_keeps_valid_and_counts_invalid(
    fixture_lines: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """Valid entries become events; ones that break the contract are counted."""
    good = [as_cloud_entry(line) for line in fixture_lines[:5]]
    bad = FakeEntry(payload={"event": "http.request"}, timestamp=None)
    result = convert_entries([*good, bad], load_contract())
    assert len(result.events) == 5
    assert result.skipped == 1
    assert "Skipped 1 log entries" in caplog.text
    assert result.events[0].timestamp == datetime.fromisoformat(
        fixture_lines[0]["timestamp"]
    )
