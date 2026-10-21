"""The default-deny guard: its exact public surface and its refusals.

Every test here uses the real middleware over a configured console. Denials
are asserted at the ASGI boundary: no route, dependency, body read, source or
store is touched before the guard has answered.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.testclient import TestClient
from starlette.routing import Route

from app.auth.sessions import SessionCookie, session_cookie_name
from app.config import Config
from app.factory import create_app
from tests.auth.console import console
from tests.auth.support import NOW, google_config
from tests.routers.guard_helpers import (
    PUBLIC_GET,
    _public_client,
)


def test_the_public_surface_is_exact_and_everything_else_is_denied() -> None:
    """Login, Google's two hops, health and static are the only exceptions."""
    client = _public_client()

    assert client.get("/login").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
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
