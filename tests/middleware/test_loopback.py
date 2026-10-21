"""The fixture demonstration serves this computer only.

Requests are built as raw ASGI scopes so the server and client addresses are
exactly the connection facts a real server would report, not TestClient's
placeholder names.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import Message

from app.config import Config
from app.domain.listen import ListenAddress
from app.main import create_app
from tests.auth.console import auth_settings
from tests.middleware.asgi import Address, call

LOCAL = ListenAddress("127.0.0.1", 8000)
LAN = ("192.0.2.20", 51000)
LAN_SERVER = ("192.0.2.50", 8000)
V4 = ("127.0.0.1", 8000)
V4_CLIENT = ("127.0.0.1", 51000)


def _fixture_app(listen: ListenAddress | None = LOCAL) -> tuple[FastAPI, list[str]]:
    """A fixture-mode app with a probe route that records every call it serves."""
    app = create_app(Config(auth_mode="fixture"), listen=listen)
    served: list[str] = []

    @app.get("/_probe")
    def probe() -> dict[str, str]:
        served.append("probe")
        return {"ok": "yes"}

    return app, served


def test_fixture_mode_refuses_a_lan_connection_before_any_page_work() -> None:
    """A LAN server and client address are refused, not served the overview."""
    app = create_app(Config(auth_mode="fixture"), listen=LOCAL)

    status, body = call(app, "/", server=LAN_SERVER, client=LAN)

    assert status == 403
    assert json.loads(body)["error"] == "loopback_only"
    assert "python -m app.demo" in json.loads(body)["detail"]


@pytest.mark.parametrize(
    "server,client",
    [
        (LAN_SERVER, LAN),
        (V4, LAN),
        (LAN_SERVER, V4_CLIENT),
        (("0.0.0.0", 8000), V4_CLIENT),
        (("::", 8000), ("::1", 51000)),
        (None, V4_CLIENT),
        (V4, None),
        (("localhost", 8000), ("localhost", 51000)),
        (("testserver", 80), ("testclient", 50000)),
        (("::ffff:192.0.2.50", 8000), ("::ffff:192.0.2.20", 51000)),
    ],
)
def test_any_non_loopback_or_missing_address_is_refused(
    server: Address, client: Address
) -> None:
    """Both ends must be loopback IP literals; a name or a gap is not proof."""
    app, served = _fixture_app()

    status, _ = call(app, "/_probe", server=server, client=client)

    assert status == 403
    assert served == []


@pytest.mark.parametrize(
    "server,client",
    [
        (V4, V4_CLIENT),
        (("127.0.0.2", 8000), ("127.0.0.3", 51000)),
        (("::1", 8000), ("::1", 51000)),
    ],
)
def test_loopback_connections_on_a_loopback_bind_are_served(
    server: Address, client: Address
) -> None:
    """IPv4 and IPv6 loopback both reach the demonstration."""
    app, served = _fixture_app()

    status, _ = call(app, "/_probe", server=server, client=client)

    assert status == 200
    assert served == ["probe"]


@pytest.mark.parametrize(
    "listen",
    [
        None,
        ListenAddress("0.0.0.0", 8000),
        ListenAddress("::", 8000),
        ListenAddress("192.0.2.50", 8000),
        ListenAddress("localhost", 8000),
    ],
    ids=["unknown", "wildcard-v4", "wildcard-v6", "lan", "name"],
)
def test_an_unknown_or_open_bind_refuses_even_a_loopback_connection(
    listen: ListenAddress | None,
) -> None:
    """A wildcard bind reached through loopback still exposes the LAN."""
    app, served = _fixture_app(listen)

    status, _ = call(app, "/_probe", server=V4, client=V4_CLIENT)

    assert status == 403
    assert served == []


def test_spoofed_headers_never_admit_a_lan_client() -> None:
    """Host, Origin and forwarded headers are the client's to choose."""
    app, served = _fixture_app()
    headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"origin", b"http://127.0.0.1:8000"),
        (b"x-forwarded-for", b"127.0.0.1"),
        (b"x-real-ip", b"127.0.0.1"),
        (b"forwarded", b"for=127.0.0.1;host=127.0.0.1"),
    ]

    status, _ = call(app, "/_probe", server=LAN_SERVER, client=LAN, headers=headers)

    assert status == 403
    assert served == []


def test_a_refused_head_request_carries_no_body() -> None:
    """HEAD gets the refusal status without a body."""
    app, _ = _fixture_app()

    status, body = call(app, "/", server=LAN_SERVER, client=LAN, method="HEAD")

    assert status == 403
    assert body == b""


def test_a_lan_websocket_is_closed() -> None:
    """No websocket is offered; a LAN one is closed before the app sees it."""
    app, _ = _fixture_app()
    sent: list[Message] = []
    scope = {
        "type": "websocket",
        "path": "/",
        "headers": [],
        "server": LAN_SERVER,
        "client": LAN,
    }

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))

    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_google_mode_is_unchanged_on_a_lan_address() -> None:
    """The owner sign-in guard, not the loopback boundary, answers in Google mode."""
    app = create_app(auth_settings())

    status, body = call(app, "/", server=LAN_SERVER, client=LAN)

    assert status == 303
    assert b"loopback_only" not in body


@pytest.mark.parametrize(
    "listen",
    [None, ListenAddress("0.0.0.0", 8000)],
    ids=["unknown", "wildcard"],
)
def test_fixture_mode_refuses_to_start_without_a_loopback_bind(
    listen: ListenAddress | None,
) -> None:
    """``uvicorn app.main:app`` gives no bind, so the server exits at startup."""
    app = create_app(Config(auth_mode="fixture"), listen=listen)

    with pytest.raises(ValueError, match="python -m app.demo"), TestClient(app):
        pass


def test_fixture_mode_starts_on_a_loopback_bind() -> None:
    """The launcher's loopback bind starts, and a loopback client is served."""
    app = create_app(Config(auth_mode="fixture"), listen=LOCAL)

    with TestClient(app, base_url="http://127.0.0.1:8000", client=V4_CLIENT) as client:
        assert client.get("/healthz").status_code == 200
