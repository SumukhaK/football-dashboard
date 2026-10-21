"""Release selection is applied before fixture limits and cursor ordering."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from release_helpers import BASE, WINDOW, fixture_releases, release_lines, request_id

from app.domain.models import EventQuery
from app.domain.releases import ReleaseSelection


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, [7, 6, 5, 4, 3, 2, 1, 0]),
        ("unknown", [7, 1]),
        ("2.5.0", [5, 0]),
        ("2.6.0", [2]),
        ("v2.6.0", [3]),
        ("V2.6.0", [4]),
        ("all", [6]),
        ("99.0.0", []),
    ],
)
def test_fixture_release_selection(
    tmp_path: Path, value: str | None, expected: list[int]
) -> None:
    """All, unknown and exact selections return only the intended identities."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    found = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query(value))
    )
    assert [event.request_id for event in found] == [request_id(i) for i in expected]


def test_release_filter_runs_before_the_limit(tmp_path: Path) -> None:
    """Newer unrelated releases cannot consume a sparse release's page."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    found = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"), limit=1)
    )
    assert [event.request_id for event in found] == [request_id(5)]


def test_release_and_existing_predicates_compose(tmp_path: Path) -> None:
    """Time, event, route, request IDs and status still constrain the selection."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    query = EventQuery(
        window=WINDOW,
        release=ReleaseSelection.from_query("2.5.0"),
        events=("http.request",),
        route="/v2/fixtures",
        request_ids=(request_id(0), request_id(5)),
        min_status=500,
        max_status=600,
    )
    assert [e.request_id for e in source.events(query)] == [request_id(0)]
    assert not source.events(
        EventQuery(window=WINDOW, release=query.release, request_id=request_id(2))
    )


def test_release_cursor_preserves_identical_timestamp_ties(tmp_path: Path) -> None:
    """The matching row below a same-time cursor survives release filtering."""
    lines = release_lines()
    lines[0]["timestamp"] = lines[5]["timestamp"]
    source = fixture_releases(tmp_path / "sample", lines)
    first = source.events(
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query("2.5.0"), limit=1)
    )[0]
    second = source.events(
        EventQuery(
            window=WINDOW,
            release=ReleaseSelection.from_query("2.5.0"),
            before=BASE + timedelta(minutes=5),
            before_id=first.request_id,
            limit=1,
        )
    )
    assert first.request_id == request_id(5)
    assert [e.request_id for e in second] == [request_id(0)]


def test_query_default_and_release_hash_are_compatible() -> None:
    """Existing callers default to all; selection is part of query identity."""
    assert EventQuery(window=WINDOW).release == ReleaseSelection()
    queries = {
        EventQuery(window=WINDOW, release=ReleaseSelection.from_query(value))
        for value in (None, "unknown", "all", "2.6.0")
    }
    assert len(queries) == 4
