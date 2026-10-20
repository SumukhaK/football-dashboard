"""Tests for the minimal public health endpoint."""

from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


def test_health_endpoint_returns_only_ok() -> None:
    """GET /healthz says the process is alive and nothing else."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_endpoint_with_gcp_source_stays_minimal() -> None:
    """The liveness answer does not expose the source or contract version."""
    app = create_app(Config(source="gcp", gcp_project_id="test-project"))
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
