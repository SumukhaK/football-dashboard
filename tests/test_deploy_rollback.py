"""Rollback stays behind the promotion boundary (testing-gaps C3).

A restore point has not been through promote.sh's checks, so rollback.sh closes
the public edge first and leaves it closed, whatever the target's environment
claims. Serving it publicly again is promote.sh's job, which refuses a revision
pinned to retired key versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deploy_promote_fakes import DIGEST_ARG, RECORD, candidate, write_record
from tests.test_deploy_behaviour import (
    AUTH_ABSENT_READ,
    AUTH_ENABLED,
    BASH,
    POLICY_PUBLIC,
    PUBLIC_UNTIL_REMOVED,
    REVISION,
    TRAFFIC_OK,
    Scripts,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="requires a working POSIX bash")


@pytest.mark.parametrize(
    "target", [AUTH_ABSENT_READ, AUTH_ENABLED], ids=["pre-auth", "google-mode-only"]
)
def test_rollback_closes_the_edge_first_and_keeps_it_closed(
    tmp_path: Path, target: str
) -> None:
    """Neither a pre-auth image nor an AUTH_MODE=google claim is served publicly."""
    scripts = Scripts(tmp_path, PUBLIC_UNTIL_REMOVED + target + TRAFFIC_OK)

    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    removal = next(c for c in calls if "remove-iam-policy-binding" in c)
    traffic = next(c for c in calls if "--to-revisions=" in c)
    assert calls.index(removal) < calls.index(traffic)
    assert [c for c in calls if "add-iam-policy-binding" in c] == []
    assert "Transport is private" in result.stdout
    assert "deploy/promote.sh" in result.stdout


def test_rollback_aborts_when_the_edge_does_not_close(tmp_path: Path) -> None:
    """A binding that is still there after removal stops the restore."""
    scripts = Scripts(tmp_path, POLICY_PUBLIC + AUTH_ENABLED + TRAFFIC_OK)

    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode != 0
    assert "allUsers" in result.stderr
    assert [c for c in scripts.calls() if "update-traffic" in c] == []


def test_rollback_never_reopens_even_when_app_auth_is_configured(
    tmp_path: Path,
) -> None:
    """DASHBOARD_TRANSPORT=app-auth is promote.sh's decision, not rollback's."""
    scripts = Scripts(
        tmp_path, PUBLIC_UNTIL_REMOVED + AUTH_ENABLED + TRAFFIC_OK, transport="app-auth"
    )

    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    assert [c for c in scripts.calls() if "add-iam-policy-binding" in c] == []


def test_a_restore_point_on_retired_key_versions_cannot_be_made_public(
    tmp_path: Path,
) -> None:
    """The public path refuses old key versions and points at a fresh deploy.

    The configuration names the current versions (3, 4 and 5); the restore
    point still binds session key version 1 and OAuth key version 2. Nothing
    re-enables those versions: the operator redeploys current code instead.
    """
    retired = candidate(
        secrets={
            "SESSION_SIGNING_KEY": ("session-signing-key", "1"),
            "OAUTH_SIGNING_KEY": ("oauth-signing-key", "2"),
        }
    )
    scripts = Scripts(tmp_path, retired + TRAFFIC_OK, transport="app-auth")
    write_record(tmp_path)

    result = scripts.run("promote.sh", REVISION, DIGEST_ARG, RECORD)

    assert result.returncode != 0
    assert "session-signing-key:1" in result.stderr
    assert "redeploy current code with deploy/deploy.sh" in result.stderr
    calls = scripts.calls()
    assert [c for c in calls if "update-traffic" in c] == []
    assert [c for c in calls if "add-iam-policy-binding" in c] == []
    assert [c for c in calls if "secrets" in c and "enable" in c] == []
