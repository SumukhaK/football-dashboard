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
    sink: list[Message] | None = None,
) -> tuple[int, bytes]:
    """The status and body the app answers for one request to ``path``.

    Pass ``sink`` to also receive every ASGI message the app sent.
    """
    scope = _http_scope(path, server, client, headers or [], method)
    sent: list[Message] = [] if sink is None else sink

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


def _http_scope(
    path: str,
    server: Address,
    client: Address,
    headers: list[tuple[bytes, bytes]],
    method: str,
) -> dict[str, object]:
    """An HTTP scope carrying exactly the given connection facts."""
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "server": server,
        "client": client,
    }
