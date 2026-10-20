"""The default-deny guard: its exact public surface and its refusals.

Every test here uses the real middleware over a configured console. Denials
are asserted at the ASGI boundary: no route, dependency, body read, source or
store is touched before the guard has answered.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.auth.sessions import SessionCookie, session_cookie_name
from app.config import Config
from app.dependencies import get_invites
from app.domain.auth import ConsoleSession
from app.main import create_app
from app.middleware.auth import AuthGuardMiddleware
from tests.auth.console import SESSION_ID, auth_settings, console, session_for
from tests.auth.support import NOW, google_config

PUBLIC_GET = {"/login", "/healthz", "/auth/google", "/auth/callback"}


def _public_client(settings: Config | None = None) -> TestClient:
    """A configured console with no session cookie."""
    resolved = settings or google_config()
    app = create_app(resolved, clock=lambda: NOW)
    return TestClient(app, base_url="https://testserver")


def _cookie_header(settings: Config, value: str) -> list[tuple[bytes, bytes]]:
    return [(b"cookie", f"{session_cookie_name(settings)}={value}".encode())]


def _http_scope(
    method: str, path: str, headers: list[tuple[bytes, bytes]] | None = None
) -> dict[str, object]:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": headers or [],
        "state": {},
    }


def _run_guard(
    guard: AuthGuardMiddleware, scope: dict[str, object]
) -> tuple[list[object], list[dict[str, Any]]]:
    """Invoke the middleware directly, recording app calls and sent messages."""
    called: list[object] = []
    messages: list[dict[str, Any]] = []

    async def app(inner: object, receive: object, send: object) -> None:
        called.append(inner)

    guard.app = app

    async def receive() -> dict[str, object]:
        raise AssertionError("a denied request must not read its body")

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    asyncio.run(guard(scope, receive, send))  # type: ignore[arg-type]
    return called, messages


def test_the_public_surface_is_exact_and_everything_else_is_denied() -> None:
    """Login, Google's two hops, health and static are the only exceptions."""
    client = _public_client()

    assert client.get("/login").status_code == 200
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/static/css/tokens.css").status_code == 200
    assert client.get("/static/vendor/htmx.min.js").status_code == 200

    for path in ("/", "/requests", "/docs", "/redoc", "/openapi.json", "/invites"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"].startswith("/login?next=")

    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/", follow_redirects=False)
        assert response.status_code == 401, method
        assert response.headers["hx-redirect"] == "/login"


def _walk_routes(routes: Iterable[Any], prefix: str = "") -> Iterator[tuple[Any, str]]:
    """Every real route, descending the wrapper FastAPI puts around includes."""
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            child = prefix + (getattr(context, "prefix", "") or "")
            yield from _walk_routes(original.routes, child)
            continue
        path = getattr(route, "path", None)
        if path is not None:
            yield route, prefix + path


def _protected_routes() -> Iterator[tuple[str, str]]:
    """Every non-public method/path pair on the fixture, invite and gcp apps."""
    for settings in (
        Config(),
        Config(invites_enabled=True),
        Config(source="gcp", gcp_project_id="demo-project"),
        Config(source="gcp", gcp_project_id="demo-project", invites_enabled=True),
    ):
        app = create_app(settings, clock=lambda: NOW)
        for route, path in _walk_routes(app.routes):
            methods = getattr(route, "methods", None)
            if methods is None:
                continue
            for method in methods - {"OPTIONS"}:
                if method in {"GET", "HEAD"} and path in PUBLIC_GET:
                    continue
                yield method, re.sub(r"\{[^}]+\}", "x", path)


def test_every_route_is_protected_for_invites_and_crashes_on_and_off() -> None:
    """A full route sweep over four surfaces leaves no unguarded method."""
    seen = set(_protected_routes())
    assert ("GET", "/requests") in seen
    assert ("POST", "/invites") in seen
    assert ("GET", "/crashes") in seen
    assert ("POST", "/auth/logout") in seen
    assert len(seen) > 20

    for settings in (
        Config(),
        Config(invites_enabled=True),
        Config(source="gcp", gcp_project_id="demo-project"),
    ):
        app = create_app(settings, clock=lambda: NOW)
        client = TestClient(app, base_url="https://testserver")
        for route, path in _walk_routes(app.routes):
            methods = getattr(route, "methods", None)
            if methods is None:
                continue
            for method in methods - {"OPTIONS"}:
                if method in {"GET", "HEAD"} and path in PUBLIC_GET:
                    continue
                url = re.sub(r"\{[^}]+\}", "x", path)
                response = client.request(method, url, follow_redirects=False)
                if method in {"GET", "HEAD"} and not url.startswith("/partials"):
                    assert response.status_code == 303, (method, url)
                else:
                    assert response.status_code == 401, (method, url)


def _paths(settings: Config) -> set[str]:
    """Every route path an app built from these settings exposes."""
    app = create_app(settings, clock=lambda: NOW)
    return {path for _, path in _walk_routes(app.routes)}


def test_the_route_sweep_sees_the_invite_and_crash_surfaces_both_ways() -> None:
    """The enumeration itself proves its settings actually change the routes."""
    plain = _paths(Config())
    more = _paths(Config(invites_enabled=True))
    gcp = _paths(Config(source="gcp", gcp_project_id="demo-project"))

    assert "/invites" in more and "/invites" not in plain
    assert "/crashes" in plain and "/crashes" not in gcp


def test_a_route_added_after_the_app_is_built_is_still_denied() -> None:
    """A new route inherits the guard; it is not public by accident."""
    signed = console()
    hits: list[bool] = []

    @signed.app.get("/_synthetic")
    def synthetic() -> dict[str, bool]:
        hits.append(True)
        return {"ok": True}

    unsigned = TestClient(signed.app, base_url="https://testserver")
    denied = unsigned.get("/_synthetic", follow_redirects=False)

    assert denied.status_code == 303
    assert denied.headers["location"].startswith("/login?next=")
    assert hits == []
    assert signed.client.get("/_synthetic").json() == {"ok": True}
    assert hits == [True]


def test_an_unhandled_private_failure_keeps_the_response_policy() -> None:
    """A framework-generated 500 does not escape the security headers."""
    signed = console()

    @signed.app.get("/_synthetic_500")
    def boom() -> None:
        raise RuntimeError("PRIVATE-EXCEPTION")

    value = SessionCookie.from_config(signed.settings, lambda: NOW).dumps(
        signed.session
    )
    client = TestClient(
        signed.app,
        base_url="https://testserver",
        cookies={session_cookie_name(signed.settings): value},
        raise_server_exceptions=False,
    )

    response = client.get("/_synthetic_500")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "PRIVATE-EXCEPTION" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" in response.headers


def test_an_unhandled_public_failure_keeps_the_response_policy() -> None:
    """The outer error boundary applies to public routes too."""
    app = create_app(google_config(), clock=lambda: NOW)

    async def boom(request: object) -> None:
        raise RuntimeError("PRIVATE-PUBLIC-EXCEPTION")

    app.router.routes.insert(0, Route("/healthz", boom, methods=["GET"]))
    client = TestClient(
        app, base_url="https://testserver", raise_server_exceptions=False
    )

    response = client.get("/healthz")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "PRIVATE-PUBLIC-EXCEPTION" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" in response.headers


def test_an_unhandled_loopback_failure_does_not_send_hsts() -> None:
    """A local HTTP app must not pin the browser to HTTPS after an error."""
    settings = google_config(
        auth_public_origin="http://127.0.0.1:8080",
        auth_callback_url="http://127.0.0.1:8080/auth/callback",
    )
    app = create_app(settings, clock=lambda: NOW)

    async def boom(request: object) -> None:
        raise RuntimeError("PRIVATE-LOOPBACK-EXCEPTION")

    app.router.routes.insert(0, Route("/healthz", boom, methods=["GET"]))
    client = TestClient(
        app, base_url="http://127.0.0.1:8080", raise_server_exceptions=False
    )

    response = client.get("/healthz")

    assert response.status_code == 500
    assert "strict-transport-security" not in response.headers


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
