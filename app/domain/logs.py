"""The bounded retained log sample shown within Requests."""

from dataclasses import dataclass

from app.domain.requests import TimelineEntry


@dataclass(frozen=True)
class LogsPage:
    """One page of sanitized log rows, with a bounded continuation."""

    rows: tuple[TimelineEntry, ...]
    next_link: str | None
    truncated: bool
