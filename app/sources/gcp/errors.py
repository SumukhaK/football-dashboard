"""Mapping of Google client errors onto the domain's source error."""

from __future__ import annotations

from collections.abc import Callable

from google.api_core import exceptions as api_exceptions
from google.auth import exceptions as auth_exceptions

from app.domain.errors import SourceErrorKind, SourceUnavailableError

_KINDS: tuple[tuple[type[Exception], SourceErrorKind], ...] = (
    (api_exceptions.PermissionDenied, "permission_denied"),
    (api_exceptions.Unauthenticated, "permission_denied"),
    (auth_exceptions.DefaultCredentialsError, "permission_denied"),
    (api_exceptions.ResourceExhausted, "quota"),
    (api_exceptions.ServiceUnavailable, "unavailable"),
    (api_exceptions.DeadlineExceeded, "unavailable"),
)
_MAPPED = tuple(error_type for error_type, _ in _KINDS)


def kind_of(error: Exception) -> SourceErrorKind:
    """Return the source error kind for one of the mapped Google errors."""
    for error_type, kind in _KINDS:
        if isinstance(error, error_type):
            return kind
    raise TypeError(f"unmapped error type: {type(error).__name__}")


def guarded[T](service: str, call: Callable[[], T]) -> T:
    """Run a Google call, turning known client errors into SourceUnavailableError."""
    try:
        return call()
    except _MAPPED as exc:
        raise SourceUnavailableError(kind_of(exc), f"{service}: {exc}") from exc
