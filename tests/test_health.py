"""Tests for the minimal public health endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health_endpoint_returns_only_ok(path: str) -> None:
    """Both exact liveness paths expose only process health and no-store headers."""
    app = create_app()
    client = TestClient(app)

    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("path", ["/health", "/healthz"])
def test_health_endpoint_with_gcp_source_stays_minimal(path: str) -> None:
    """The liveness answer does not expose the source or contract version."""
    app = create_app(Config(source="gcp", gcp_project_id="test-project"))
    client = TestClient(app)

    response = client.get(path, follow_redirects=False)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/health/", "/health/private", "/healthcheck"])
def test_health_exception_does_not_allow_other_paths(path: str) -> None:
    """Adding hosted liveness does not expose a prefix or trailing-slash alias."""
    client = TestClient(create_app())
    assert client.get(path, follow_redirects=False).status_code == 303


def test_health_writes_require_a_session() -> None:
    """Only safe methods may use the public liveness exception."""
    response = TestClient(create_app()).post("/health")
    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
