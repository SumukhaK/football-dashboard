"""Frozen view models for the source page.

Which telemetry source the console is reading, what that source can answer, and
- when it reads a local file - what the last read of that file did. They belong
to the domain: they describe what the page shows, with no knowledge of FastAPI.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import LocalReadStats


@dataclass(frozen=True)
class CapabilityRow:
    """One line of the source page's list of what the source can answer."""

    name: str
    available: bool


@dataclass(frozen=True)
class SourceStatusModel:
    """Everything the source page renders."""

    source: str
    capabilities: tuple[CapabilityRow, ...]
    stats: LocalReadStats | None
