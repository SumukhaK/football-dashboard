"""Send one HTTP request through an ASGI app with chosen connection facts."""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Message

Address = tuple[str, int] | None


def call(
    app: ASGIApp,
    path: str,
    *,
    server: Address,
    client: Address,
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "GET",
) -> tuple[int, bytes]:
    """The status and body the app answers for one request to ``path``."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "server": server,
        "client": client,
    }
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    async def run() -> None:
        await app(scope, receive, send)

    asyncio.run(run())
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return int(start["status"]), body
