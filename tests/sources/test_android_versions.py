"""Android app versions filter independently, before row caps and grouping."""

from dataclasses import replace
from datetime import timedelta

from app.config import Config
from app.sources.fixture_crashes import FixtureCrashSource
from tests.services.requests_helpers import NOW, WINDOW


def test_fixture_version_filter_precedes_limit_and_issue_selection() -> None:
    """One old version remains visible behind a flood of newer-version events."""
    source = FixtureCrashSource(Config().fixture_dir, NOW)
    sample = replace(source._events[-1], timestamp=NOW - timedelta(minutes=1))
    source._events = [replace(sample, app_version="2.6.0")] * 6000 + [
        replace(sample, app_version="2.5.1")
    ]
    events = source.version_crash_events(WINDOW, 1, "2.5.1")
    assert len(events) == 1 and events[0].app_version == "2.5.1"
    assert source.version_issue_events(sample.issue_id, WINDOW, 1, "2.5.1") == events


def test_issue_detail_marks_a_capped_sample_as_partial() -> None:
    """Issue counts at the list cap must not look like complete lifetime counts."""
    from app.services.crashes import CrashesService

    source = FixtureCrashSource(Config().fixture_dir, NOW)
    sample = replace(
        source._events[0], timestamp=NOW - timedelta(minutes=1), app_version="2.6.0"
    )
    source._events = [sample] * 5000
    detail = CrashesService(source, lambda: NOW, version="2.6.0").detail_for_hours(
        sample.issue_id, 24, WINDOW
    )
    assert detail and detail.truncated


def test_missing_issue_under_a_cap_is_unavailable_not_absent() -> None:
    """An issue beyond the retained sample cannot be declared nonexistent."""
    import pytest

    from app.domain.errors import SourceUnavailableError
    from app.services.crashes import CrashesService

    source = FixtureCrashSource(Config().fixture_dir, NOW)
    sample = replace(
        source._events[0], timestamp=NOW - timedelta(minutes=1), app_version="2.6.0"
    )
    source._events = [sample] * 5000
    with pytest.raises(SourceUnavailableError, match="cap"):
        CrashesService(source, lambda: NOW, version="2.6.0").detail_for_hours(
            "outside-sample", 24, WINDOW
        )


def test_android_cache_isolates_all_exact_unknown_and_issue_queries() -> None:
    """No version's capped rows can be reused for another app version."""
    from app.sources.cached import CachedCrashSource

    source = FixtureCrashSource(Config().fixture_dir, NOW)
    sample = replace(source._events[0], timestamp=NOW - timedelta(minutes=1))
    source._events = [
        replace(sample, app_version=v) for v in ("2.5.1", "2.6.0", "unknown")
    ]
    cached = CachedCrashSource(source, 60, lambda: NOW)
    assert len(cached.crash_events(WINDOW, 5)) == 3
    for version in ("2.5.1", "2.6.0", "unknown"):
        assert [
            e.app_version for e in cached.version_crash_events(WINDOW, 5, version)
        ] == [version]
        assert [
            e.app_version
            for e in cached.version_issue_events(sample.issue_id, WINDOW, 5, version)
        ] == [version]
    source._events = []
    assert len(cached.crash_events(WINDOW, 5)) == 3
    assert cached.version_crash_events(WINDOW, 5, "2.5.1")[0].app_version == "2.5.1"
