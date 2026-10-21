"""Release filtering over real local log snapshots, tails and appended data."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest
from release_helpers import BASE, WINDOW, fixture_releases, release_lines, request_id

from app.contract import load_contract
from app.domain.models import EventQuery
from app.domain.releases import ReleaseSelection
from app.sources import local_log_source
from app.sources.local_log_source import LocalLogSource


def write_lines(path: Path, lines: list[dict[str, Any]]) -> str:
    """Write actual JSON log lines and return the exact serialized content."""
    content = "".join(json.dumps(line) + "\n" for line in lines)
    path.write_text(content, encoding="utf-8", newline="\n")
    return content


def local_source(path: Path, max_bytes: int = 50_000_000) -> LocalLogSource:
    """Read a local file with the real contract and deterministic clock."""
    return LocalLogSource(path, max_bytes, load_contract(), lambda: BASE)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (None, [7, 6, 5, 4, 3, 2, 1, 0]),
        ("unknown", [7, 1]),
        ("2.5.0", [5, 0]),
        ("2.6.0", [2]),
        ("v2.6.0", [3]),
        ("V2.6.0", [4]),
        ("all", [6]),
        ("absent", []),
    ],
)
def test_local_and_fixture_release_results_agree(
    tmp_path: Path, version: str | None, expected: list[int]
) -> None:
    """The same mixed records produce identical scoped rows in both sources."""
    lines = release_lines()
    path = tmp_path / "api.jsonl"
    write_lines(path, lines)
    query = EventQuery(window=WINDOW, release=ReleaseSelection.from_query(version))
    found = local_source(path).events(query)
    assert [e.request_id for e in found] == [request_id(i) for i in expected]
    fixture = fixture_releases(tmp_path / "sample", lines)
    assert found == fixture.events(query)


def test_local_filter_precedes_limit_and_same_time_cursor(tmp_path: Path) -> None:
    """Unrelated rows cannot consume a selected release's first or next page."""
    lines = release_lines()
    lines[0]["timestamp"] = lines[5]["timestamp"]
    path = tmp_path / "api.jsonl"
    write_lines(path, lines)
    source = local_source(path)
    selected = ReleaseSelection.from_query("2.5.0")
    first = source.events(EventQuery(window=WINDOW, release=selected, limit=1))
    assert [e.request_id for e in first] == [request_id(5)]
    second = source.events(
        EventQuery(
            window=WINDOW,
            release=selected,
            before=first[0].timestamp,
            before_id=first[0].request_id,
            limit=1,
        )
    )
    assert [e.request_id for e in second] == [request_id(0)]


def test_snapshot_keeps_all_releases_when_selection_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing release does not reuse a previously filtered snapshot or reread."""
    path = tmp_path / "api.jsonl"
    write_lines(path, release_lines())
    source = local_source(path)
    assert len(source.events(EventQuery(window=WINDOW))) == 8

    def unexpected(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("unchanged file must reuse its complete snapshot")

    monkeypatch.setattr(local_log_source, "read_snapshot", unexpected)
    for value, expected in [("2.5.0", [5, 0]), ("2.6.0", [2]), ("unknown", [7, 1])]:
        found = source.events(
            EventQuery(window=WINDOW, release=ReleaseSelection.from_query(value))
        )
        assert [e.request_id for e in found] == [request_id(i) for i in expected]
    assert source.read_stats().events_kept == 8


def test_append_refreshes_selected_release_without_stale_rows(tmp_path: Path) -> None:
    """A size change invalidates the snapshot without relying on wall-clock time."""
    path = tmp_path / "api.jsonl"
    lines = release_lines()
    write_lines(path, lines)
    source = local_source(path)
    query = EventQuery(
        window=WINDOW, release=ReleaseSelection.from_query("2.6.0"), limit=1
    )
    assert source.events(query)[0].request_id == request_id(2)
    added = dict(
        lines[2],
        request_id=request_id(8),
        timestamp=(BASE + timedelta(minutes=8)).isoformat(),
    )
    write_lines(path, [*lines, added])
    assert source.events(query)[0].request_id == request_id(8)


def test_invalid_records_do_not_become_unknown_release_events(tmp_path: Path) -> None:
    """Missing required metadata and malformed records keep existing rejection counts."""
    path = tmp_path / "api.jsonl"
    lines = release_lines()
    missing = dict(lines[0])
    del missing["api_version"]
    bad_time = dict(lines[0], timestamp="2026-10-08T12:00:00")
    content = write_lines(path, [*lines, missing, bad_time])
    path.write_text(content + "not json\n", encoding="utf-8")
    source = local_source(path)
    unknown = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("unknown"))
    )
    assert [e.request_id for e in unknown] == [request_id(7), request_id(1)]
    stats = source.read_stats()
    assert (stats.events_kept, stats.skipped_invalid, stats.skipped_non_json) == (
        8,
        2,
        1,
    )


def test_byte_tail_limit_is_preserved_with_release_filtering(tmp_path: Path) -> None:
    """Filtering cannot recover an older release outside the bounded file tail."""
    path = tmp_path / "api.jsonl"
    lines = release_lines()
    write_lines(path, lines)
    last_line = json.dumps(lines[-1]) + "\n"
    source = local_source(path, len(last_line.encode("utf-8")))
    assert not source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"))
    )
    unknown = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("unknown"))
    )
    assert [e.request_id for e in unknown] == [request_id(7)]
    assert source.read_stats().truncated
