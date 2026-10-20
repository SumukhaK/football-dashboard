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


def test_convert_first_malformed_keeps_second(
    fixture_lines: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed first record does not discard a valid second record."""
    line0 = dict(fixture_lines[0])
    line0["attributes"] = None  # Malformed attributes as in B1
    entry0 = as_cloud_entry(line0)

    line1 = dict(fixture_lines[1])
    entry1 = as_cloud_entry(line1)

    result = convert_entries([entry0, entry1], load_contract())
    assert len(result.events) == 1
    assert result.skipped == 1
    assert result.events[0].request_id == line1.get("request_id")
    assert "Skipped 1 log entries that do not match the contract" in caplog.text
    assert "invalid_attributes: 1" in caplog.text


def test_convert_protects_domain_conversion_failure(
    fixture_lines: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """A record failing domain conversion is caught within the per-record boundary."""
    good_line = dict(fixture_lines[0])
    good_entry = as_cloud_entry(good_line)

    # An entry whose payload is not a valid dict/mapping
    bad_entry = FakeEntry(payload="invalid text payload", timestamp=None, severity=None)

    result = convert_entries([good_entry, bad_entry], load_contract())
    assert len(result.events) == 1
    assert result.skipped == 1
    assert result.events[0].request_id == good_line.get("request_id")


def test_convert_batches_mixed_all_invalid_and_empty(
    fixture_lines: list[dict[str, Any]],
) -> None:
    """Mixed, all-invalid, and empty batches preserve order and accurate skip counts."""
    contract = load_contract()

    # Empty batch
    empty_res = convert_entries([], contract)
    assert empty_res.events == []
    assert empty_res.skipped == 0

    # All-invalid batch
    bad1 = FakeEntry(payload={"event": "http.request"}, timestamp=None)
    bad2 = FakeEntry(payload=None, timestamp=None)
    bad3 = FakeEntry(payload={"contract_version": "9.9.9"}, timestamp=None)
    all_bad_res = convert_entries([bad1, bad2, bad3], contract)
    assert all_bad_res.events == []
    assert all_bad_res.skipped == 3

    # Mixed batch: valid, bad, valid, bad
    v1 = as_cloud_entry(dict(fixture_lines[0]))
    b1 = FakeEntry(payload={"event": "http.request"}, timestamp=None)
    v2 = as_cloud_entry(dict(fixture_lines[1]))
    b2 = FakeEntry(payload=None, timestamp=None)
    mixed_res = convert_entries([v1, b1, v2, b2], contract)
    assert len(mixed_res.events) == 2
    assert mixed_res.skipped == 2
    assert mixed_res.events[0].request_id == fixture_lines[0].get("request_id")
    assert mixed_res.events[1].request_id == fixture_lines[1].get("request_id")


def test_convert_warnings_do_not_leak_payloads(
    fixture_lines: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    """Warnings report counts and field categories without leaking raw payloads or tokens."""
    sensitive_token = "SUPER-SECRET-AUTH-TOKEN-XYZ123"
    bad_line = dict(fixture_lines[0])
    bad_line["attributes"] = sensitive_token  # string instead of mapping

    entry = as_cloud_entry(bad_line)
    result = convert_entries([entry], load_contract())
    assert result.skipped == 1
    assert sensitive_token not in caplog.text
    assert "invalid_attributes: 1" in caplog.text
