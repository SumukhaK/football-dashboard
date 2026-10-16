"""Tests for mapping Crashlytics export rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.sources.crash_rows import to_crash_event

WHEN = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
FRAME = {"symbol": "a.B.c", "file": "B.kt", "line": 9, "library": "x", "blamed": True}
ROW: dict[str, Any] = {
    "event_id": "e1",
    "event_timestamp": WHEN,
    "issue_id": "i1",
    "error_type": "FATAL",
    "application": {"display_version": "2.5.0"},
    "device": {"manufacturer": "Google", "model": "Pixel 7"},
    "operating_system": {"display_version": "14"},
    "installation_uuid": "u1",
    "exceptions": [
        {"type": "E", "exception_message": "m", "nested": False, "frames": [FRAME]}
    ],
    "blame_frame": FRAME,
}


def test_maps_a_full_row() -> None:
    """Every field the page needs is carried over."""
    event = to_crash_event(ROW)
    assert (event.event_id, event.issue_id, event.error_type) == ("e1", "i1", "FATAL")
    assert (event.app_version, event.device, event.os_version) == (
        "2.5.0",
        "Google Pixel 7",
        "14",
    )
    assert event.exceptions[0].frames[0].line == 9
    assert event.blame_frame is not None and event.blame_frame.blamed


def test_string_timestamps_are_parsed() -> None:
    """The fixture file's RFC 3339 strings become aware datetimes."""
    event = to_crash_event({**ROW, "event_timestamp": "2026-10-15T08:00:00Z"})
    assert event.timestamp == WHEN


def test_null_records_become_unknown_or_empty() -> None:
    """Nulls in the export never crash the mapper."""
    nulls = (
        "error_type",
        "application",
        "device",
        "operating_system",
        "installation_uuid",
        "exceptions",
    )
    sparse = {**ROW, **dict.fromkeys(nulls), "blame_frame": {"symbol": None}}
    event = to_crash_event(sparse)
    assert (event.error_type, event.app_version, event.device) == (
        "unknown",
        "unknown",
        "unknown",
    )
    assert (event.installation_uuid, event.exceptions, event.blame_frame) == (
        "",
        (),
        None,
    )
