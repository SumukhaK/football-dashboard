"""Logout, loopback cookies, provider construction and the auth logging and caching rules."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import (
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.config import Config
from app.domain.auth import (
    OAUTH_COOKIE,
    OAUTH_COOKIE_LOCAL,
    SESSION_COOKIE,
    SESSION_COOKIE_LOCAL,
)
from app.factory import create_app
from app.services.auth import AuthPolicy, IdentityProvider
from tests.auth.support import (
    FakeGoogle,
    build_provider,
    google_config,
)
from tests.routers.auth_helpers import (
    CLOCK,
    HOSTED,
    _begin,
    _callback,
    _console,
    _live_cookie,
    _session,
)


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
