"""A hand-edited pagination cursor is a 422, never a server error."""

from __future__ import annotations

import pytest

from .requests_helpers import make_client

PATHS = ("/requests", "/partials/requests", "/partials/request_rows")


@pytest.mark.parametrize("path", PATHS)
def test_a_cursor_without_a_timezone_is_a_422(path: str) -> None:
    """Comparing a naive cursor with aware event times used to raise a 500."""
    response = make_client().get(path, params={"before": "2026-10-10T00:00:00"})

    assert response.status_code == 422
    assert "timezone offset" in response.json()["detail"]


@pytest.mark.parametrize("path", PATHS)
def test_a_cursor_id_without_its_timestamp_is_a_422(path: str) -> None:
    """EventQuery's invariant used to escape as a 500."""
    response = make_client().get(path, params={"before_id": "req-00000001"})

    assert response.status_code == 422
    assert "before_id needs a before timestamp" in response.json()["detail"]


def test_a_complete_cursor_still_pages() -> None:
    """An offset-bearing cursor with its id keeps working."""
    response = make_client().get(
        "/requests",
        params={"before": "2026-10-10T00:00:00+00:00", "before_id": "req-00000001"},
    )

    assert response.status_code == 200
