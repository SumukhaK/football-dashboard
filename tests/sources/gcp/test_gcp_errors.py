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


@pytest.mark.parametrize(
    "error",
    [api_exceptions.NotFound("gone"), RuntimeError("bug"), ValueError("invalid")],
)
def test_other_errors_pass_through(error: Exception) -> None:
    """Missing resources and unrelated programming errors are not hidden."""

    def fail() -> None:
        raise error

    with pytest.raises(type(error)) as raised:
        guarded("Cloud Trace", fail)
    assert raised.value is error


@pytest.mark.parametrize(
    ("cause", "kind"),
    [
        (api_exceptions.ServiceUnavailable("offline"), "unavailable"),
        (api_exceptions.DeadlineExceeded("late"), "unavailable"),
        (api_exceptions.PermissionDenied("private-payload"), "permission_denied"),
        (api_exceptions.Unauthenticated("credential"), "permission_denied"),
        (auth_exceptions.DefaultCredentialsError("credential"), "permission_denied"),
        (api_exceptions.ResourceExhausted("private-quota"), "quota"),
        (ConnectionError("transport"), "unavailable"),
        (TimeoutError("transport"), "unavailable"),
    ],
)
def test_exhausted_retries_are_mapped_without_private_details(
    cause: Exception, kind: str
) -> None:
    """Retry exhaustion preserves known kinds without disclosing SDK details."""
    error = api_exceptions.RetryError("deadline exhausted private-wrapper", cause)
    calls = 0

    def fail() -> None:
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(SourceUnavailableError) as raised:
        guarded("Cloud Logging", fail)
    assert raised.value.kind == kind
    assert raised.value.detail == "Cloud Logging: retries exhausted; try again later"
    assert raised.value.__cause__ is error
    assert calls == 1


def test_retry_wrapped_not_found_passes_to_the_reader() -> None:
    """Readers retain their own policy for an SDK-wrapped missing resource."""
    cause = api_exceptions.NotFound("gone")
    error = api_exceptions.RetryError("deadline exhausted", cause)

    def fail() -> None:
        raise error

    with pytest.raises(api_exceptions.NotFound) as raised:
        guarded("Cloud Trace", fail)
    assert raised.value is cause


def test_kind_of_rejects_unmapped_errors() -> None:
    """Asking for the kind of an unmapped error is a programming error."""
    with pytest.raises(TypeError):
        kind_of(ValueError("x"))


def test_successful_call_returns_its_value() -> None:
    """A call that works returns its value unchanged."""
    assert guarded("Cloud Trace", lambda: 7) == 7
