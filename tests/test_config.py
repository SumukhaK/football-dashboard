"""Tests for configuration settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT, Config


def test_default_source_is_fixture() -> None:
    """Default source should be 'fixture'."""
    config = Config()
    assert config.source == "fixture"


def test_fixture_dir_resolves_against_repo_root() -> None:
    """A relative fixture_dir is resolved against the repo, not the cwd."""
    assert Config().fixture_dir == REPO_ROOT / "fixtures"


def test_absolute_fixture_dir_is_kept(tmp_path: Path) -> None:
    """An absolute fixture_dir is used as given."""
    assert Config(fixture_dir=tmp_path).fixture_dir == tmp_path


def test_gcp_defaults() -> None:
    """Page size and platform patterns have the documented defaults."""
    config = Config()
    assert config.gcp_page_size == 1000
    assert ("Memory limit of", "out_of_memory") in config.platform_patterns


def test_gcp_requires_project_id() -> None:
    """source='gcp' without gcp_project_id should fail validation."""
    with pytest.raises(ValidationError):
        Config(source="gcp")


def test_gcp_with_project_id() -> None:
    """source='gcp' with gcp_project_id should succeed."""
    config = Config(source="gcp", gcp_project_id="test-project")
    assert config.source == "gcp"
    assert config.gcp_project_id == "test-project"


def test_cache_ttl_in_valid_range() -> None:
    """cache_ttl_seconds should be between 0 and 600."""
    # Valid values
    Config(cache_ttl_seconds=0)
    Config(cache_ttl_seconds=300)
    Config(cache_ttl_seconds=600)


def test_default_window_in_valid_range() -> None:
    """default_window_hours should be between 1 and 720."""
    config = Config()
    assert 1 <= config.default_window_hours <= 720


def test_contract_version() -> None:
    """Config should have access to contract_version."""
    config = Config()
    assert config.contract_version == "1.0.0"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cache_ttl_seconds", -1),
        ("cache_ttl_seconds", 601),
        ("default_window_hours", 0),
        ("default_window_hours", 721),
        ("gcp_page_size", 0),
        ("gcp_page_size", 1001),
    ],
)
def test_out_of_range_settings_are_rejected(field: str, value: int) -> None:
    """Range-limited settings reject values outside their bounds."""
    with pytest.raises(ValidationError):
        Config.model_validate({field: value})
