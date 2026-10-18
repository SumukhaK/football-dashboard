"""Time-limited in-memory cache in front of the telemetry and crash sources."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Hashable
from datetime import datetime, timedelta
from typing import TypeVar, cast

from app.domain.clock import Clock
from app.domain.crashes import CrashEvent
from app.domain.models import (
    ErrorGroup,
    EventQuery,
    LocalReadStats,
    PlatformEvent,
    SourceCapabilities,
    TelemetryEvent,
    TimeWindow,
    Trace,
)
from app.sources.base import CrashSource, LocalLogStats, TelemetrySource

T = TypeVar("T")


class TtlCache:
    """Keeps each key's value for ttl_seconds, evicting least recently used."""

    def __init__(self, ttl_seconds: int, clock: Clock, max_entries: int = 256) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock
        self._max_entries = max_entries
        self._entries: OrderedDict[Hashable, tuple[datetime, object]] = OrderedDict()

    def get(self, key: Hashable, load: Callable[[], T]) -> T:
        """Return a fresh cached value or load, store and return a new one.

        A raised error propagates before anything is stored, so failures are
        never cached and the next call retries the inner source.
        """
        if self._ttl.total_seconds() == 0:
            return load()
        now = self._clock()
        hit = self._entries.get(key)
        if hit is not None and now - hit[0] < self._ttl:
            self._entries.move_to_end(key)
            return cast(T, hit[1])
        value = load()
        self._store(key, now, value)
        return value

    def _store(self, key: Hashable, now: datetime, value: object) -> None:
        """Store a value and evict the least recently used entries over the limit."""
        self._entries[key] = (now, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class CachedSource:
    """Caches each distinct call for ttl_seconds, evicting least recently used."""

    def __init__(
        self,
        inner: TelemetrySource,
        ttl_seconds: int,
        clock: Clock,
        max_entries: int = 256,
    ) -> None:
        self._inner = inner
        self._cache = TtlCache(ttl_seconds, clock, max_entries)

    def events(self, query: EventQuery) -> list[TelemetryEvent]:
        """Return events matching the query, newest first."""
        return self._cache.get(("events", query), lambda: self._inner.events(query))

    def trace(self, trace_id: str) -> Trace | None:
        """Return one trace, or None when it does not exist."""
        return self._cache.get(("trace", trace_id), lambda: self._inner.trace(trace_id))

    def error_groups(self, window: TimeWindow) -> list[ErrorGroup]:
        """Return error groups that overlap the window."""
        return self._cache.get(
            ("error_groups", window), lambda: self._inner.error_groups(window)
        )

    def platform_events(self, window: TimeWindow) -> list[PlatformEvent]:
        """Return platform events inside the window, newest first."""
        return self._cache.get(
            ("platform_events", window), lambda: self._inner.platform_events(window)
        )

    def capabilities(self) -> SourceCapabilities:
        """What the inner source can answer; the same on every call, so uncached."""
        return self._inner.capabilities()

    def read_stats(self) -> LocalReadStats | None:
        """The inner source's log read, or None when it read no local file."""
        if isinstance(self._inner, LocalLogStats):
            return self._inner.read_stats()
        return None


class CachedCrashSource:
    """Caches each distinct crash query for ttl_seconds, like CachedSource."""

    def __init__(
        self,
        inner: CrashSource,
        ttl_seconds: int,
        clock: Clock,
        max_entries: int = 256,
    ) -> None:
        self._inner = inner
        self._cache = TtlCache(ttl_seconds, clock, max_entries)

    def crash_events(self, window: TimeWindow, limit: int) -> list[CrashEvent]:
        """Return up to limit events inside the window, newest first."""
        return self._cache.get(
            ("crash_events", window, limit),
            lambda: self._inner.crash_events(window, limit),
        )

    def issue_events(
        self, issue_id: str, window: TimeWindow, limit: int
    ) -> list[CrashEvent]:
        """Return up to limit events of one issue in the window, newest first."""
        return self._cache.get(
            ("issue_events", issue_id, window, limit),
            lambda: self._inner.issue_events(issue_id, window, limit),
        )
