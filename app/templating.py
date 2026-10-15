"""Shared Jinja2 templates and their global template data."""

from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.routers import NAVIGATION

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["navigation"] = NAVIGATION
