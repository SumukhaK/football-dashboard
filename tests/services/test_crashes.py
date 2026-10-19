"""Tests for CrashesService."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.crashes import CrashEvent, CrashException, CrashFrame
from app.domain.models import TimeWindow
from app.services.crashes import CrashesService, frame_rows

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
FRAME = CrashFrame("a.B.c", "B.kt", 12, "lib", blamed=True)
BASE = CrashEvent(
    event_id="e0",
    timestamp=NOW - timedelta(hours=1),
    issue_id="issue-a",
    error_type="FATAL",
    app_version="2.5.0",
    device="Google Pixel 7",
    os_version="14",
    installation_uuid="install-1",
    exceptions=(
        CrashException("java.lang.IllegalStateException", "boom", False, (FRAME,)),
    ),
    blame_frame=FRAME,
)


class FakeCrashSource:
    """Answers from a canned list, recording the windows it was asked for."""

    def __init__(self, events: list[CrashEvent]) -> None:
        self._events = sorted(events, key=lambda e: e.timestamp, reverse=True)
        self.windows: list[TimeWindow] = []

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """The canned events inside the window."""
        self.windows.append(window)
        inside = [e for e in self._events if window.start <= e.timestamp < window.end]
        return inside[:limit]

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """The canned events of one issue."""
        return [e for e in self.crash_events(window, limit) if e.issue_id == issue_id]


def _event(
    n: int,
    issue_id: str = BASE.issue_id,
    error_type: str = BASE.error_type,
    installation_uuid: str = BASE.installation_uuid,
    app_version: str = BASE.app_version,
) -> CrashEvent:
    """BASE with a distinct id, n days older, and the given fields."""
    return replace(
        BASE,
        event_id=f"e{n}",
        timestamp=BASE.timestamp - timedelta(days=n),
        issue_id=issue_id,
        error_type=error_type,
        installation_uuid=installation_uuid,
        app_version=app_version,
    )


def _service(events: list[CrashEvent]) -> CrashesService:
    """A service over the canned events with a fixed clock."""
    return CrashesService(FakeCrashSource(events), lambda: NOW)


def test_groups_events_by_issue_with_counts_and_times() -> None:
    """One row per issue: events, distinct installs, first/last seen, versions."""
    events = [
        _event(0),
        _event(1, installation_uuid="install-2", app_version="2.4.1"),
        _event(2),
        _event(3, issue_id="issue-b", error_type="ANR", installation_uuid=""),
    ]
    first, second = _service(events).build_for_hours(168).issues
    assert first.issue_id == "issue-a"
    assert (first.events, first.installs) == (3, 2)
    assert first.first_seen == events[2].timestamp
    assert first.last_seen == events[0].timestamp
    assert first.app_versions == ("2.4.1", "2.5.0")
    assert (first.title, first.subtitle) == ("java.lang.IllegalStateException", "boom")
    assert (second.issue_id, second.error_type, second.installs) == (
        "issue-b",
        "ANR",
        0,
    )


def test_issues_are_newest_first_by_last_seen() -> None:
    """An issue seen more recently comes first even with fewer events."""
    events = [_event(1), _event(2), _event(0, issue_id="recent")]
    issues = _service(events).build_for_hours(168).issues
    assert [row.issue_id for row in issues] == ["recent", "issue-a"]


def test_totals_by_type_list_known_types_first_even_at_zero() -> None:
    """FATAL, NON_FATAL and ANR always show; other types follow by name."""
    events = [_event(0), _event(1), _event(2, error_type="NON_FATAL")]
    events.append(_event(3, error_type="OTHER"))
    totals = _service(events).build_for_hours(168).totals
    assert totals == (("FATAL", 2), ("NON_FATAL", 1), ("ANR", 0), ("OTHER", 1))


def test_title_falls_back_to_blame_frame_then_type() -> None:
    """Without exceptions the blame frame names the issue, then the type."""
    framed = replace(_event(0), exceptions=())
    bare = replace(_event(1, issue_id="b"), exceptions=(), blame_frame=None)
    issues = _service([framed, bare]).build_for_hours(168).issues
    assert [(row.title, row.subtitle) for row in issues] == [
        ("a.B.c", ""),
        ("FATAL", ""),
    ]


def test_no_events_is_an_empty_model() -> None:
    """No rows gives empty issues and zero totals, not an error."""
    model = _service([]).build_for_hours(168)
    assert model.issues == ()
    assert model.totals == (("FATAL", 0), ("NON_FATAL", 0), ("ANR", 0))
    assert model.total_events == 0
    assert not model.truncated


def test_the_type_filter_narrows_the_rows_but_not_the_chip_counts() -> None:
    """A chip counts the whole window, even while it narrows the list."""
    events = [_event(0), _event(1, error_type="NON_FATAL", issue_id="issue-b")]
    model = _service(events).build_for_hours(168, "NON_FATAL")
    assert [row.issue_id for row in model.issues] == ["issue-b"]
    assert model.type_filter == "NON_FATAL"
    assert model.total_events == 2
    assert [(chip.label, chip.count) for chip in model.type_chips] == [
        ("All", 2),
        ("Fatal", 1),
        ("Non-fatal", 1),
        ("Not responding", 0),
    ]


def test_type_chips_carry_the_label_and_the_link_of_their_own_type() -> None:
    """Every chip links to the list it filters, and All keeps no type."""
    chips = _service([_event(0)]).build_for_hours(24).type_chips
    assert [chip.value for chip in chips] == [None, "FATAL", "NON_FATAL", "ANR"]
    assert chips[0].link == "/crashes?hours=24"
    assert chips[1].link == "/crashes?hours=24&type=FATAL"
    assert chips[3].label == "Not responding"


def test_resolve_type_offers_the_three_known_types() -> None:
    """Only the types the page has a chip for can be filtered on."""
    assert CrashesService.resolve_type(None) is None
    assert CrashesService.resolve_type("") is None
    assert CrashesService.resolve_type("FATAL") == "FATAL"
    with pytest.raises(ValueError):
        CrashesService.resolve_type("OTHER")


def test_issue_rows_split_the_class_name_and_carry_their_links() -> None:
    """A row names the short class and its package, and links to its own views."""
    row = _service([_event(0)]).build_for_hours(168).issues[0]
    assert (row.short_name, row.package) == ("IllegalStateException", "java.lang")
    assert row.title == "java.lang.IllegalStateException"
    assert (row.type_label, row.type_tone) == ("Fatal", "fail")
    assert row.link == "/crashes/issue-a?hours=168"
    assert row.panel_link == "/partials/crashes/issue-a/panel?hours=168"
    assert row.open_link == "/crashes?hours=168&open=issue-a"


def test_frame_rows_split_the_symbol_and_mark_the_first_app_frame() -> None:
    """The first frame in the app's own code is the marked one."""
    frames = (
        CrashFrame("kotlinx.serialization.Plugin.throw", "P.kt", 40, None, True),
        CrashFrame("com.example.app.Chat.send", "C.kt", 47, None, False),
        CrashFrame("com.example.app.Chat.ask", "C.kt", 54, None, False),
    )
    rows = frame_rows(frames, "com.example.app")
    assert [row.method for row in rows] == ["throw", "send", "ask"]
    assert rows[0].package == "kotlinx.serialization.Plugin"
    assert [row.in_app for row in rows] == [False, True, True]
    assert [row.first_app for row in rows] == [False, True, False]


def test_no_frame_in_the_app_marks_nothing() -> None:
    """Frames from libraries alone leave the first-app mark unused."""
    frames = (CrashFrame("okhttp3.internal.Http2.waitForIo", None, None, None, True),)
    rows = frame_rows(frames, "com.example.app")
    assert [row.in_app for row in rows] == [False]
    assert [row.first_app for row in rows] == [False]
    assert (rows[0].file, rows[0].line) == (None, None)


def test_a_package_prefix_alone_is_not_the_app() -> None:
    """A neighbouring package that starts the same way is still a library."""
    frames = (CrashFrame("com.example.application.Main.run", None, None, None, True),)
    assert frame_rows(frames, "com.example.app")[0].in_app is False


def test_default_window_is_seven_days() -> None:
    """No requested window means 168 hours; an unsupported one is refused."""
    assert CrashesService.resolve_hours(None) == 168
    assert CrashesService.resolve_hours(24) == 24
    with pytest.raises(ValueError):
        CrashesService.resolve_hours(5)


def test_detail_has_recent_events_and_latest_frames() -> None:
    """The detail lists the issue's events and the newest event's frames."""
    older = replace(_event(1), blame_frame=CrashFrame("old", None, None, None, False))
    service = _service([_event(0), older, _event(2, issue_id="b")])
    detail = service.detail_for_hours("issue-a", 168)
    assert detail is not None
    assert detail.issue.events == 2
    assert [row.timestamp for row in detail.events] == [
        BASE.timestamp,
        older.timestamp,
    ]
    assert detail.blame_frame == FRAME
    assert [(frame.method, frame.file, frame.line) for frame in detail.frames] == [
        ("c", "B.kt", 12)
    ]
    assert detail.events[0].device == "Google Pixel 7"


def test_detail_of_unknown_issue_is_none() -> None:
    """An issue with no events in the window has no detail."""
    assert _service([_event(0)]).detail_for_hours("nope", 168) is None


class SilentIssueSource(FakeCrashSource):
    """Lists an issue but answers none of its events."""

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Answer nothing for any issue."""
        return []


def test_detail_of_an_issue_whose_events_are_missing_is_none() -> None:
    """A source that lists an issue but answers no events leaves no detail."""
    service = CrashesService(SilentIssueSource([_event(0)]), lambda: NOW)
    assert service.detail_for_hours("issue-a", 168) is None


def test_detail_marks_the_first_frame_in_the_service_s_own_package() -> None:
    """The service's app package decides which frame is the app's own code."""
    frame = CrashFrame("com.example.app.Match.show", "Match.kt", 40, None, True)
    event = replace(
        _event(0),
        exceptions=(
            CrashException("java.lang.IllegalStateException", "boom", False, (frame,)),
        ),
        blame_frame=frame,
    )
    service = CrashesService(FakeCrashSource([event]), lambda: NOW, "com.example.app")
    detail = service.detail_for_hours("issue-a", 168)
    assert detail is not None
    assert [(row.method, row.first_app) for row in detail.frames] == [("show", True)]


def test_window_uses_the_clock() -> None:
    """The window ends at the clock's interval and spans the requested hours."""
    source = FakeCrashSource([])
    CrashesService(source, lambda: NOW).build_for_hours(24)
    window = source.windows[0]
    assert window.end - window.start == timedelta(hours=24)
    assert window.start < NOW <= window.end
