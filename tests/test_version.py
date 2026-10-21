"""The console's version has one source: pyproject.toml."""

from __future__ import annotations

import tomllib

import app
from app.config import REPO_ROOT, Config
from tests.auth.console import console_client


def _pyproject_version() -> str:
    """The version the package is built and installed with."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def test_the_package_version_is_the_pyproject_version() -> None:
    """app.__version__ is read from the installed package, not typed again."""
    assert app.__version__ == _pyproject_version()


def test_the_configured_version_defaults_to_the_package_version() -> None:
    """Config.app_version follows the package unless deliberately overridden."""
    assert Config().app_version == _pyproject_version()


def test_the_sidebar_footer_shows_the_pyproject_version() -> None:
    """The footer a reader sees carries the same version."""
    body = console_client().get("/").text

    assert f"v{_pyproject_version()}" in body
