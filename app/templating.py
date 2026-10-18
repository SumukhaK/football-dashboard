"""Shared Jinja2 templates, their globals and filters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.routers import NAVIGATION, NavItem, NavSection
from app.services.labels import window_span

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def visible_navigation(config: object) -> list[NavSection]:
    """The navigation sections this deployment offers, in order.

    An item may name a config flag in ``enabled_by`` and is then offered only
    while that flag is on; a section left with no items is dropped, so a
    switched-off page never leaves an empty heading behind.
    """
    sections: list[NavSection] = []
    for section in NAVIGATION:
        items = [item for item in section["items"] if _offered(item, config)]
        if items:
            sections.append({"name": section["name"], "items": items})
    return sections


def _offered(item: NavItem, config: object) -> bool:
    """Whether an item's page is switched on (an item without a flag always is)."""
    flag = item.get("enabled_by")
    return flag is None or bool(getattr(config, flag))


def utc_time(moment: datetime | None) -> str:
    """Format a moment as a short UTC stamp, for example '08 Oct 06:01 UTC'."""
    if moment is None:
        return ""
    return moment.astimezone(UTC).strftime("%d %b %H:%M UTC")


def utc_clock(moment: datetime | None) -> str:
    """Format a moment as a clock in UTC, for example '18:04 UTC'."""
    if moment is None:
        return ""
    return moment.astimezone(UTC).strftime("%H:%M UTC")


# The pill tone for each state a tile, a freshness row or a refresh run shows.
STATE_TONES: dict[str, str] = {
    "ok": "ok",
    "degraded": "warn",
    "failed": "fail",
    "no data": "neutral",
}


def state_tone(state: str) -> str:
    """The pill tone that colours a state; anything unrecognised stays neutral."""
    return STATE_TONES.get(str(state), "neutral")


def nav_path_matches(request_path: str, item_path: str) -> bool:
    """Whether a request path belongs to a navigation item.

    The console root matches only itself. Every other item also owns its detail
    pages, so a request detail keeps "Requests" marked as the current page.
    """
    if item_path == "/":
        return request_path == "/"
    return request_path == item_path or request_path.startswith(item_path + "/")


templates.env.filters["utc_time"] = utc_time
templates.env.filters["utc_clock"] = utc_clock
templates.env.filters["state_tone"] = state_tone
templates.env.globals["nav_path_matches"] = nav_path_matches
templates.env.globals["visible_navigation"] = visible_navigation
templates.env.globals["window_span"] = window_span
