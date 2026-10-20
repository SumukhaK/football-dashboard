"""The response policy: CSP nonces, framing, caching, HSTS and HTMX history."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.auth.sessions import SessionCookie, session_cookie_name
from app.config import REPO_ROOT, Config
from app.main import create_app
from tests.auth.console import console, session_for
from tests.auth.support import NOW, google_config

NONCE = re.compile(r'<script nonce="([^"]+)"')
JSON_NONCE = re.compile(r'<script type="application/json"[^>]*nonce="([^"]+)"')


def _directive(csp: str, name: str) -> str:
    """One CSP directive's value, for exact assertions."""
    for part in csp.split(";"):
        key, _, value = part.strip().partition(" ")
        if key == name:
            return value
    raise AssertionError(f"the CSP has no {name} directive")


def _unsigned(settings: Config | None = None) -> TestClient:
    app = create_app(settings or google_config(), clock=lambda: NOW)
    return TestClient(app, base_url="https://testserver")


def test_a_private_page_carries_the_full_response_policy() -> None:
    """One authenticated page proves every header the console promises."""
    response = console().client.get("/")
    csp = response.headers["content-security-policy"]

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")
    assert _directive(csp, "frame-ancestors") == "'none'"
    assert _directive(csp, "base-uri") == "'none'"
    assert _directive(csp, "form-action") == "'self'"
    assert _directive(csp, "object-src") == "'none'"
    assert _directive(csp, "default-src") == "'self'"


def test_the_nonce_matches_the_theme_and_chart_data_scripts() -> None:
    """The rendered inline scripts carry the header's per-request nonce."""
    signed = console()
    home = signed.client.get("/")
    header_nonce = _directive(home.headers["content-security-policy"], "script-src")
    theme_nonce = NONCE.search(home.text)

    assert theme_nonce is not None
    assert f"'nonce-{theme_nonce.group(1)}'" in header_nonce

    partial = signed.client.get("/partials/overview")
    chart_nonce = JSON_NONCE.search(partial.text)
    partial_header = _directive(
        partial.headers["content-security-policy"], "script-src"
    )
    assert chart_nonce is not None
    assert f"'nonce-{chart_nonce.group(1)}'" in partial_header


def test_the_public_login_page_carries_the_same_policy_and_nonce() -> None:
    """The login page's own theme bootstrap is nonced, not left inline."""
    response = _unsigned().get("/login")
    csp = response.headers["content-security-policy"]

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert NONCE.search(response.text) is not None
    assert "frame-ancestors 'none'" in csp


def test_a_nonce_is_not_reused_between_requests() -> None:
    """Each response gets a fresh nonce even on the same page."""
    client = _unsigned()
    first = NONCE.search(client.get("/login").text)
    second = NONCE.search(client.get("/login").text)

    assert first is not None and second is not None
    assert first.group(1) != second.group(1)


def test_inline_scripts_are_not_allowed_but_inline_styles_are() -> None:
    """Charts need width attributes; arbitrary inline script is refused."""
    csp = console().client.get("/").headers["content-security-policy"]
    script_src = _directive(csp, "script-src")
    style_src = _directive(csp, "style-src")

    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'unsafe-inline'" in style_src
    assert "'self'" in script_src


def test_guard_refusals_carry_the_same_headers() -> None:
    """A redirect, a 401 and a 403 are responses too, not naked errors."""
    unsigned = _unsigned()
    redirect = unsigned.get("/requests", follow_redirects=False)
    unauthorized = unsigned.post("/invites", follow_redirects=False)

    assert redirect.headers["x-content-type-options"] == "nosniff"
    assert redirect.headers["content-security-policy"].startswith("default-src")
    assert redirect.headers["cache-control"] == "no-store"
    assert unauthorized.headers["x-frame-options"] == "DENY"
    assert unauthorized.headers["referrer-policy"] == "no-referrer"

    settings = console().settings
    foreign = session_for(settings, lambda: NOW, email="other@example.com")
    value = SessionCookie.from_config(settings, lambda: NOW).dumps(foreign)
    forbidden = TestClient(
        create_app(settings, clock=lambda: NOW),
        base_url="https://testserver",
        cookies={session_cookie_name(settings): value},
    ).get("/", follow_redirects=False)

    assert forbidden.status_code == 403
    assert forbidden.headers["x-frame-options"] == "DENY"
    assert forbidden.headers["cache-control"] == "no-store"


def test_no_store_covers_html_partials_health_and_owner_404s() -> None:
    """No sensitive response is allowed to sit in a shared cache."""
    signed = console()
    client = _unsigned()

    assert signed.client.get("/").headers["cache-control"] == "no-store"
    assert (
        signed.client.get("/partials/overview").headers["cache-control"] == "no-store"
    )
    assert client.get("/healthz").headers["cache-control"] == "no-store"
    assert client.get("/login").headers["cache-control"] == "no-store"
    assert (
        client.get("/docs", follow_redirects=False).headers["cache-control"]
        == "no-store"
    )
    missing = signed.client.get("/no-such-page")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"


def test_static_assets_keep_their_own_caching_and_are_public() -> None:
    """Only the static mount is exempt from no-store."""
    response = _unsigned().get("/static/css/tokens.css")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers.get("cache-control") != "no-store"


def test_hsts_appears_only_for_an_https_origin() -> None:
    """Loopback http must not pin a browser to a scheme it does not serve."""
    hosted = _unsigned().get("/login")
    assert "strict-transport-security" in hosted.headers

    local = google_config(
        auth_public_origin="http://127.0.0.1:8080",
        auth_callback_url="http://127.0.0.1:8080/auth/callback",
    )
    response = TestClient(
        create_app(local, clock=lambda: NOW), base_url="http://127.0.0.1:8080"
    ).get("/login")

    assert "strict-transport-security" not in response.headers


def test_the_shell_disables_htmx_history_and_loads_the_history_clearer() -> None:
    """A protected body opts out before any swap can snapshot it."""
    signed = console()
    home = signed.client.get("/")
    login = _unsigned().get("/login")

    assert 'hx-history="false"' in home.text
    assert "/static/auth.js" in home.text
    assert "/static/theme.js" in home.text
    assert "/static/auth.js" in login.text


def test_auth_js_clears_only_the_htmx_cache_and_reloads_on_bfcache() -> None:
    """No other local storage is touched, and a restored page re-checks auth."""
    script = (REPO_ROOT / "app" / "static" / "auth.js").read_text(encoding="utf-8")

    assert 'removeItem("htmx-history-cache")' in script
    assert "pageshow" in script
    assert "persisted" in script
    assert "location.reload" in script
    assert "localStorage.clear" not in script
    assert script.count("removeItem(") == 1


def test_the_invite_copy_uses_an_external_handler_not_an_onclick() -> None:
    """The invite partial has no inline event handler for the CSP to allow."""
    page = console(Config(invites_enabled=True)).client.get("/invites")
    partial = (
        REPO_ROOT / "app" / "templates" / "partials" / "invite_result.html"
    ).read_text(encoding="utf-8")
    handler = (REPO_ROOT / "app" / "static" / "invite.js").read_text(encoding="utf-8")

    assert "onclick=" not in partial
    assert "js-copy-invite" in partial
    assert 'closest(".js-copy-invite")' in handler
    assert "/static/invite.js" in page.text
