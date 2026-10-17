"""Grades the component tiles for the overview page.

The overview service does the reading; this module turns those events into the
frozen ``ComponentTile`` models, so the grading rules (including the tile
lookback and the freshness thresholds) live in one place.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.config import Config
from app.domain.models import TelemetryEvent, TimeWindow
from app.domain.overview import ComponentTile, TileState
from app.services.events import by_event
from app.services.freshness import age_hours, newest_per_competition, state_for
from app.services.links import requests_link

LOAD_STATES: dict[str, TileState] = {
    "ok": TileState.OK,
    "degraded": TileState.DEGRADED,
    "failed": TileState.FAILED,
}


def component_tiles(
    events: list[TelemetryEvent],
    degraded: list[TelemetryEvent],
    window: TimeWindow,
    components: Sequence[str],
    settings: Config,
) -> tuple[ComponentTile, ...]:
    """One tile per component plus the refresh and freshness tiles.

    ``events`` are the load, refresh and freshness events read over the lookback
    window. ``degraded`` is read separately over the selected window only, which
    is the one place its count is used, so a flood of degradations cannot push a
    component's own load out of the read.
    """
    loads = by_event(events, "component.load")
    tiles = [component_tile(name, loads, degraded, window) for name in components]
    tiles.append(refresh_tile(by_event(events, "refresh.run")))
    tiles.append(freshness_tile(by_event(events, "data.freshness"), settings))
    return tuple(tiles)


def component_tile(
    name: str,
    loads: list[TelemetryEvent],
    degraded: list[TelemetryEvent],
    window: TimeWindow,
) -> ComponentTile:
    """The tile for one component, from its latest load and degradations."""
    mine = [event for event in loads if event.attributes.get("component") == name]
    count = sum(1 for event in degraded if event.attributes.get("component") == name)
    link = (
        requests_link(window, event="component.degraded", component=name)
        if count
        else None
    )
    if not mine:
        return _missing_load_tile(name, count, link)
    latest = max(mine, key=lambda event: event.timestamp)
    found = str(latest.attributes.get("status"))
    if found not in LOAD_STATES:
        return ComponentTile(
            name=name,
            state=TileState.FAILED,
            detail=f"unknown status {found!r}",
            since=latest.timestamp,
            degraded_count=count,
            link=link,
        )
    state = LOAD_STATES[found]
    if state is TileState.OK and count:
        state = TileState.DEGRADED
    reason = latest.attributes.get("reason")
    return ComponentTile(
        name=name,
        state=state,
        detail=str(reason) if reason else latest.message,
        since=latest.timestamp,
        degraded_count=count,
        link=link,
    )


def _missing_load_tile(name: str, count: int, link: str | None) -> ComponentTile:
    """A component with no load in the lookback: amber if it still degraded."""
    if count:
        return ComponentTile(
            name=name,
            state=TileState.DEGRADED,
            detail="no load in the window",
            since=None,
            degraded_count=count,
            link=link,
        )
    return ComponentTile(
        name=name,
        state=TileState.NO_DATA,
        detail="no load in the lookback",
        since=None,
    )


def refresh_tile(runs: list[TelemetryEvent]) -> ComponentTile:
    """The daily-refresh tile: red after two failures, amber after one."""
    if not runs:
        return ComponentTile(
            name="daily_refresh",
            state=TileState.NO_DATA,
            detail="no run in the lookback",
            since=None,
        )
    ordered = sorted(runs, key=lambda event: event.timestamp, reverse=True)
    last = ordered[0]
    error = last.attributes.get("error")
    return ComponentTile(
        name="daily_refresh",
        state=_refresh_state(ordered),
        detail=str(error) if error else "last run succeeded",
        since=last.timestamp,
    )


def _refresh_state(runs: list[TelemetryEvent]) -> TileState:
    """Grade the refresh tile from the newest runs (newest first)."""
    if runs[0].attributes.get("status") != "failed":
        return TileState.OK
    if len(runs) >= 2 and runs[1].attributes.get("status") == "failed":
        return TileState.FAILED
    return TileState.DEGRADED


def freshness_tile(events: list[TelemetryEvent], settings: Config) -> ComponentTile:
    """The freshness tile from the oldest league age, treating null as unknown."""
    if not events:
        return ComponentTile(
            name="data_freshness",
            state=TileState.NO_DATA,
            detail="no reading in the lookback",
            since=None,
        )
    latest = newest_per_competition(events)
    readings = [
        (age_hours(event), competition, event) for competition, event in latest.items()
    ]
    unknown = sorted(name for age, name, _ in readings if age is None)
    known = [(age, name, event) for age, name, event in readings if age is not None]
    worst = max(known, key=lambda item: item[0]) if known else None
    detail, since = _freshness_detail(unknown, worst, latest)
    return ComponentTile(
        name="data_freshness",
        state=state_for(worst[0] if worst else None, bool(unknown), settings),
        detail=detail,
        since=since,
    )


def _freshness_detail(
    unknown: list[str],
    worst: tuple[float, str, TelemetryEvent] | None,
    latest: dict[str, TelemetryEvent],
) -> tuple[str, datetime | None]:
    """The freshness tile's detail line and the moment it refers to."""
    if unknown:
        return f"no data for {', '.join(unknown)}", latest[unknown[0]].timestamp
    if worst is not None:
        return f"oldest {worst[0]:.0f}h ({worst[1]})", worst[2].timestamp
    return "no reading in the lookback", None
