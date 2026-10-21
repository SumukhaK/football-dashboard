"""Shared steps for the sign-in route tests: a console, a started login and its callback."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.auth.sessions import (
    SessionCookie,
    session_cookie_name,
)
from app.auth.transactions import TransactionCookie
from app.config import Config
from app.domain.auth import (
    OAUTH_COOKIE,
    LoginTransaction,
)
from app.factory import create_app
from tests.auth.support import (
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
