"""Shared Jinja2 templates, their globals and filters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.routers import NAVIGATION

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["navigation"] = NAVIGATION


def utc_time(moment: datetime | None) -> str:
    """Format a moment as a short UTC stamp, for example '08 Oct 06:01 UTC'."""
    if moment is None:
        return ""
    return moment.astimezone(UTC).strftime("%d %b %H:%M UTC")


# The badge class for each state a tile or a freshness row can show.
STATE_CLASSES: dict[str, str] = {
    "ok": "status-healthy",
    "degraded": "status-warning",
    "failed": "status-error",
    "no data": "status-none",
}


def state_class(state: str) -> str:
    """Format a tile state as the badge class that colours it."""
    return STATE_CLASSES.get(str(state), "status-none")


templates.env.filters["utc_time"] = utc_time
templates.env.filters["state_class"] = state_class
