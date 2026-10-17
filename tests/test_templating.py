"""Tests for the shared template filters and globals."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.config import Config
from app.templating import nav_path_matches, state_tone, utc_time, visible_navigation


def test_utc_time_formats_a_moment() -> None:
    """A moment becomes a short UTC stamp."""
    moment = datetime(2026, 10, 8, 6, 1, tzinfo=UTC)
    assert utc_time(moment) == "08 Oct 06:01 UTC"


def test_utc_time_handles_none() -> None:
    """A missing moment renders as an empty string."""
    assert utc_time(None) == ""


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("ok", "ok"),
        ("degraded", "warn"),
        ("failed", "fail"),
        ("no data", "neutral"),
        ("unknown", "neutral"),
        ("something new", "neutral"),
    ],
)
def test_state_tone_maps_every_state_to_a_pill_tone(state: str, expected: str) -> None:
    """Each state maps to a shared pill tone, and an unknown one stays neutral."""
    assert state_tone(state) == expected


def test_nav_path_matches_the_page_itself() -> None:
    """Every navigation path matches its own page."""
    assert nav_path_matches("/", "/")
    assert nav_path_matches("/errors", "/errors")
    assert nav_path_matches("/assistant", "/assistant")


def test_nav_path_matches_a_detail_page_below_it() -> None:
    """A detail page keeps the section it belongs to current."""
    assert nav_path_matches("/requests/5051c1cc", "/requests")
    assert nav_path_matches("/crashes/4f1c2a9be0d34c5e", "/crashes")


def test_nav_path_does_not_match_a_sibling_or_prefix() -> None:
    """A path that is not the item, nor under it, does not match."""
    assert not nav_path_matches("/errors", "/")
    assert not nav_path_matches("/assistant", "/invites")
    assert not nav_path_matches("/requestscache", "/requests")


def _stub(crashes: bool, invites: bool) -> SimpleNamespace:
    """A stand-in for the settings two pages are gated on."""
    return SimpleNamespace(crashes_enabled=crashes, invites_enabled=invites)


def _paths(config: SimpleNamespace) -> list[str]:
    """Every offered navigation path, in order."""
    return [
        item["path"]
        for section in visible_navigation(config)
        for item in section["items"]
    ]


def _names(config: SimpleNamespace) -> list[str]:
    """Every offered section heading, in order."""
    return [section["name"] for section in visible_navigation(config)]


def test_visible_navigation_offers_the_pages_that_have_no_flag() -> None:
    """A page that cannot be switched off is always offered."""
    paths = _paths(_stub(crashes=False, invites=False))
    assert paths == ["/", "/errors", "/requests", "/assistant", "/data", "/access"]


def test_visible_navigation_drops_a_switched_off_page_and_its_section() -> None:
    """A page with its flag off goes, and an empty section goes with it."""
    config = _stub(crashes=False, invites=False)
    assert "/crashes" not in _paths(config)
    assert "/invites" not in _paths(config)
    assert "Android app" not in _names(config)
    assert "Platform" in _names(config)


def test_visible_navigation_keeps_an_offered_page_in_its_section() -> None:
    """A flag that is on keeps its page, under its own heading."""
    config = _stub(crashes=True, invites=True)
    by_name = {
        section["name"]: [item["path"] for item in section["items"]]
        for section in visible_navigation(config)
    }
    assert by_name["Android app"] == ["/crashes"]
    assert "/invites" in by_name["Platform"]


def test_every_gating_flag_exists_on_the_settings() -> None:
    """A misspelt flag would hide a page for good, so each one is checked."""
    config = Config()
    for section in visible_navigation(config):
        for item in section["items"]:
            if "enabled_by" in item:
                assert hasattr(config, item["enabled_by"]), item
