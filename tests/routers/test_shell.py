"""Tests for the shell: the sidebar, the page header and the theme button."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import Config
from tests.auth.console import console_client

from .requests_helpers import chat_request_id

PAGES = ("/", "/errors", "/requests", "/assistant", "/crashes")
CRASH_ISSUE = "4f1c2a9be0d34c5e"


def make_client(invites_enabled: bool = False) -> TestClient:
    """A signed-in test client with the invite page on or off."""
    return console_client(Config(invites_enabled=invites_enabled))


def test_every_page_renders_inside_the_shell() -> None:
    """Each page carries the sidebar and its own header, and neither the old
    page title nor the version footer."""
    client = make_client()
    for path in PAGES:
        body = client.get(path).text
        assert 'class="sidebar"' in body, path
        assert 'class="page-header"' in body, path
        assert "<h1>" not in body, path
        assert "page-footer" not in body, path
        assert 'href="/static/css/tokens.css"' in body, path
        assert 'href="/static/css/shell.css"' in body, path
        assert 'href="/static/css/components.css"' in body, path


def test_the_sidebar_marks_the_current_page_on_every_route() -> None:
    """Exactly one navigation link is current, and it is the page's own."""
    client = make_client()
    marked = {
        "/": "/",
        "/errors": "/errors",
        "/requests": "/requests",
        "/assistant": "/assistant",
        "/crashes": "/crashes",
        f"/requests/{chat_request_id()}": "/requests",
        f"/crashes/{CRASH_ISSUE}": "/crashes",
    }
    for path, expected in marked.items():
        body = client.get(path).text
        assert body.count('aria-current="page"') == 1, path
        assert f'href="{expected}" aria-current="page"' in body, path


def test_the_sidebar_groups_the_pages_by_section() -> None:
    """The links sit under the section headings the redesign names."""
    body = make_client().get("/").text
    assert "Backend" in body
    assert "Android app" in body
    assert "Platform" in body
    for name, path in (
        ("Overview", "/"),
        ("Errors", "/errors"),
        ("Requests", "/requests"),
        ("Assistant", "/assistant"),
        ("Crashes", "/crashes"),
        ("Data", "/data"),
        ("Access", "/access"),
    ):
        assert f'href="{path}"' in body, name


def test_invites_are_only_in_the_sidebar_when_enabled() -> None:
    """The one page that writes is offered only when it is switched on."""
    assert 'href="/invites"' not in make_client().get("/").text
    assert 'href="/invites"' in make_client(invites_enabled=True).get("/").text


def test_crashes_are_offered_whenever_they_are_on() -> None:
    """The fixture source runs crashes, so the page and its section are there."""
    body = make_client().get("/crashes?hours=168").text
    assert 'href="/crashes" aria-current="page"' in body
    assert ">App crashes</a>" in body
    assert "Android app" in body
    assert '<h1 class="page-title">App crashes</h1>' in body
    assert (
        '<p class="page-subtitle">Android app, from Crashlytics, last 7 days</p>'
        in body
    )


def test_the_header_names_the_page_and_the_window() -> None:
    """The page header holds the title and the window in words."""
    body = make_client().get("/assistant?hours=168").text
    assert '<h1 class="page-title">Assistant</h1>' in body
    assert '<p class="page-subtitle">Last 7 days</p>' in body


def test_the_sidebar_footer_holds_the_theme_button_and_the_version() -> None:
    """The theme button says what it will switch to, and the version is shown."""
    body = make_client().get("/").text
    assert 'aria-label="Switch to light theme"' in body
    assert "v1.0.0" in body
