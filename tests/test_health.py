"""Tests for health endpoint."""

from fastapi.testclient import TestClient

from app.config import Config
from app.main import create_app


def test_health_endpoint_returns_ok_and_version() -> None:
    """GET /healthz should return status ok and contract version 1.0.0."""
    Config()
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["contract_version"] == "1.0.0"


def test_health_endpoint_with_gcp_source() -> None:
    """Health endpoint works with gcp source (if project_id provided)."""
    Config(source="gcp", gcp_project_id="test-project")
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["contract_version"] == "1.0.0"
