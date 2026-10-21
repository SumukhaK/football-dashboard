"""Build catalogue metadata from already validated, bounded source events."""

from app.domain.models import TelemetryEvent
from app.domain.releases import ReleaseCatalogue


def catalogue_from_events(
    events: list[TelemetryEvent], *, truncated: bool = False
) -> ReleaseCatalogue:
    """Keep exact observed labels and mark unknown separately from truncation."""
    values = {event.api_version for event in events}
    return ReleaseCatalogue(
        tuple(sorted(value for value in values if value is not None)),
        None in values,
        truncated,
    )
