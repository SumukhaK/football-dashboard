"""Tests for FixtureSource against the committed fixtures."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.contract import Contract, load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TelemetryEvent, TimeWindow
from app.sources.fixture_source import FixtureSource

FIXTURES = REPO_ROOT / "fixtures"
FIXTURE_END = datetime(2026, 10, 8, 18, 0, tzinfo=UTC)
ALL_DAY = TimeWindow(start=FIXTURE_END - timedelta(days=2), end=FIXTURE_END)
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def contract() -> Contract:
    """The committed contract."""
    return load_contract()


@pytest.fixture(scope="module")
def source(contract: Contract) -> FixtureSource:
    """A fixture source without time re-basing."""
    return FixtureSource(FIXTURES, contract)


def everything(source: FixtureSource) -> list[TelemetryEvent]:
    """Return every event in the fixture days, newest first."""
    return source.events(EventQuery(window=ALL_DAY, limit=5000))


def test_loads_every_event_line(source: FixtureSource) -> None:
    """Every non-empty line of events.jsonl becomes an event."""
    lines = (FIXTURES / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(everything(source)) == len([line for line in lines if line.strip()])


def test_request_id_returns_the_whole_request(source: FixtureSource) -> None:
    """All lines of one chat request share its request_id."""
    chat = source.events(
        EventQuery(window=ALL_DAY, events=("assistant.answer",), limit=1)
    )[0]
    lines = source.events(
        EventQuery(window=ALL_DAY, request_id=chat.request_id, limit=5000)
    )
    names = {line.event for line in lines}
    assert {"http.request", "assistant.answer"} <= names
    assert all(line.request_id == chat.request_id for line in lines)


def test_min_status_returns_only_server_errors(source: FixtureSource) -> None:
    """min_status=500 keeps only lines whose status is 5xx."""
    query = EventQuery(window=ALL_DAY, min_status=500, limit=5000)
    found = source.events(query)
    assert found
    assert {e.event for e in found} <= {"http.request", "app.error"}
    assert all(int(str(e.attributes["status"])) >= 500 for e in found)


def test_newest_first_and_limit(source: FixtureSource) -> None:
    """Results are newest first and capped at the limit."""
    found = source.events(EventQuery(window=ALL_DAY, limit=50))
    assert len(found) == 50
    stamps = [e.timestamp for e in found]
    assert stamps == sorted(stamps, reverse=True)


def test_trace_lookup(source: FixtureSource) -> None:
    """A chat request's trace is found; an unknown id gives None."""
    chat = source.events(
        EventQuery(window=ALL_DAY, route="/v2/assistant/chat", limit=1)
    )[0]
    assert chat.trace_id is not None
    trace = source.trace(chat.trace_id)
    assert trace is not None
    assert trace.root.name == "POST /v2/assistant/chat"
    assert source.trace("0" * 32) is None


def test_error_groups_and_platform_events(source: FixtureSource) -> None:
    """The four error groups and four platform events fall in the fixture days."""
    assert len(source.error_groups(ALL_DAY)) == 4
    assert len(source.platform_events(ALL_DAY)) == 4


def test_rebasing_moves_every_file(source: FixtureSource, contract: Contract) -> None:
    """With now set, the newest event sits at now and everything shifts with it."""
    rebased = FixtureSource(FIXTURES, contract, now=NOW)
    newest = everything(source)[0]
    shifted_window = TimeWindow(start=ALL_DAY.start, end=NOW + timedelta(seconds=1))
    moved = rebased.events(EventQuery(window=shifted_window, limit=1))[0]
    assert moved.timestamp == NOW
    shift = NOW - newest.timestamp
    window = TimeWindow(start=ALL_DAY.start + shift, end=ALL_DAY.end + shift)
    old_groups = source.error_groups(ALL_DAY)
    assert [g.last_seen + shift for g in old_groups] == [
        g.last_seen for g in rebased.error_groups(window)
    ]
    old_platform = source.platform_events(ALL_DAY)
    assert [p.timestamp + shift for p in old_platform] == [
        p.timestamp for p in rebased.platform_events(window)
    ]
    trace_id = old_trace_id(source)
    old_root = source.trace(trace_id)
    new_root = rebased.trace(trace_id)
    assert old_root is not None and new_root is not None
    assert new_root.root.start == old_root.root.start + shift


def old_trace_id(source: FixtureSource) -> str:
    """Return the trace id of one chat request."""
    chat = source.events(
        EventQuery(window=ALL_DAY, route="/v2/assistant/chat", limit=1)
    )[0]
    assert chat.trace_id is not None
    return chat.trace_id


def copy_fixtures(target: Path) -> Path:
    """Copy the committed fixtures into a temporary folder."""
    shutil.copytree(FIXTURES, target)
    return target


def test_invalid_line_is_a_loud_error(tmp_path: Path, contract: Contract) -> None:
    """A line that breaks the contract stops loading and names its line number."""
    folder = copy_fixtures(tmp_path / "fixtures")
    events = folder / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    lines[2] = '{"event": "http.request"}'
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(SourceUnavailableError) as raised:
        FixtureSource(folder, contract)
    assert raised.value.kind == "invalid_data"
    assert "line 3" in raised.value.detail


def test_missing_file_is_not_found(tmp_path: Path, contract: Contract) -> None:
    """A missing fixture file is reported as not_found."""
    folder = copy_fixtures(tmp_path / "fixtures")
    (folder / "traces.json").unlink()
    with pytest.raises(SourceUnavailableError) as raised:
        FixtureSource(folder, contract)
    assert raised.value.kind == "not_found"


def test_broken_json_is_invalid_data(tmp_path: Path, contract: Contract) -> None:
    """A JSON file that does not parse is reported as invalid_data."""
    folder = copy_fixtures(tmp_path / "fixtures")
    (folder / "error_groups.json").write_text("[{", encoding="utf-8")
    with pytest.raises(SourceUnavailableError) as raised:
        FixtureSource(folder, contract)
    assert raised.value.kind == "invalid_data"
