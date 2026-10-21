"""Launch the sample-data demonstration on this computer only.

    uv run python -m app.demo [--host 127.0.0.1] [--port 8000]

The launcher binds the listening socket itself, checks the address the
operating system actually bound, and hands that socket and its address to the
application. ``auth_mode=fixture`` refuses to serve without that fact, so a
plain ``uvicorn app.main:app --host 0.0.0.0`` cannot expose the demonstration.
"""

from __future__ import annotations

import argparse
import socket
from collections.abc import Callable, Sequence

import uvicorn
from fastapi import FastAPI

from app import config
from app.domain.listen import ListenAddress, is_loopback
from app.factory import create_app

Serve = Callable[[FastAPI, socket.socket], None]


def bind_loopback(host: str, port: int) -> tuple[socket.socket, ListenAddress]:
    """A listening socket on a loopback IP literal, and the address it got."""
    if not is_loopback(host):
        raise SystemExit(
            f"--host {host} is not a loopback address: the sample-data "
            "demonstration serves this computer only (use 127.0.0.1 or ::1)"
        )
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    bound = sock.getsockname()
    listen = ListenAddress(host=str(bound[0]), port=int(bound[1]))
    if not listen.loopback:
        sock.close()
        raise SystemExit(f"the socket was bound to {listen.host}, not loopback")
    sock.listen(socket.SOMAXCONN)
    return sock, listen


def _serve(app: FastAPI, sock: socket.socket) -> None:
    """Run uvicorn on the socket already bound, never on a host it chooses."""
    # proxy_headers off: the client address is the real peer, never a header.
    uvicorn.Server(uvicorn.Config(app, proxy_headers=False)).run(sockets=[sock])


def main(argv: Sequence[str] | None = None, serve: Serve = _serve) -> None:
    """Bind loopback, build the fixture app with that bind, and serve it."""
    parser = argparse.ArgumentParser(prog="python -m app.demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    # An explicit keyword wins over the environment, so the demo is always the
    # fixture mode; Config still refuses a real source, invites or K_REVISION.
    settings = config.Config(auth_mode="fixture")
    sock, listen = bind_loopback(args.host, args.port)
    print(f"Sample data on http://{_url_host(listen.host)}:{listen.port}")
    serve(create_app(settings, listen=listen), sock)


def _url_host(host: str) -> str:
    """An IPv6 literal needs brackets in a URL."""
    return f"[{host}]" if ":" in host else host


if __name__ == "__main__":
    main()
