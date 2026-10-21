"""The shell says when it is showing the local sample-data demonstration."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.domain.listen import ListenAddress
from app.main import create_app
from tests.auth.console import console_client

NOTICE = "Sample data — local demonstration."
PAGES = ("/", "/errors", "/requests", "/assistant", "/crashes", "/data", "/access")


def _demo_client() -> TestClient:
    """The fixture demonstration as its launcher serves it: loopback both ends."""
    app = create_app(
        Config(auth_mode="fixture"), listen=ListenAddress("127.0.0.1", 8000)
    )
    return TestClient(
        app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 51000)
    )


@pytest.mark.parametrize("path", PAGES)
def test_every_page_of_the_demonstration_carries_the_notice(path: str) -> None:
    """The notice sits in the shared shell, so no page can leave it out."""
    body = _demo_client().get(path).text

    assert NOTICE in body
    assert 'class="banner banner-warn sample-mode-notice" role="note"' in body


@pytest.mark.parametrize("path", PAGES)
def test_google_sign_in_never_shows_the_notice(path: str) -> None:
    """Sample files behind the real owner sign-in are not the demonstration."""
    client = console_client(Config(source="fixture"))

    response = client.get(path)

    assert response.status_code == 200
    assert NOTICE not in response.text
    assert "sample-mode-notice" not in response.text
