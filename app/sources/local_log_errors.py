"""Stable source-error mapping for local log filesystem failures."""

from pathlib import Path

from app.domain.errors import SourceUnavailableError


def not_found(path: Path) -> SourceUnavailableError:
    """The error a missing log file raises, on the stat and on the read."""
    return SourceUnavailableError("not_found", f"{path} not found")


def read_error(path: Path, exc: OSError) -> SourceUnavailableError:
    """The error a file that cannot be read raises, by what went wrong."""
    if isinstance(exc, PermissionError):
        return SourceUnavailableError("permission_denied", f"{path} permission denied")
    reason = exc.strerror or exc.__class__.__name__
    return SourceUnavailableError("unavailable", f"{path} cannot be read: {reason}")
