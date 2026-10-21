"""Exact recorded API release identity and immutable selection semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Self

MAX_RELEASE_LENGTH = 64


@dataclass(frozen=True)
class ReleaseCatalogue:
    """Observed labels and explicit unknown/incomplete discovery metadata."""

    versions: tuple[str, ...]
    has_unknown: bool
    truncated: bool


def recorded_release(value: object) -> str | None:
    """Keep a usable label exactly; unusable or reserved values are unknown."""
    if (
        isinstance(value, str)
        and 1 <= len(value) <= MAX_RELEASE_LENGTH
        and value.strip()
        and value.isprintable()
        and value != "unknown"
    ):
        return value
    return None


@dataclass(frozen=True)
class ReleaseSelection:
    """A hashable all/exact/unknown choice; only exact carries a label."""

    kind: Literal["all", "exact", "unknown"] = "all"
    value: str | None = None

    def __post_init__(self) -> None:
        """Reject ambiguous or unusable selections at construction."""
        if self.kind not in ("all", "exact", "unknown"):
            raise ValueError("invalid release selection kind")
        if self.kind == "exact":
            if self.value is None or recorded_release(self.value) != self.value:
                raise ValueError("exact release needs a usable label")
        elif self.value is not None:
            raise ValueError("only exact release carries a label")

    @classmethod
    def from_query(cls, value: str | None) -> Self:
        """Parse an omitted selection, reserved unknown or exact label."""
        if value is None:
            return cls()
        if value == "unknown":
            return cls("unknown")
        return cls("exact", value)
