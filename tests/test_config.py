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


def test_default_window_must_be_a_picker_window() -> None:
    """default_window_hours must be one of the windows the picker offers."""
    with pytest.raises(ValidationError):
        Config(default_window_hours=12)


def test_tile_lookback_default() -> None:
    """The tile lookback defaults to a week."""
    assert Config().tile_lookback_hours == 168


def test_contract_version() -> None:
    """Config should have access to contract_version."""
    config = Config()
    assert config.contract_version == "1.1.0"


def test_version_and_revision_defaults() -> None:
    """The footer's version has a default and the revision is unset locally."""
    config = Config()
    assert config.app_version == "1.0.0"
    assert config.revision is None


def test_revision_is_read_from_the_cloud_run_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud Run's K_REVISION names the revision the console runs as."""
    monkeypatch.setenv("K_REVISION", "football-dashboard-00007-abc")
    assert Config().revision == "football-dashboard-00007-abc"


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


def test_invites_are_off_by_default() -> None:
    """The invite page is opt-in and writes to the staging collections."""
    config = Config()
    assert config.invites_enabled is False
    assert config.invite_collection_prefix == "staging_"
    assert config.invite_lifetime_days == 7


def test_crashlytics_defaults() -> None:
    """The crashes settings default to the staging app's export table."""
    config = Config()
    assert config.crashlytics_project_id is None
    assert config.crashlytics_dataset == "firebase_crashlytics"
    assert config.crashlytics_table == "com_footballintelligence_app_stg_ANDROID"
    assert config.crashlytics_location == "US"
    assert config.crashlytics_max_bytes_billed == 1_000_000_000


def test_crashes_enabled_on_fixture_or_with_a_firebase_project() -> None:
    """Sample data always has crashes; gcp needs crashlytics_project_id."""
    assert Config().crashes_enabled
    gcp = Config(source="gcp", gcp_project_id="demo-project")
    assert not gcp.crashes_enabled
    with_project = gcp.model_copy(update={"crashlytics_project_id": "proj-123"})
    assert with_project.crashes_enabled


def test_crashlytics_identifiers_are_checked() -> None:
    """Identifiers pasted into the SQL must be plain names."""
    with pytest.raises(ValidationError):
        Config(crashlytics_table="t`; DROP TABLE x")
    with pytest.raises(ValidationError):
        Config(crashlytics_project_id="Bad Project")
