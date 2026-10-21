"""Behavioural tests for setup_service_account.sh, run against a recording gcloud."""

from __future__ import annotations

from pathlib import Path

from tests.deploy_harness import (
    BINDING_FAILS,
    CUSTOM_ROLE,
    NEEDS_BASH,
    OLD_BINDING,
    PROJECT_POLICY_READ_FAILS,
    ROLE_ABSENT,
    SA_ABSENT,
    Scripts,
    index_of,
)

pytestmark = NEEDS_BASH


def test_setup_binds_the_read_roles_and_removes_nothing_when_the_project_is_clean(
    tmp_path: Path,
) -> None:
    """A first run creates the account, defines the role and binds three roles."""
    scripts = Scripts(tmp_path, SA_ABSENT + ROLE_ABSENT)
    result = scripts.run("setup_service_account.sh")

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    assert "iam service-accounts create football-dashboard-reader" in " ".join(calls)
    assert "iam roles create footballDashboardTraceReader" in " ".join(calls)
    bound = [c for c in calls if "add-iam-policy-binding" in c]
    assert len(bound) == 3
    assert "roles/logging.viewer" in bound[0]
    assert "roles/errorreporting.viewer" in bound[1]
    assert CUSTOM_ROLE in bound[2]
    assert [c for c in calls if "remove-iam-policy-binding" in c] == []


def test_setup_updates_the_role_and_revokes_the_old_broad_role_on_a_repeat_run(
    tmp_path: Path,
) -> None:
    """The second run is idempotent and migrates away from roles/cloudtrace.user."""
    scripts = Scripts(tmp_path, OLD_BINDING)
    result = scripts.run("setup_service_account.sh")

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    assert [c for c in calls if "iam service-accounts create" in c] == []
    assert [c for c in calls if "iam roles create" in c] == []
    assert "iam roles update footballDashboardTraceReader" in " ".join(calls)
    removals = [c for c in calls if "remove-iam-policy-binding" in c]
    assert len(removals) == 1
    assert "roles/cloudtrace.user" in removals[0]


def test_setup_binds_the_custom_role_only_after_the_role_exists(tmp_path: Path) -> None:
    """Binding before the role exists would fail on a fresh project."""
    scripts = Scripts(tmp_path, SA_ABSENT + ROLE_ABSENT)
    scripts.run("setup_service_account.sh")

    calls = scripts.calls()
    assert index_of(calls, "iam roles create") < index_of(calls, CUSTOM_ROLE)


def test_setup_stops_at_the_first_failed_grant(tmp_path: Path) -> None:
    """set -e and pipefail mean a failed binding aborts the script."""
    scripts = Scripts(tmp_path, SA_ABSENT + ROLE_ABSENT + BINDING_FAILS)
    result = scripts.run("setup_service_account.sh")

    assert result.returncode != 0
    assert len([c for c in scripts.calls() if "add-iam-policy-binding" in c]) == 1


def test_setup_aborts_when_the_policy_read_fails(tmp_path: Path) -> None:
    """A policy read that fails must not look like "the broad role is not bound"."""
    scripts = Scripts(tmp_path, PROJECT_POLICY_READ_FAILS)
    result = scripts.run("setup_service_account.sh")

    assert "fake: project policy read failed" in result.stderr
    assert result.returncode != 0
    assert "Granted logging.viewer" not in result.stdout
