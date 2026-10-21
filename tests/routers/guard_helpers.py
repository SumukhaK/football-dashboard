"""Shared builders for the guard tests: clients, cookies and raw ASGI calls."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from app.auth.sessions import session_cookie_name
from app.config import Config
from app.factory import create_app
from app.middleware.auth import AuthGuardMiddleware
from tests.auth.support import NOW, google_config

PUBLIC_GET = {"/login", "/health", "/healthz", "/auth/google", "/auth/callback"}


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
