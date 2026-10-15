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


templates.env.filters["utc_time"] = utc_time
