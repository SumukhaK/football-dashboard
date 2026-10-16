"""Map Crashlytics export rows onto domain crash events.

The fixture file and BigQuery both give rows in the export's shape, nested
records as dicts and repeated records as lists, so one mapper serves both.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.domain.crashes import CrashEvent, CrashException, CrashFrame

UNKNOWN = "unknown"
Row = Mapping[str, Any]  # Any: export rows hold mixed, untyped values.


def to_crash_event(row: Row) -> CrashEvent:
    """Map one export row; missing records become 'unknown' or empty."""
    device = _record(row, "device")
    blame = row.get("blame_frame")
    return CrashEvent(
        event_id=str(row["event_id"]),
        timestamp=_time(row["event_timestamp"]),
        issue_id=str(row["issue_id"]),
        error_type=row.get("error_type") or UNKNOWN,
        app_version=_record(row, "application").get("display_version") or UNKNOWN,
        device=_device(device),
        os_version=_record(row, "operating_system").get("display_version") or UNKNOWN,
        installation_uuid=row.get("installation_uuid") or "",
        exceptions=tuple(_exception(e) for e in row.get("exceptions") or ()),
        blame_frame=_frame(blame) if blame and blame.get("symbol") else None,
    )


def _record(row: Row, name: str) -> Row:
    """A nested record, or an empty one when the export left it null."""
    value = row.get(name)
    return value if isinstance(value, Mapping) else {}


def _time(value: datetime | str) -> datetime:
    """BigQuery gives datetimes; the fixture file gives RFC 3339 strings."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _device(device: Row) -> str:
    """'manufacturer model', or 'unknown' when both are missing."""
    parts = [device.get("manufacturer"), device.get("model")]
    return " ".join(str(part) for part in parts if part) or UNKNOWN


def _exception(item: Row) -> CrashException:
    """One exception with its frames (the list query leaves frames out)."""
    return CrashException(
        type=item.get("type") or UNKNOWN,
        message=item.get("exception_message") or "",
        nested=bool(item.get("nested")),
        frames=tuple(_frame(frame) for frame in item.get("frames") or ()),
    )


def _frame(item: Row) -> CrashFrame:
    """One stack frame."""
    return CrashFrame(
        symbol=item.get("symbol") or UNKNOWN,
        file=item.get("file"),
        line=item.get("line"),
        library=item.get("library"),
        blamed=bool(item.get("blamed")),
    )
