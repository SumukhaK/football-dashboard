"""Release/time selection is immutable, exact, bounded and URL-safe."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.view_scope import parse_scope, scoped_url, sort_releases

NOW = datetime(2026, 10, 21, 12, tzinfo=UTC)


def test_semver_order_preserves_recorded_identity() -> None:
    """Numeric core/prerelease order precedes stable non-semver labels."""
    labels = (
        "v2.6.0",
        "2.9.0",
        "2.10.0-rc.10",
        "2.10.0-rc.2",
        "2.10.0",
        "all",
        "V2.6.0",
    )
    assert sort_releases(labels) == (
        "2.10.0",
        "2.10.0-rc.10",
        "2.10.0-rc.2",
        "2.9.0",
        "V2.6.0",
        "all",
        "v2.6.0",
    )


def test_official_semver_prerelease_precedence_and_build_ties() -> None:
    """Numeric prereleases sort below strings; build metadata never changes precedence."""
    chain = (
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    )
    assert sort_releases(chain) == tuple(reversed(chain))
    assert sort_releases(("1.0.0+z", "1.0.0+a", "01.0.0", "1.0.0-01")) == (
        "1.0.0+a",
        "1.0.0+z",
        "01.0.0",
        "1.0.0-01",
    )


def test_custom_window_and_scoped_links_keep_exact_utc_context() -> None:
    """Generated hourly links cannot replace the selected historical range."""
    scope = parse_scope(
        {
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-09-02T00:00:00Z",
            "api_version": "2.6.0",
        },
        NOW,
    )
    url = scoped_url("/requests?hours=24&status=5xx&before_id=request-12345678", scope)
    query = parse_qs(urlsplit(url).query)
    assert "hours" not in query and query["api_version"] == ["2.6.0"]
    assert query["status"] == ["5xx"] and query["before_id"] == ["request-12345678"]
    assert datetime.fromisoformat(query["start"][0]) == scope.window.start
    assert scope.window.start.tzinfo == UTC
    assert scoped_url("https://example.org/trace", scope) == "https://example.org/trace"
    assert scoped_url("/auth/logout", scope) == "/auth/logout"


@pytest.mark.parametrize(
    "query",
    [
        {"start": "2026-10-01T00:00:00Z"},
        {"start": "2026-10-02T00:00:00Z", "end": "2026-10-01T00:00:00Z"},
        {"start": "2026-10-01T00:00:00", "end": "2026-10-02T00:00:00"},
        {"start": "2026-10-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"},
        {"start": "2026-01-01T00:00:00Z", "end": "2026-03-01T00:00:00Z"},
        {"start": "2020-01-01T00:00:00Z", "end": "2020-01-02T00:00:00Z"},
        {"hours": "24", "start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"},
        {"hours": "2"},
        {"api_version": ""},
        {"api_version": "x" * 65},
    ],
)
def test_invalid_or_ambiguous_scope_is_rejected(query: dict[str, str]) -> None:
    """A bad historical range never widens silently to a default window."""
    with pytest.raises(ValueError):
        parse_scope(query, NOW)
