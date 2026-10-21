"""Source-wide catalogue bounds and release-safe reuse of the existing cache."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from release_helpers import BASE, WINDOW, fixture_releases, release_lines
from test_cached import CountingSource

from app.contract import load_contract
from app.domain.errors import SourceUnavailableError
from app.domain.models import EventQuery, TimeWindow
from app.domain.releases import ReleaseCatalogue, ReleaseSelection
from app.sources.cached import CachedSource
from app.sources.local_log_source import LocalLogSource


def test_fixture_catalogue_is_unfiltered_and_marks_unknown(tmp_path: Path) -> None:
    """Catalogue discovery is independent of selected release and keeps unknown."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    result = source.release_catalogue(WINDOW)
    assert result.versions == ("2.5.0", "2.6.0", "V2.6.0", "all", "v2.6.0")
    assert result.has_unknown and not result.truncated
    empty = source.release_catalogue(
        TimeWindow(start=WINDOW.end, end=WINDOW.end + timedelta(hours=1))
    )
    assert empty.versions == () and not empty.has_unknown and not empty.truncated


def test_file_catalogue_exposes_tail_and_row_caps(tmp_path: Path) -> None:
    """Limited data is explicit; discovery never invents a complete catalogue."""
    lines = release_lines()
    path = tmp_path / "api.jsonl"
    content = "".join(json.dumps(line) + "\n" for line in lines)
    path.write_text(content, encoding="utf-8", newline="\n")
    source = LocalLogSource(
        path,
        len((json.dumps(lines[-1]) + "\n").encode()),
        load_contract(),
        lambda: BASE,
    )
    result = source.release_catalogue(WINDOW)
    assert result.versions == () and result.has_unknown and result.truncated
    huge = fixture_releases(tmp_path / "huge", [lines[2]] * 5001)
    assert huge.release_catalogue(WINDOW).truncated


def test_cached_event_results_do_not_cross_release_selections(tmp_path: Path) -> None:
    """All, exact and unknown queries keep different row contents in the cache."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    cache = CachedSource(source, 60, lambda: BASE)
    for _ in range(2):
        for value, count in [
            (None, 8),
            ("2.5.0", 2),
            ("2.6.0", 1),
            ("unknown", 2),
            ("all", 1),
        ]:
            found = cache.events(
                EventQuery(window=WINDOW, release=ReleaseSelection.from_query(value))
            )
            assert len(found) == count


def test_local_invalid_records_cannot_claim_complete_discovery(tmp_path: Path) -> None:
    """Rejected contract lines make local discovery incomplete, like Google."""
    path = tmp_path / "api.jsonl"
    lines = release_lines(["2.6.0"])
    path.write_text(
        json.dumps(lines[0]) + '\n{"api_version":"2.5.0"}\n', encoding="utf-8"
    )
    result = LocalLogSource(
        path, 100_000, load_contract(), lambda: BASE
    ).release_catalogue(WINDOW)
    assert result.versions == ("2.6.0",) and result.truncated


def test_catalogue_cache_ttl_window_keys_and_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Discovery reuses the configured TTL, isolates windows and never caches errors."""
    source = fixture_releases(tmp_path / "sample", release_lines())
    original = source.release_catalogue
    calls = 0
    fail = False
    now = BASE

    def counted(window: TimeWindow) -> ReleaseCatalogue:
        nonlocal calls
        calls += 1
        if fail:
            raise SourceUnavailableError("unavailable", "offline")
        return original(window)

    monkeypatch.setattr(source, "release_catalogue", counted)
    cache = CachedSource(source, 60, lambda: now)
    assert cache.release_catalogue(WINDOW) == cache.release_catalogue(WINDOW)
    assert calls == 1
    other = TimeWindow(start=WINDOW.end, end=WINDOW.end + timedelta(hours=1))
    assert not cache.release_catalogue(other).versions
    assert calls == 2
    now += timedelta(seconds=60)
    fail = True
    with pytest.raises(SourceUnavailableError):
        cache.release_catalogue(WINDOW)
    fail = False
    assert cache.release_catalogue(WINDOW).versions
    assert calls == 4


def test_unsupported_catalogue_fails_instead_of_empty_success() -> None:
    """A telemetry-only implementation does not pretend it has a catalogue."""
    cache = CachedSource(CountingSource(), 60, lambda: BASE)
    with pytest.raises(SourceUnavailableError, match="discovery"):
        cache.release_catalogue(WINDOW)


def test_same_window_caches_are_isolated_by_source_instance(tmp_path: Path) -> None:
    """Different source data cannot share event or catalogue cache contents."""
    first = fixture_releases(tmp_path / "first", release_lines(["2.5.0"]))
    second = fixture_releases(tmp_path / "second", release_lines(["2.6.0"]))
    a = CachedSource(first, 60, lambda: BASE)
    b = CachedSource(second, 60, lambda: BASE)
    query = EventQuery(window=WINDOW)
    assert a.events(query)[0].api_version == "2.5.0"
    assert b.events(query)[0].api_version == "2.6.0"
    assert a.release_catalogue(WINDOW).versions == ("2.5.0",)
    assert b.release_catalogue(WINDOW).versions == ("2.6.0",)
