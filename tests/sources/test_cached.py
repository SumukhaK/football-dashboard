"""Tests for CachedSource."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.contract import load_contract
from app.domain.crashes import CrashEvent
from app.domain.errors import SourceUnavailableError
from app.domain.models import (
    ALL_CAPABILITIES,
    ErrorGroup,
    EventQuery,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.sources.cached import CachedCrashSource, CachedSource
from app.sources.local_log_source import LocalLogSource

START = datetime(2026, 10, 8, tzinfo=UTC)
WINDOW = TimeWindow(start=START, end=START + timedelta(hours=1))


class CountingSource:
    """A source that counts calls and can be told to fail."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def _hit(self) -> None:
        self.calls += 1
        if self.fail:
            raise SourceUnavailableError("unavailable", "down")

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Count and return nothing."""
        self._hit()
        return []

    def trace(self, trace_id: str) -> Trace | None:
        """Count and return nothing."""
        self._hit()
        return None

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Count and return nothing."""
        self._hit()
        return []

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Count and return nothing."""
        self._hit()
        return []

    def capabilities(self) -> SourceCapabilities:
        """Answer without counting: what a source can do does not change."""
        return ALL_CAPABILITIES


class FakeClock:
    """A clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


def make_cache(
    ttl: int = 60, max_entries: int = 256
) -> tuple[CachedSource, CountingSource, FakeClock]:
    """Return a cache over a counting source with a hand-moved clock."""
    inner, clock = CountingSource(), FakeClock()
    return CachedSource(inner, ttl, clock, max_entries=max_entries), inner, clock


def test_second_call_is_a_hit() -> None:
    """The same call within the TTL reaches the inner source once."""
    cache, inner, _ = make_cache()
    query = EventQuery(window=WINDOW)
    cache.events(query)
    cache.events(query)
    assert inner.calls == 1


def test_capabilities_come_from_the_inner_source_and_are_not_cached() -> None:
    """What a source can answer does not change, so it is asked, not cached."""
    cache, inner, _ = make_cache()
    assert cache.capabilities() == ALL_CAPABILITIES
    cache.capabilities()
    assert inner.calls == 0


def test_read_stats_is_none_for_a_source_without_a_local_log() -> None:
    """A source that reads no file has no read to describe."""
    cache, _, _ = make_cache()
    assert cache.read_stats() is None


def test_read_stats_pass_through_a_local_log_source(tmp_path: Path) -> None:
    """A cached local log source still answers the footer's counts."""
    log = tmp_path / "api.jsonl"
    log.write_text("", encoding="utf-8")
    inner = LocalLogSource(log, 1_000_000, load_contract(), lambda: START)
    cache = CachedSource(inner, 60, FakeClock())
    stats = cache.read_stats()
    assert stats is not None
    assert stats.lines_read == 0
    assert stats.events_kept == 0


def test_each_method_and_argument_has_its_own_entry() -> None:
    """Different methods and arguments do not share entries."""
    cache, inner, _ = make_cache()
    cache.trace("a" * 32)
    cache.trace("b" * 32)
    cache.error_groups(WINDOW)
    cache.platform_events(WINDOW)
    cache.trace("a" * 32)
    assert inner.calls == 4


def test_entry_expires_after_ttl() -> None:
    """After the TTL the inner source is asked again."""
    cache, inner, clock = make_cache(ttl=60)
    cache.error_groups(WINDOW)
    clock.now += timedelta(seconds=59)
    cache.error_groups(WINDOW)
    clock.now += timedelta(seconds=1)
    cache.error_groups(WINDOW)
    assert inner.calls == 2


def test_zero_ttl_disables_caching() -> None:
    """ttl_seconds=0 sends every call to the inner source."""
    cache, inner, _ = make_cache(ttl=0)
    cache.platform_events(WINDOW)
    cache.platform_events(WINDOW)
    assert inner.calls == 2


def test_least_recently_used_entry_is_evicted() -> None:
    """Going over max_entries drops the entry used longest ago."""
    cache, inner, _ = make_cache(max_entries=2)
    cache.trace("a")
    cache.trace("b")
    cache.trace("a")
    cache.trace("c")
    assert inner.calls == 3
    cache.trace("a")
    assert inner.calls == 3
    cache.trace("b")
    assert inner.calls == 4


def test_errors_are_never_cached() -> None:
    """A failing call is retried on the next read, then cached once it works."""
    cache, inner, _ = make_cache()
    inner.fail = True
    for _ in range(2):
        with pytest.raises(SourceUnavailableError):
            cache.events(EventQuery(window=WINDOW))
    inner.fail = False
    cache.events(EventQuery(window=WINDOW))
    cache.events(EventQuery(window=WINDOW))
    assert inner.calls == 3


class CountingCrashSource:
    """A crash source that counts calls and returns nothing."""

    def __init__(self) -> None:
        self.calls = 0

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """Count and return nothing."""
        self.calls += 1
        return []

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Count and return nothing."""
        self.calls += 1
        return []


def test_crash_queries_are_cached_per_argument() -> None:
    """Repeat crash queries hit the cache; each issue gets its own entry."""
    inner, clock = CountingCrashSource(), FakeClock()
    cache = CachedCrashSource(inner, 60, clock)
    cache.crash_events(WINDOW, 10)
    cache.crash_events(WINDOW, 10)
    cache.issue_events("a", WINDOW, 10)
    cache.issue_events("b", WINDOW, 10)
    cache.issue_events("a", WINDOW, 10)
    assert inner.calls == 3
    clock.now += timedelta(seconds=60)
    cache.crash_events(WINDOW, 10)
    assert inner.calls == 4
