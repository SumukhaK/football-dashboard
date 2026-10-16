"""Tests for the invite page routes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.config import Config
from app.dependencies import get_invites
from app.domain.errors import SourceUnavailableError
from app.main import create_app
from app.services.invites import InviteRecord, InviteService

NOW = datetime(2026, 10, 16, 5, 0, tzinfo=UTC)
FORM = {"content-type": "application/x-www-form-urlencoded"}


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
    """A client over the fixture source, with invites on a fake store."""
    app = create_app(Config(invites_enabled=enabled), clock=lambda: NOW)
    service = InviteService(
        store or FakeStore(), lambda: NOW, 7, new_code=lambda: "K7MP-W3QX"
    )
    app.dependency_overrides[get_invites] = lambda: service
    return TestClient(app)


def _post(client: TestClient, body: str, origin: str | None = None) -> str:
    """Post the form body, optionally from ``origin``, and return the text."""
    headers = FORM if origin is None else {**FORM, "origin": origin}
    response = client.post("/invites", content=body, headers=headers)
    assert response.status_code == 200
    text: str = response.text
    return text


def test_disabled_page_and_post_are_404_with_no_nav_link() -> None:
    """With invites off, neither route exists and the nav does not link them."""
    client = _client(enabled=False)
    assert client.get("/invites").status_code == 404
    response = client.post("/invites", content="email=a%40b.c", headers=FORM)
    assert response.status_code == 404
    assert 'href="/invites"' not in client.get("/").text


def test_enabled_page_shows_the_form_and_nav_link() -> None:
    """With invites on, GET /invites renders the email form, uncached."""
    response = _client().get("/invites")
    assert response.status_code == 200
    assert 'name="email"' in response.text
    assert 'href="/invites"' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_valid_post_shows_the_code_once_and_saves_it() -> None:
    """A good email writes the record and shows the code and its expiry."""
    store = FakeStore()
    response = _client(store).post(
        "/invites", content="email=Ann%40Example.com", headers=FORM
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
    headers = {**FORM, "origin": "https://evil.example"}
    response = _client(store).post("/invites", content="email=a%40b.c", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"] == "http_error"
    assert store.records == {}


def test_same_origin_post_is_accepted() -> None:
    """The page's own origin may post."""
    store = FakeStore()
    _post(_client(store), "email=a%40b.c", origin="http://testserver")
    assert "a@b.c" in store.records


def test_store_failure_shows_a_banner() -> None:
    """A refused write is explained on the page, never a 500."""
    text = _post(_client(FakeStore(fail=True)), "email=a%40b.c")
    assert "permission_denied" in text
    assert "K7MP-W3QX" not in text
