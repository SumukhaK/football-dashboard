"""The sample-data launcher binds loopback itself and tells the app so."""

from __future__ import annotations

import socket
import subprocess
import sys

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.demo import bind_loopback, main
from app.domain.listen import ListenAddress


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.0.2.50", "localhost", "", "example.com"]
)
def test_the_launcher_refuses_a_host_that_is_not_a_loopback_literal(
    host: str,
) -> None:
    """A wildcard, LAN or named host is refused before any socket exists."""
    with pytest.raises(SystemExit, match="not a loopback address"):
        bind_loopback(host, 0)


def test_the_launcher_reports_the_address_it_actually_bound() -> None:
    """The listen address comes from the bound socket, not from the argument."""
    sock, listen = bind_loopback("127.0.0.1", 0)
    try:
        assert listen == ListenAddress("127.0.0.1", sock.getsockname()[1])
        assert listen.port > 0
        assert listen.loopback
    finally:
        sock.close()


def test_main_serves_the_fixture_app_on_its_loopback_socket() -> None:
    """The app it serves carries the bind, and fixture mode is forced on."""
    served: list[tuple[FastAPI, socket.socket]] = []

    main(["--port", "0"], serve=lambda app, sock: served.append((app, sock)))

    [(app, sock)] = served
    try:
        assert app.state.config.auth_mode == "fixture"
        assert app.state.listen == ListenAddress("127.0.0.1", sock.getsockname()[1])
    finally:
        sock.close()


def test_main_never_serves_a_wildcard_host() -> None:
    """--host 0.0.0.0 stops before anything is bound or served."""
    served: list[object] = []

    with pytest.raises(SystemExit):
        main(["--host", "0.0.0.0", "--port", "0"], serve=lambda *a: served.append(a))

    assert served == []


def test_main_keeps_the_real_source_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The launcher forces fixture auth, never a fixture source over a real one."""
    monkeypatch.setenv("SOURCE", "gcp")
    monkeypatch.setenv("GCP_PROJECT_ID", "real-project")
    served: list[object] = []

    with pytest.raises(ValidationError, match="loopback demonstration mode"):
        main(["--port", "0"], serve=lambda *a: served.append(a))

    assert served == []


def test_the_launcher_never_builds_the_module_level_app() -> None:
    """Importing the launcher must not also build app.main's environment app.

    A second app logged a second startup line and, with a real source in the
    environment, failed at import instead of with the launcher's own message.
    """
    probe = "import sys, app.demo; print('app.main' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"


def test_uvicorn_still_finds_the_module_level_app() -> None:
    """The Dockerfile and Cloud Run serve ``app.main:app``."""
    from app.main import app

    assert isinstance(app, FastAPI)
