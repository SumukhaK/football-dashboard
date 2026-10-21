"""The sample-data demonstration carries the same response policy as Google mode."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message

from app.config import Config
from app.domain.listen import ListenAddress
from app.factory import create_app
from tests.middleware.asgi import call

LOCAL = ListenAddress("127.0.0.1", 8000)
NONCE = re.compile(r'<script nonce="([^"]+)"')
JSON_NONCE = re.compile(r'<script type="application/json"[^>]*nonce="([^"]+)"')


def _demo() -> TestClient:
    app = create_app(Config(auth_mode="fixture"), listen=LOCAL)
    return TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1))


def _script_src(headers: object) -> str:
    csp = str(headers["content-security-policy"])  # type: ignore[index]
    return next(p for p in csp.split(";") if p.strip().startswith("script-src"))


@pytest.mark.parametrize("path", ["/", "/requests", "/errors", "/partials/overview"])
def test_demo_pages_carry_the_full_response_policy(path: str) -> None:
    """nosniff, frame denial, no-store and a nonce CSP on every page."""
    response = _demo().get(path)

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_the_theme_and_chart_scripts_carry_the_header_nonce() -> None:
    """Without the shared nonce the CSP would block the theme and the charts."""
    home = _demo().get("/partials/overview")
    page = _demo().get("/")

    for response, pattern in ((page, NONCE), (home, JSON_NONCE)):
        found = pattern.search(response.text)
        assert found is not None and found.group(1)
        assert f"'nonce-{found.group(1)}'" in _script_src(response.headers)


def test_each_request_gets_a_fresh_nonce() -> None:
    """A nonce reused across responses would let an injected script borrow it."""
    client = _demo()

    first, second = (_script_src(client.get("/").headers) for _ in range(2))

    assert first != second


def test_static_assets_stay_cacheable() -> None:
    """Static files keep their cache headers; documents are no-store."""
    response = _demo().get("/static/css/tokens.css")

    assert response.status_code == 200
    assert response.headers.get("cache-control") != "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_refused_lan_request_also_carries_the_policy() -> None:
    """The loopback refusal is a response like any other."""
    app = create_app(Config(auth_mode="fixture"), listen=LOCAL)
    sent: list[Message] = []

    status, _ = call(
        app, "/", server=("192.0.2.50", 8000), client=("192.0.2.20", 5), sink=sent
    )

    headers = dict(sent[0]["headers"])
    assert status == 403
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"cache-control"] == b"no-store"
