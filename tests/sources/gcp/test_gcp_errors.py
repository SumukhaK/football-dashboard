"""Tests for mapping Google client errors to SourceUnavailableError."""

from __future__ import annotations

import pytest
from google.api_core import exceptions as api_exceptions
from google.auth import exceptions as auth_exceptions

from app.domain.errors import SourceUnavailableError
from app.sources.gcp.errors import guarded, kind_of


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (api_exceptions.PermissionDenied("no"), "permission_denied"),
        (api_exceptions.Unauthenticated("no"), "permission_denied"),
        (auth_exceptions.DefaultCredentialsError("no"), "permission_denied"),
        (api_exceptions.ResourceExhausted("slow down"), "quota"),
        (api_exceptions.ServiceUnavailable("down"), "unavailable"),
        (api_exceptions.DeadlineExceeded("late"), "unavailable"),
    ],
)
def test_known_errors_are_mapped(error: Exception, kind: str) -> None:
    """Each mapped Google error becomes a SourceUnavailableError of its kind."""

    def fail() -> None:
        raise error

    with pytest.raises(SourceUnavailableError) as raised:
        guarded("Cloud Logging", fail)
    assert raised.value.kind == kind
    assert raised.value.detail.startswith("Cloud Logging:")


def test_other_errors_pass_through() -> None:
    """Errors outside the mapping are not hidden."""

    def fail() -> None:
        raise api_exceptions.NotFound("gone")

    with pytest.raises(api_exceptions.NotFound):
        guarded("Cloud Trace", fail)


def test_kind_of_rejects_unmapped_errors() -> None:
    """Asking for the kind of an unmapped error is a programming error."""
    with pytest.raises(TypeError):
        kind_of(ValueError("x"))


def test_successful_call_returns_its_value() -> None:
    """A call that works returns its value unchanged."""
    assert guarded("Cloud Trace", lambda: 7) == 7
