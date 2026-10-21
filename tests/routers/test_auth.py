"""Tests for /login, /auth/google, /auth/callback and POST /auth/logout.

The adapter is the real D9.2 one, wired to the fake Google in tests/auth; the
cookie codecs are the real ones over a frozen clock. Nothing here reaches
Google, and no cookie, code, state or token may appear in a log line.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from app.auth.sessions import (
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.domain.auth import (
    OAUTH_COOKIE,
    SESSION_COOKIE,
)
from app.factory import create_app
from tests.auth.support import (
    CALLBACK,
    NOW,
    FakeGoogle,
    build_provider,
)
from tests.routers.auth_helpers import (
    CLOCK,
    HOSTED,
    _begin,
    _callback,
    _console,
    _live_cookie,
    _session,
    _token_calls,
)


def test_the_login_page_is_public_minimal_and_uncached() -> None:
    """It has the button and theme, no private shell and no source read."""
    client, _ = _console()

    response = client.get("/login")

    assert response.status_code == 200
    assert "Continue with Google" in response.text
    assert 'href="/static/css/tokens.css"' in response.text
    assert 'href="/static/css/login.css"' in response.text
    assert 'class="sidebar"' not in response.text
    assert 'class="page-header"' not in response.text
    assert "sidebar-footer" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_the_login_page_offers_the_safe_return_path() -> None:
    """The next target reaches the button as a local path only."""
    client, _ = _console()

    body = client.get("/login", params={"next": "/requests?window=24"}).text
    assert "next=/requests%3Fwindow%3D24" in body

    unsafe = client.get("/login", params={"next": "//evil.example/steal"}).text
    assert 'href="/auth/google?next=/"' in unsafe
    assert "evil.example" not in unsafe


def test_the_login_page_shows_generic_retry_text_only_when_asked() -> None:
    """A failed attempt gets one generic sentence, never provider detail."""
    client, _ = _console()

    assert "didn&#39;t complete" not in client.get("/login").text
    retry = client.get("/login", params={"retry": "1"}).text
    assert "didn&#39;t complete" in retry
    assert "invalid_grant" not in retry


def test_start_redirects_to_google_with_a_signed_transaction() -> None:
    """PKCE, state, nonce and the configured callback travel with the attempt."""
    client, _ = _console()

    response = client.get("/auth/google?next=/requests", follow_redirects=False)

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == [HOSTED.google_client_id]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid email"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"][0]
    assert query["nonce"][0]

    cookie = _live_cookie(response, OAUTH_COOKIE)
    assert cookie["httponly"] == "yes"
    assert cookie["secure"] == "yes"
    assert cookie["samesite"] == "lax"
    assert cookie["path"] == "/"
    assert cookie["max-age"] == "300"
    assert "domain" not in cookie

    transaction = TransactionCookie.from_config(HOSTED, CLOCK).loads(cookie["value"])
    assert transaction.state == query["state"][0]
    assert transaction.nonce == query["nonce"][0]
    assert transaction.return_path == "/requests"
    assert session_cookie_name(HOSTED) not in client.cookies


def test_start_replaces_the_previous_transaction() -> None:
    """One browser keeps one pending attempt, not a growing list."""
    client, fake = _console()

    first = _begin(client, fake)
    second = _begin(client, fake)

    assert first.state != second.state
    assert client.cookies.get(OAUTH_COOKIE) is not None
    response = _callback(client, first)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert _token_calls(fake) == 0


def test_a_malicious_next_cannot_redirect_off_site() -> None:
    """The signed transaction keeps only a local path, so the 303 cannot leave."""
    client, fake = _console()
    transaction = _begin(client, fake, "//evil.example/steal")

    assert transaction.return_path == "/"
    response = _callback(client, transaction)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "evil.example" not in response.headers["location"]


def test_a_successful_callback_creates_the_console_session() -> None:
    """A fresh one-hour session, the attempt cleared, no provider token kept."""
    client, fake = _console()
    transaction = _begin(client, fake)

    response = _callback(client, transaction)

    assert response.status_code == 303
    assert response.headers["location"] == "/requests"
    assert response.headers["cache-control"] == "no-store"
    session_cookie = _live_cookie(response, SESSION_COOKIE)
    assert session_cookie["httponly"] == "yes"
    assert session_cookie["secure"] == "yes"
    assert session_cookie["samesite"] == "lax"
    assert session_cookie["path"] == "/"
    assert session_cookie["max-age"] == "3600"
    assert "domain" not in session_cookie

    session = _session(client)
    assert session.subject == "1234567890"
    assert session.email == "sumukh.aithal@gmail.com"
    assert session.expires_at == NOW + timedelta(hours=1)
    assert session.session_id
    assert client.cookies.get(OAUTH_COOKIE) is None

    stored = session_cookie["value"]
    assert "fake-access-token" not in stored
    assert "id_token" not in stored
    assert _token_calls(fake) == 1


def test_the_callback_replays_nothing_without_the_transaction() -> None:
    """Google's code is single use, and our attempt cookie is gone."""
    client, fake = _console()
    transaction = _begin(client, fake)
    assert _callback(client, transaction).status_code == 303
    client.cookies.clear()

    replay = _callback(client, transaction)

    assert replay.status_code == 303
    assert replay.headers["location"] == "/login?retry=1"
    assert session_cookie_name(HOSTED) not in client.cookies
    assert _token_calls(fake) == 1


def test_a_wrong_state_stops_before_the_token_endpoint() -> None:
    """The bound state is checked first; no code is exchanged."""
    client, fake = _console()
    _begin(client, fake)

    response = client.get(
        "/auth/callback",
        params={"code": "fake-code", "state": "not-the-bound-state"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?retry=1"
    assert _token_calls(fake) == 0
    assert client.cookies.get(OAUTH_COOKIE) is None
    assert session_cookie_name(HOSTED) not in client.cookies


def test_an_expired_transaction_is_refused() -> None:
    """Five minutes are enforced against the server clock, not the browser."""
    settings = HOSTED
    fake = FakeGoogle()
    provider = build_provider(fake, clock=CLOCK)
    starter = TestClient(
        create_app(settings, clock=CLOCK, provider=provider),
        base_url="https://testserver",
    )
    transaction = _begin(starter, fake)
    value = starter.cookies.get(OAUTH_COOKIE)
    assert value is not None

    late = TestClient(
        create_app(
            settings, clock=lambda: NOW + timedelta(minutes=6), provider=provider
        ),
        base_url="https://testserver",
        cookies={OAUTH_COOKIE: value},
    )
    response = _callback(late, transaction)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?retry=1"
    assert _token_calls(fake) == 0
    assert _live_cookie(response, OAUTH_COOKIE)["max-age"] == "0"


def test_a_session_value_cannot_be_offered_as_a_transaction() -> None:
    """The two signed purposes cannot be substituted for one another."""
    client, fake = _console()
    transaction = _begin(client, fake)
    assert _callback(client, transaction).status_code == 303
    session_value = client.cookies.get(SESSION_COOKIE)
    assert session_value is not None

    crossed = TestClient(
        create_app(HOSTED, clock=CLOCK, provider=build_provider(fake, clock=CLOCK)),
        base_url="https://testserver",
        cookies={OAUTH_COOKIE: session_value},
    )
    response = _callback(crossed, transaction)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?retry=1"
    assert crossed.cookies.get(session_cookie_name(HOSTED)) is None


def test_a_cancelled_sign_in_is_a_generic_retry() -> None:
    """A provider error never reaches the token endpoint or the page."""
    client, fake = _console()
    transaction = _begin(client, fake)

    response = client.get(
        "/auth/callback",
        params={"error": "access_denied", "state": transaction.state},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login?retry=1"
    assert "access_denied" not in response.headers["location"]
    assert _token_calls(fake) == 0
    assert client.cookies.get(OAUTH_COOKIE) is None
    assert session_cookie_name(HOSTED) not in client.cookies


def test_a_non_owner_gets_a_generic_403_and_no_session() -> None:
    """A different verified Google user is refused without being named."""
    client, fake = _console()
    transaction = _begin(client, fake)
    fake.id_token_overrides.update(
        {"email": "intruder@example.com", "email_verified": True}
    )

    response = _callback(client, transaction)

    assert response.status_code == 403
    assert "intruder@example.com" not in response.text
    assert "does not have access" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert client.cookies.get(OAUTH_COOKIE) is None
    assert session_cookie_name(HOSTED) not in client.cookies


def test_missing_and_malformed_callback_parameters_are_refused() -> None:
    """A direct visit and a junk attempt both get the generic retry."""
    client, fake = _console()
    _begin(client, fake)

    for params in ({}, {"code": "fake-code"}, {"code": "", "state": ""}):
        response = client.get("/auth/callback", params=params, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login?retry=1"

    assert _token_calls(fake) == 0

    junk = TestClient(
        create_app(HOSTED, clock=CLOCK, provider=build_provider(fake, clock=CLOCK)),
        base_url="https://testserver",
        cookies={OAUTH_COOKIE: "not-a-signed-value"},
    )
    response = junk.get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )

    assert response.headers["location"] == "/login?retry=1"
    assert _live_cookie(response, OAUTH_COOKIE)["max-age"] == "0"
