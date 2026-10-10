"""Errors raised by telemetry sources."""

from __future__ import annotations

from typing import Literal

SourceErrorKind = Literal[
    "permission_denied", "quota", "unavailable", "not_found", "invalid_data"
]


class SourceUnavailableError(Exception):
    """A telemetry source could not be read."""

    def __init__(self, kind: SourceErrorKind, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind: SourceErrorKind = kind
        self.detail = detail
