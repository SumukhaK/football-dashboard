"""Crash source backed by the committed sample Crashlytics events."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from app.domain.crashes import CrashEvent
from app.domain.models import TimeWindow
from app.sources.crash_rows import to_crash_event
from app.sources.fixture_files import read_json

CRASHES_FILE = "crashlytics_events.json"


class FixtureCrashSource:
    """Reads the crash fixture once and answers queries in memory.

    Times are moved so the newest event sits at ``now``, as FixtureSource does,
    so the default seven-day window always shows the sample week.
    """

    def __init__(self, fixture_dir: Path, now: datetime) -> None:
        events = [to_crash_event(row) for row in read_json(fixture_dir / CRASHES_FILE)]
        shift = now - max(e.timestamp for e in events) if events else None
        self._events = sorted(
            (replace(e, timestamp=e.timestamp + shift) if shift else e for e in events),
            key=lambda e: e.timestamp,
            reverse=True,
        )

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """Return up to limit events inside the window, newest first."""
        return [e for e in self._events if _inside(e, window)][:limit]

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Return up to limit events of one issue in the window, newest first."""
        return [
            e for e in self._events if e.issue_id == issue_id and _inside(e, window)
        ][:limit]


def _inside(event: CrashEvent, window: TimeWindow) -> bool:
    """Whether the event falls in [start, end)."""
    return window.start <= event.timestamp < window.end
