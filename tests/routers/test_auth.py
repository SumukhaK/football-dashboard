"""Tests for /login, /auth/google, /auth/callback and POST /auth/logout.

The adapter is the real D9.2 one, wired to the fake Google in tests/auth; the
cookie codecs are the real ones over a frozen clock. Nothing here reaches
Google, and no cookie, code, state or token may appear in a log line.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import (
    SessionCookie,
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.config import Config
from app.domain.auth import (
    OAUTH_COOKIE,
    OAUTH_COOKIE_LOCAL,
    SESSION_COOKIE,
    SESSION_COOKIE_LOCAL,
    LoginTransaction,
)
from app.factory import create_app
from app.services.auth import AuthPolicy, IdentityProvider
from tests.auth.support import (
    CALLBACK,
    NOW,
    FakeGoogle,
    build_provider,
    google_config,
)

HOSTED = google_config()
CLOCK = lambda: NOW


def _console(
    settings: Config = HOSTED, clock: Any = CLOCK, provider: Any = None
) -> tuple[TestClient, FakeGoogle]:
    """A hosted test console over the fake Google, with a frozen clock."""
    fake = FakeGoogle()
    provider = provider or build_provider(fake, clock=clock)
    app = create_app(settings, clock=clock, provider=provider)
    return TestClient(app, base_url="https://testserver"), fake


def _live_cookie(response: Any, name: str) -> dict[str, str]:
    """The Set-Cookie header for one cookie, as lower-cased attributes."""
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            value, *attributes = header.split(";")
            parsed = {"value": value.split("=", 1)[1]}
            for attribute in attributes:
                key, _, setting = attribute.strip().partition("=")
                parsed[key.lower()] = setting or "yes"
            return parsed
    raise AssertionError(
        f"no {name} cookie in {response.headers.get_list('set-cookie')}"
    )


def _begin(
    client: TestClient,
    fake: FakeGoogle,
    next_path: str = "/requests",
) -> LoginTransaction:
    """Start a sign-in through the route and teach the fake its transaction."""
    response = client.get(
        f"/auth/google?next={quote(next_path)}", follow_redirects=False
    )
    assert response.status_code == 303
    value = client.cookies.get(OAUTH_COOKIE)
    assert value is not None
    transaction = TransactionCookie.from_config(HOSTED, CLOCK).loads(value)
    fake.expected_verifier = transaction.code_verifier
    fake.id_token_overrides = {"nonce": transaction.nonce}
    return transaction


def _callback(client: TestClient, transaction: LoginTransaction, **params: str) -> Any:
    query = {"code": "fake-code", "state": transaction.state}
    query.update(params)
    return client.get("/auth/callback", params=query, follow_redirects=False)


def _session(client: TestClient, settings: Config = HOSTED) -> Any:
    value = client.cookies.get(session_cookie_name(settings))
    assert value is not None
    return SessionCookie.from_config(settings, CLOCK).loads(value)


def _token_calls(fake: FakeGoogle) -> int:
    return len([request for request in fake.requests if request.url.path == "/token"])


# --- the login page --------------------------------------------------------


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


# --- /auth/google ----------------------------------------------------------


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


# --- /auth/callback --------------------------------------------------------


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


# --- POST /auth/logout -----------------------------------------------------


def _signed_in() -> tuple[TestClient, FakeGoogle, Any]:
    client, fake = _console()
    transaction = _begin(client, fake)
    assert _callback(client, transaction).status_code == 303
    return client, fake, _session(client)


def test_logout_requires_the_exact_origin_and_csrf() -> None:
    """Missing or foreign origin and a wrong token all fail closed."""
    client, _, session = _signed_in()
    url = "/auth/logout"

    no_origin = client.post(url, data={"csrf_token": session.session_id})
    assert no_origin.status_code == 403
    assert client.cookies.get(SESSION_COOKIE) is not None

    foreign = client.post(
        url,
        data={"csrf_token": session.session_id},
        headers={"origin": "https://evil.example"},
    )
    assert foreign.status_code == 403
    assert client.cookies.get(SESSION_COOKIE) is not None

    wrong = client.post(
        url,
        data={"csrf_token": "not-the-session-token"},
        headers={"origin": HOSTED.auth_public_origin},
    )
    assert wrong.status_code == 403
    assert client.cookies.get(SESSION_COOKIE) is not None


def test_a_valid_logout_expires_both_cookies() -> None:
    """The session is cleared and the browser is sent back to /login."""
    client, _, session = _signed_in()

    response = client.post(
        "/auth/logout",
        data={"csrf_token": session.session_id},
        headers={"origin": HOSTED.auth_public_origin},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert response.headers["cache-control"] == "no-store"
    assert _live_cookie(response, SESSION_COOKIE)["max-age"] == "0"
    assert _live_cookie(response, OAUTH_COOKIE)["max-age"] == "0"
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.cookies.get(OAUTH_COOKIE) is None


def test_get_logout_cannot_mutate_the_session() -> None:
    """Logout is a form post; a link or a prefetch does nothing."""
    client, _, _ = _signed_in()

    response = client.get("/auth/logout", follow_redirects=False)

    assert response.status_code == 405
    assert client.cookies.get(SESSION_COOKIE) is not None


def test_logout_without_a_session_is_refused_by_the_guard() -> None:
    """A write without a session never reaches the logout route."""
    client, _ = _console()

    response = client.post(
        "/auth/logout",
        headers={"origin": HOSTED.auth_public_origin},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
    assert client.cookies.get(SESSION_COOKIE) is None


def test_logout_with_a_forged_session_cookie_is_refused_and_cleared() -> None:
    """A value that is not a session is refused, and the bad cookie is cleared."""
    client = TestClient(
        create_app(
            HOSTED,
            clock=CLOCK,
            provider=build_provider(FakeGoogle(), clock=CLOCK),
        ),
        base_url="https://testserver",
        cookies={SESSION_COOKIE: "not-a-session"},
    )

    response = client.post(
        "/auth/logout",
        headers={"origin": HOSTED.auth_public_origin},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
    assert _live_cookie(response, SESSION_COOKIE)["max-age"] == "0"


def test_an_unconfigured_console_refuses_logout_at_the_guard() -> None:
    """No session codec and no session cookie means the guard refuses first."""
    client = TestClient(
        create_app(Config(), clock=CLOCK),
        base_url="https://testserver",
    )

    response = client.post(
        "/auth/logout",
        headers={"origin": "https://console.example"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"


# --- local mode, unconfigured mode and logs --------------------------------


def test_loopback_uses_its_own_cookie_names_without_secure() -> None:
    """Plain http on 127.0.0.1 cannot use __Host- or Secure."""
    settings = google_config(
        auth_public_origin="http://127.0.0.1:8080",
        auth_callback_url="http://127.0.0.1:8080/auth/callback",
    )
    client, fake = _console(settings)
    start = client.get("/auth/google?next=/", follow_redirects=False)
    cookie = _live_cookie(start, OAUTH_COOKIE_LOCAL)
    assert "secure" not in cookie
    assert cookie["path"] == "/"
    transaction = TransactionCookie.from_config(settings, CLOCK).loads(cookie["value"])
    fake.expected_verifier = transaction.code_verifier
    fake.id_token_overrides = {"nonce": transaction.nonce}

    response = _callback(client, transaction)
    assert response.status_code == 303
    assert _live_cookie(response, SESSION_COOKIE_LOCAL)["path"] == "/"
    assert session_cookie_name(settings) == SESSION_COOKIE_LOCAL
    assert client.cookies.get(SESSION_COOKIE) is None


def test_an_unconfigured_console_refuses_sign_in_without_calling_google() -> None:
    """No settings is a generic 503, not a crash and not a bypass."""
    fake = FakeGoogle()
    client = TestClient(
        create_app(Config(), clock=CLOCK, provider=build_provider(fake, clock=CLOCK)),
        base_url="https://testserver",
    )

    start = client.get("/auth/google", follow_redirects=False)
    callback = client.get(
        "/auth/callback", params={"code": "c", "state": "s"}, follow_redirects=False
    )

    assert start.status_code == 503
    assert callback.status_code == 503
    assert "not configured" in start.text
    assert fake.requests == []


def test_the_provider_is_built_on_first_use_and_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An injected provider is optional; the default is built once, lazily."""
    from app.routers import auth as auth_routes

    fake = FakeGoogle()
    built: list[Any] = []

    def builder(
        settings: Config, policy: AuthPolicy, *, clock: Any
    ) -> IdentityProvider:
        built.append(clock)
        return build_provider(fake, clock=clock)

    monkeypatch.setattr(auth_routes, "GoogleOIDC", builder)
    app = create_app(HOSTED, clock=CLOCK)
    client = TestClient(app, base_url="https://testserver")

    first = client.get("/auth/google", follow_redirects=False)
    second = client.get("/auth/google", follow_redirects=False)

    assert first.status_code == second.status_code == 303
    assert len(built) == 1
    assert app.state.auth_provider is not None


def test_auth_logs_carry_no_code_state_cookie_or_address(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The log says an outcome, never the security parameters or identity."""
    client, fake = _console()
    transaction = _begin(client, fake)
    client.cookies.clear()

    with caplog.at_level(logging.INFO, logger="app.auth"):
        client.get(
            "/auth/callback",
            params={"code": "SENTINEL-CODE", "state": "SENTINEL-STATE"},
            follow_redirects=False,
        )

    assert "sign-in failed" in caplog.text
    for secret in ("SENTINEL-CODE", "SENTINEL-STATE", transaction.state):
        assert secret not in caplog.text

    signed_in, fake = _console()
    transaction = _begin(signed_in, fake)
    session_cookie = None
    with caplog.at_level(logging.INFO, logger="app.auth"):
        response = _callback(signed_in, transaction)
    session_cookie = signed_in.cookies.get(SESSION_COOKIE)

    assert response.status_code == 303
    assert "sign-in accepted" in caplog.text
    assert "sumukh.aithal@gmail.com" not in caplog.text
    assert session_cookie is not None
    assert session_cookie not in caplog.text


def test_every_auth_response_is_uncached() -> None:
    """Login, denial and redirect responses all say no-store."""
    client, fake = _console()
    _begin(client, fake)

    assert client.get("/login").headers["cache-control"] == "no-store"
    refused = client.get(
        "/auth/callback",
        params={"code": "fake-code", "state": "wrong"},
        follow_redirects=False,
    )
    assert refused.headers["cache-control"] == "no-store"
