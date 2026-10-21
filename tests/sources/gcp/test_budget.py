"""Tests for the shared finite read budget."""

from __future__ import annotations

import pytest

from app.domain.errors import SourceUnavailableError
from app.sources.gcp.budget import READ_BUDGET_SECONDS, ReadBudget


def test_budget_exhaustion_is_a_safe_source_error() -> None:
    """An exhausted budget raises the existing source error with no payload."""
    now = [100.0]
    budget = ReadBudget("Cloud Logging", lambda: now[0])

    assert budget.remaining() == READ_BUDGET_SECONDS
    now[0] += READ_BUDGET_SECONDS

    with pytest.raises(SourceUnavailableError) as raised:
        budget.check()

    assert raised.value.kind == "unavailable"
    assert (
        raised.value.detail == "Cloud Logging: read budget exhausted; try again later"
    )


def test_budget_timeout_is_capped_by_the_remaining_time() -> None:
    """A call may not outlive the remaining whole-read budget."""
    now = [100.0]
    budget = ReadBudget("Cloud Trace", lambda: now[0], seconds=5.0)

    now[0] += 3.0
    assert budget.timeout(2.0) == 2.0
    assert budget.timeout(5.0) == 2.0

    now[0] += 2.0
    with pytest.raises(SourceUnavailableError):
        budget.timeout(2.0)
