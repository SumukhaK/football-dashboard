"""Sign-in discovery failures must use the same clean retry as the callback."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.transactions import TransactionCookie
from app.domain.auth import OAUTH_COOKIE, SESSION_COOKIE
from app.main import create_app
from app.services.auth import AuthPolicy
from tests.auth.support import NOW, FakeGoogle, build_provider, google_config


@pytest.mark.parametrize("outage", ["http", "transport"])
def test_discovery_failure_clears_the_attempt_and_offers_a_generic_retry(
    outage: str, caplog: pytest.LogCaptureFixture
) -> None:
    """An unavailable Google discovery endpoint never becomes an unhandled 500."""
    settings = google_config()
    fake = FakeGoogle()
    if outage == "http":
        fake.discovery_status = 503
    else:
        fake.outage = httpx.ConnectError("PRIVATE-DISCOVERY-DETAIL")
    provider = build_provider(fake, clock=lambda: NOW)
    client = TestClient(
        create_app(settings, clock=lambda: NOW, provider=provider),
        base_url="https://testserver",
        raise_server_exceptions=False,
    )
    pending = AuthPolicy.from_config(settings).new_transaction(
        "pending-state", "pending-nonce", "pending-verifier", "/", lambda: NOW
    )
    previous = TransactionCookie.from_config(settings, lambda: NOW).dumps(pending)
    client.cookies.set(OAUTH_COOKIE, previous)

    with caplog.at_level(logging.INFO, logger="app.auth"):
        response = client.get("/auth/google", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?retry=1"
    assert response.headers["cache-control"] == "no-store"
    assert any(
        header.startswith(f"{OAUTH_COOKIE}=") and "Max-Age=0" in header
        for header in response.headers.get_list("set-cookie")
    )
    assert client.cookies.get(SESSION_COOKIE) is None
    assert "sign-in failed: provider" in caplog.text
    assert "PRIVATE-DISCOVERY-DETAIL" not in caplog.text
    assert previous not in caplog.text
