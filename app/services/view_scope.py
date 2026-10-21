"""Immutable release/time selection and explicit internal URL context."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.domain.models import TimeWindow
from app.domain.releases import ReleaseSelection
from app.services.windows import resolve_window_hours, window_for_hours

SCOPE_KEYS = ("hours", "start", "end", "api_version")
PAGE_PATHS = ("/", "/requests", "/errors", "/assistant", "/data", "/access", "/crashes")
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
VersionKey = tuple[int, int, int, bool, tuple[tuple[int, int | str], ...]]


@dataclass(frozen=True)
class ViewScope:
    """One resolved window and exact release selection for one request."""

    window: TimeWindow
    release: ReleaseSelection
    hours: int
    custom: bool
    explicit: bool

    def params(self) -> dict[str, str]:
        """Canonical UTC/custom or quick-hour parameters, omitting all releases."""
        params = (
            {"start": self.window.start.isoformat(), "end": self.window.end.isoformat()}
            if self.custom
            else {"hours": str(self.hours)}
        )
        if self.release.kind != "all":
            params["api_version"] = self.release.value or "unknown"
        return params


def _utc(value: str) -> datetime:
    """Require a bounded offset-bearing ISO timestamp and normalize it to UTC."""
    if len(value) > 40:
        raise ValueError("timestamp is too long")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("start/end must include a timezone offset")
    return moment.astimezone(UTC)


def parse_scope(
    query: Mapping[str, str],
    now: datetime,
    default_hours: int = 24,
    max_range_days: int = 31,
    max_history_days: int = 365,
) -> ViewScope:
    """Reject invalid/ambiguous ranges instead of silently widening the query."""
    hours = resolve_window_hours(
        int(query["hours"]) if "hours" in query else None, default_hours
    )
    release = ReleaseSelection.from_query(query.get("api_version"))
    custom = "start" in query or "end" in query
    window = window_for_hours(hours, now)
    if custom:
        if "hours" in query or "start" not in query or "end" not in query:
            raise ValueError("use start and end together, without hours")
        window = TimeWindow(_utc(query["start"]), _utc(query["end"]))
        if window.end > now:
            raise ValueError("historical end cannot be in the future")
        if window.end - window.start > timedelta(days=max_range_days):
            raise ValueError(f"custom range cannot exceed {max_range_days} days")
        if window.start < now - timedelta(days=max_history_days):
            raise ValueError(
                f"historical start exceeds the {max_history_days}-day safety bound"
            )
    return ViewScope(
        window, release, hours, custom, any(k in query for k in SCOPE_KEYS)
    )


def scoped_url(url: str, scope: ViewScope) -> str:
    """Carry active scope only to internal console GET views, never auth/writes."""
    parsed = urlsplit(url)
    path = parsed.path
    allowed = path in (*PAGE_PATHS, "/source", "/invites") or path.startswith(
        ("/requests/", "/crashes/", "/partials/")
    )
    if not scope.explicit or parsed.scheme or parsed.netloc or not allowed:
        return url
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key in SCOPE_KEYS:
        params.pop(key, None)
    params = {**scope.params(), **params}
    return (
        path
        + "?"
        + urlencode(params)
        + ("#" + parsed.fragment if parsed.fragment else "")
    )


def _version_key(label: str) -> VersionKey | None:
    """SemVer precedence, preserving the label and ignoring build metadata."""
    match = SEMVER.fullmatch(label)
    if match is None:
        return None
    parts = match.group(4).split(".") if match.group(4) else []
    if any(p.isdigit() and len(p) > 1 and p.startswith("0") for p in parts):
        return None
    prerelease = tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts)
    return int(match[1]), int(match[2]), int(match[3]), not parts, prerelease


def sort_releases(labels: tuple[str, ...]) -> tuple[str, ...]:
    """Sort real SemVer newest first, then all other exact labels lexically."""
    parsed = [(label, _version_key(label)) for label in sorted(set(labels))]
    versions = [(label, key) for label, key in parsed if key is not None]
    versions.sort(key=lambda pair: pair[1], reverse=True)
    return tuple(label for label, _ in versions) + tuple(
        label for label, key in parsed if key is None
    )
