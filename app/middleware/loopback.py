"""The fixture demonstration's boundary: this computer only.

``auth_mode=fixture`` has no sign-in, so it must never be reachable from
another machine. This pure-ASGI middleware answers before any route, source
read or template when any of these is not loopback:

- the address the launcher bound its socket to (``ListenAddress``), which only
  ``python -m app.demo`` supplies, so an unknown or wildcard bind is refused;
- the server address of this connection (``scope["server"]``);
- the client address of this connection (``scope["client"]``).

Host, Origin and forwarded headers are never consulted: a client chooses them.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from starlette.types import ASGIApp, Receive, Scope, Send

from app.domain.listen import ListenAddress, is_loopback

logger = logging.getLogger("app.auth")

DEMO_COMMAND = "uv run python -m app.demo"
REFUSAL = {
    "error": "loopback_only",
    "detail": (
        "The sample-data demonstration serves this computer only. "
        f"Start it with: {DEMO_COMMAND}"
    ),
}


def _host(address: object) -> str | None:
    """The host of an ASGI ``(host, port)`` pair, or None when absent."""
    if isinstance(address, Sequence) and not isinstance(address, str) and address:
        host = address[0]
        return host if isinstance(host, str) else None
    return None


def connection_is_local(scope: Scope, listen: ListenAddress | None) -> bool:
    """Whether the bind, the server side and the client side are all loopback."""
    return (
        listen is not None
        and listen.loopback
        and is_loopback(_host(scope.get("server")))
        and is_loopback(_host(scope.get("client")))
    )


class LoopbackOnlyMiddleware:
    """Refuse every connection that is not loopback on a loopback bind."""

    def __init__(self, app: ASGIApp, *, listen: ListenAddress | None) -> None:
        self.app = app
        self.listen = listen

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket") or connection_is_local(scope, self.listen):
            await self.app(scope, receive, send)
            return
        logger.warning("fixture request refused: not a loopback connection")
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps(REFUSAL).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        head = str(scope.get("method", "GET")).upper() == "HEAD"
        await send({"type": "http.response.body", "body": b"" if head else body})
