"""Tests for the invite page routes, its Origin and its session CSRF token."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import cast

import httpx
from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_invites
from app.domain.errors import SourceUnavailableError
from app.services.invites import InviteRecord, InviteService
from tests.auth.console import SESSION_ID, console

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
FORM = {"content-type": "application/x-www-form-urlencoded"}
ORIGIN = "https://console.example"
CSRF = SESSION_ID


class FakeStore:
    """Keeps saved records in memory, or fails every write."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.records: dict[str, InviteRecord] = {}

    def save(self, email: str, record: InviteRecord) -> None:
        """Keep the record, or fail like a refused Firestore write."""
        if self.fail:
            raise SourceUnavailableError("permission_denied", "firestore: denied")
        self.records[email] = record


def _client(store: FakeStore | None = None, enabled: bool = True) -> TestClient:
    """A signed-in client over the fixture source, with invites on a fake store."""
    signed = console(Config(invites_enabled=enabled), clock=lambda: NOW)
    service = InviteService(
        store or FakeStore(), lambda: NOW, 7, new_code=lambda: "K7MP-W3QX"
    )
    signed.app.dependency_overrides[get_invites] = lambda: service
    return signed.client


def _raw_post(
    client: TestClient,
    body: str,
    *,
    origin: str | None = ORIGIN,
    csrf: str | None = CSRF,
) -> httpx.Response:
    """Post the form with an explicit Origin and CSRF choice."""
    fields = body if csrf is None else f"{body}&csrf_token={csrf}"
    headers = dict(FORM)
    if origin is not None:
        headers["origin"] = origin
    return cast(
        httpx.Response, client.post("/invites", content=fields, headers=headers)
    )


def _post(
    client: TestClient,
    body: str,
    *,
    origin: str | None = ORIGIN,
    csrf: str | None = CSRF,
) -> str:
    """Post an accepted form and return the HTMX result text."""
    response = _raw_post(client, body, origin=origin, csrf=csrf)
    assert response.status_code == 200
    return response.text


def test_disabled_page_and_post_are_404_with_no_nav_link() -> None:
    """With invites off, neither route exists and the nav does not link them."""
    client = _client(enabled=False)
    assert client.get("/invites").status_code == 404
    response = client.post("/invites", content="email=a%40b.c", headers=FORM)
    assert response.status_code == 404
    assert 'href="/invites"' not in client.get("/").text


def test_enabled_page_shows_the_form_the_nav_link_and_the_session_csrf() -> None:
    """With invites on, GET /invites renders the form, uncached, with its token."""
    response = _client().get("/invites")
    assert response.status_code == 200
    assert 'name="email"' in response.text
    assert 'name="csrf_token"' in response.text
    assert f'value="{CSRF}"' in response.text
    assert 'href="/invites"' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_valid_post_shows_the_code_once_and_saves_it() -> None:
    """A good email writes the record and shows the code and its expiry."""
    store = FakeStore()
    response = _client(store).post(
        "/invites",
        content=f"email=Ann%40Example.com&csrf_token={CSRF}",
        headers={**FORM, "origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "K7MP-W3QX" in response.text
    assert "23 Oct 05:00 UTC" in response.text
    assert "<!DOCTYPE html>" not in response.text
    record = store.records["ann@example.com"]
    assert record["code_hash"] == hashlib.sha256(b"K7MPW3QX").hexdigest()


def test_invalid_email_shows_an_error_and_saves_nothing() -> None:
    """A bad email gets a message, not a code."""
    store = FakeStore()
    text = _post(_client(store), "email=nope")
    assert "K7MP-W3QX" not in text
    assert "email address" in text
    assert store.records == {}


def test_missing_email_is_an_invalid_email() -> None:
    """An empty form is treated as a bad email."""
    assert "email address" in _post(_client(), "")


def test_cross_origin_post_is_rejected() -> None:
    """A form posted from another site cannot create an invite."""
    store = FakeStore()
    response = _raw_post(_client(store), "email=a%40b.c", origin="https://evil.example")
    assert response.status_code == 403
    assert response.json()["error"] == "http_error"
    assert store.records == {}


def test_a_missing_origin_is_rejected() -> None:
    """The route does not accept a write that carries no Origin at all."""
    store = FakeStore()
    response = _raw_post(_client(store), "email=a%40b.c", origin=None)
    assert response.status_code == 403
    assert store.records == {}


def test_a_matching_host_with_the_wrong_scheme_is_rejected() -> None:
    """Only the configured origin matches, not merely its host name."""
    store = FakeStore()
    response = _raw_post(_client(store), "email=a%40b.c", origin="http://testserver")
    assert response.status_code == 403
    assert store.records == {}


def test_same_origin_post_is_accepted() -> None:
    """The page's own configured origin may post."""
    store = FakeStore()
    _post(_client(store), "email=a%40b.c")
    assert "a@b.c" in store.records


def test_a_missing_csrf_token_is_rejected_before_the_store() -> None:
    """A same-origin post without the session token writes nothing."""
    store = FakeStore()
    response = _raw_post(_client(store), "email=a%40b.c", csrf=None)
    assert response.status_code == 403
    assert store.records == {}


def test_a_foreign_csrf_token_is_rejected_before_the_store() -> None:
    """A wrong token is refused even with the exact Origin."""
    store = FakeStore()
    response = _raw_post(_client(store), "email=a%40b.c", csrf="another-session")
    assert response.status_code == 403
    assert store.records == {}


def test_an_htmx_post_with_origin_and_csrf_is_accepted() -> None:
    """The real HTMX caller sends both the Origin and the hidden token."""
    store = FakeStore()
    response = _client(store).post(
        "/invites",
        content=f"email=a%40b.c&csrf_token={CSRF}",
        headers={**FORM, "origin": ORIGIN, "hx-request": "true"},
    )
    assert response.status_code == 200
    assert "a@b.c" in store.records


def test_store_failure_shows_a_banner() -> None:
    """A refused write is explained on the page, never a 500."""
    text = _post(_client(FakeStore(fail=True)), "email=a%40b.c")
    assert "permission_denied" in text
    assert "K7MP-W3QX" not in text
