"""Cache around any TelemetrySource implementation.

The cache key is the full query (frozen dataclasses are hashable).  Expired
entries are replaced on next read.  ``ttl_seconds=0`` means no caching: every
call goes to ``inner``.  Bounded to ``max_entries`` (LRU eviction, no
background threads).
"""

from __future__ import annotations

from collections.abc import Sequence
from collections import OrderedDict

from app.domain.errors import SourceUnavailableError
from app.sources.base import TelemetrySource


class CachedSource(TelemetrySource):
    """Cache around any ``TelemetrySource``.

    :param inner: The source to cache.
    :param ttl_seconds: Entry expiration in seconds.  ``0`` disables caching.
    :param clock: Optional clock for expiry; defaults to ``system_clock``.
    :param max_entries: Maximum number of entries kept (LRU eviction).
    """

    def __init__(
        self,
        inner: TelemetrySource,
        ttl_seconds: int,
        clock,
        max_entries: int = 256,
    ) -> None:
        self._inner = inner
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: OrderedDict[str, tuple[int, object]] = OrderedDict()
        self._max_entries = max_entries

    def _make_key(self, method: str, args: object) -> str:
        """Create a hashable cache key from method name and arguments."""
        return f"{method}:{hash(str(args))}"

    def _check_cache(self, key: str) -> object | None:
        """Return cached value if not expired, otherwise remove and return None."""
        if key not in self._cache:
            return None
        timestamp, value = self._cache[key]
        if self._ttl_seconds > 0 and (self._clock() - timestamp).total_seconds() > self._ttl_seconds:
            self._cache.move_to_end(key)  # LRU: remove expired
            del self._cache[key]
            return None
        # Move to end to mark as recently used
        self._cache.move_to_end(key)
        return value

    def _set_cache(self, key: str, value: object) -> None:
        """Store a value in the cache, evicting LRU if at capacity."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (self._clock(), value)
        if len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)  # Remove least recently used

    def events(self, query: object) -> Sequence[object]:  # type: ignore[override]
        """Query events, using cache if enabled."""
        key = self._make_key("events", query)
        cached = self._check_cache(key)
        if cached is not None:
            return cached  # type: ignore[return-value]

        result = self._inner.events(query)  # type: ignore[arg-type]
        self._set_cache(key, result)
        return result

    def trace(self, trace_id: str) -> object | None:  # type: ignore[override]
        """Trace lookup, not cached (errors are never cached)."""
        if self._ttl_seconds == 0:
            return self._inner.trace(trace_id)
        # Cache misses raise; hits return the result
        key = self._make_key("trace", trace_id)
        cached = self._check_cache(key)
        if cached is not None:
            return cached
        result = self._inner.trace(trace_id)
        # Never cache SourceUnavailableError or None
        if result is not None and not isinstance(result, SourceUnavailableError):
            self._set_cache(key, result)
        return result

    def error_groups(self, window: object) -> Sequence[object]:  # type: ignore[override]
        """Error groups, using cache if enabled."""
        key = self._make_key("error_groups", window)
        cached = self._check_cache(key)
        if cached is not None:
            return cached

        result = self._inner.error_groups(window)  # type: ignore[arg-type]
        self._set_cache(key, result)
        return result

    def platform_events(self, window: object) -> Sequence[object]:  # type: ignore[override]
        """Platform events, using cache if enabled."""
        key = self._make_key("platform_events", window)
        cached = self._check_cache(key)
        if cached is not None:
            return cached

        result = self._inner.platform_events(window)  # type: ignore[arg-type]
        self._set_cache(key, result)
        return result