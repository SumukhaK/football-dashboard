"""The guard on denied writes, redirects, static paths, sessions and other scope types."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import SessionCookie, session_cookie_name
from app.config import Config
from app.dependencies import get_invites
from app.domain.auth import ConsoleSession
from app.factory import create_app
from app.middleware.auth import AuthGuardMiddleware
from tests.auth.console import SESSION_ID, auth_settings, console, session_for
from tests.auth.support import NOW, google_config
from tests.routers.guard_helpers import (
    _http_scope,
    _public_client,
    _run_guard,
)


def test_a_denied_write_reads_no_body_and_calls_no_route() -> None:
    """The ASGI refusal happens before the body or the application is touched."""
    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    called, messages = _run_guard(guard, _http_scope("POST", "/invites"))

    assert called == []
    assert messages[0]["status"] == 401
    assert (b"hx-redirect", b"/login") in messages[0]["headers"]


def test_a_denied_invite_write_never_resolves_the_store() -> None:
    """The invite dependency is not built for a caller with no session."""
    signed = console(Config(invites_enabled=True))

    def explode() -> None:
        raise AssertionError("the store must not be touched")

    signed.app.dependency_overrides[get_invites] = explode
    unsigned = TestClient(signed.app, base_url="https://testserver")
    response = unsigned.post(
        "/invites", data={"email": "a@b.c"}, follow_redirects=False
    )

    assert response.status_code == 401


def test_a_partial_or_an_htmx_page_gets_a_header_redirect_not_a_login_document() -> (
    None
):
    """HTMX must not swap a login page into a panel."""
    client = _public_client()

    partial = client.get("/partials/overview", follow_redirects=False)
    assert partial.status_code == 401
    assert partial.headers["hx-redirect"] == "/login"
    assert "<!DOCTYPE" not in partial.text

    boosted = client.get(
        "/requests", headers={"hx-request": "true"}, follow_redirects=False
    )
    assert boosted.status_code == 401
    assert boosted.headers["hx-redirect"] == "/login"
    assert "<!DOCTYPE" not in boosted.text

    post = client.post("/invites", data={"email": "a@b.c"}, follow_redirects=False)
    assert post.status_code == 401
    assert post.headers["hx-redirect"] == "/login"


def test_next_is_a_local_path_with_its_query_and_never_an_open_redirect() -> None:
    """The login return path is quoted locally, and the Location is always /login."""
    client = _public_client()

    response = client.get(
        "/requests?hours=24&event=http.request", follow_redirects=False
    )
    location = response.headers["location"]
    assert location.startswith("/login?")
    assert parse_qs(urlsplit(location).query)["next"] == [
        "/requests?hours=24&event=http.request"
    ]

    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    _, messages = _run_guard(guard, _http_scope("GET", "//evil.example/x"))
    hostile = dict(messages[0]["headers"])[b"location"].decode()
    assert hostile.startswith("/login?")
    assert parse_qs(urlsplit(hostile).query)["next"] == ["//evil.example/x"]


@pytest.mark.parametrize(
    "path",
    (
        "/static/../requests",
        "/static/%2e%2e/requests",
        "/static\\..\\requests",
        "/static//requests",
        "/static/.hidden",
        "/Static/css/tokens.css",
        "/partials/../requests",
        "/requests/../access",
    ),
)
def test_a_prefix_or_traversal_path_is_not_public(path: str) -> None:
    """Static and partial prefixes cannot be bent into another route."""
    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    called, messages = _run_guard(guard, _http_scope("GET", path))

    assert called == []
    assert messages[0]["status"] in {303, 401}
    if messages[0]["status"] == 303:
        assert dict(messages[0]["headers"])[b"location"].startswith(b"/login?next=")


def test_a_plain_static_path_reaches_the_static_mount() -> None:
    """The ordinary static path is the exception the guard is designed for."""
    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    called, _ = _run_guard(guard, _http_scope("GET", "/static/css/tokens.css"))
    assert called != []


def test_a_static_asset_is_public_only_for_a_safe_method() -> None:
    """The mount is public for reads; a write is refused before it arrives."""
    client = _public_client()

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)(
            "/static/css/tokens.css", follow_redirects=False
        )
        assert response.status_code == 401, method
        assert response.headers["hx-redirect"] == "/login"


def test_a_session_for_another_address_is_forbidden_and_cleared() -> None:
    """A valid signature for a different account is not the owner."""
    settings = auth_settings()
    app = create_app(settings, clock=lambda: NOW)
    foreign = session_for(settings, lambda: NOW, email="someone@else.example")
    value = SessionCookie.from_config(settings, lambda: NOW).dumps(foreign)
    client = TestClient(
        app,
        base_url="https://testserver",
        cookies={session_cookie_name(settings): value},
    )

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 403
    assert response.text == "Forbidden"
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert "someone@else.example" not in response.text


def test_an_expired_session_is_denied_and_cleared() -> None:
    """An absolute expiry is authoritative even when the signature is valid."""
    settings = auth_settings()
    app = create_app(settings, clock=lambda: NOW)
    expired = ConsoleSession(
        subject="google-owner-subject",
        email=settings.owner_email,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
        session_id="expired-session",
    )
    value = SessionCookie.from_config(settings, lambda: NOW).dumps(expired)
    client = TestClient(
        app,
        base_url="https://testserver",
        cookies={session_cookie_name(settings): value},
    )

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_a_forged_session_cookie_is_denied_and_cleared() -> None:
    """A value that is not a signed session never reaches a page."""
    settings = auth_settings()
    app = create_app(settings, clock=lambda: NOW)
    client = TestClient(
        app,
        base_url="https://testserver",
        cookies={session_cookie_name(settings): "forged"},
    )

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_forwarded_and_identity_headers_do_not_authenticate() -> None:
    """Only the signed session cookie decides who the caller is."""
    client = _public_client()
    owner = google_config().owner_email

    response = client.get(
        "/",
        headers={
            "x-forwarded-user": owner,
            "x-remote-user": owner,
            "remote-user": owner,
            "x-email": owner,
            "x-forwarded-proto": "https",
            "x-forwarded-host": "console.example",
            "authorization": "Bearer not-a-session",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_an_owner_reaches_pages_and_partials() -> None:
    """The valid session is the one path through the guard."""
    signed = console()

    assert signed.client.get("/").status_code == 200
    assert signed.client.get("/requests").status_code == 200
    assert signed.client.get("/partials/overview").status_code == 200
    assert signed.client.get("/healthz").json() == {"status": "ok"}


def test_owner_logout_is_a_form_with_the_session_csrf_token() -> None:
    """The only write the shell offers carries the hidden token."""
    signed = console()
    body = signed.client.get("/").text

    assert 'action="/auth/logout"' in body
    assert 'method="post"' in body
    assert 'name="csrf_token"' in body
    assert f'value="{SESSION_ID}"' in body


def test_docs_and_the_schema_are_not_served_to_an_owner_either() -> None:
    """Disabling the framework routes removes them rather than guarding HTML."""
    signed = console()

    assert signed.client.get("/docs").status_code == 404
    assert signed.client.get("/redoc").status_code == 404
    assert signed.client.get("/openapi.json").status_code == 404


def test_an_unknown_scope_type_is_passed_through() -> None:
    """Only HTTP, WebSocket and lifespan scopes are this middleware's business."""
    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    called, _ = _run_guard(guard, {"type": "custom"})
    assert called != []


def test_a_websocket_is_closed_and_lifespan_passes() -> None:
    """No websocket inherits an unauthenticated connection."""
    guard = AuthGuardMiddleware(
        app=None, settings=auth_settings(), clock=lambda: NOW  # type: ignore[arg-type]
    )
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(guard({"type": "websocket"}, None, send))  # type: ignore[arg-type]
    assert messages == [{"type": "websocket.close", "code": 1008}]

    called, _ = _run_guard(guard, {"type": "lifespan"})
    assert called != []


def test_a_head_request_gets_the_redirect_with_no_body() -> None:
    """HEAD is a safe method but still never gets a private body."""
    response = _public_client().head("/requests", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")
    assert response.content == b""
