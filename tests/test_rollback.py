"""Behavioural tests for rollback.sh, run against a recording gcloud.

Without a digest a rollback target is unverified, whatever its settings say,
so it is restored behind a closed edge. With a digest it must pass the same
checks as a promotion before the transport is left as it was.
"""

from __future__ import annotations

from pathlib import Path

from tests.deploy_harness import (
    AUTH_ABSENT_READ,
    AUTH_ENABLED,
    CANDIDATE_OK,
    DIGEST_VALUE,
    NEEDS_BASH,
    POLICY_PUBLIC,
    PUBLIC_UNTIL_REMOVED,
    RECORD,
    REVISION,
    REVISION_READ_FAILS,
    TAGS_PRESENT,
    Scripts,
    answer,
    index_of,
    secret_read,
)

pytestmark = NEEDS_BASH

REMOVAL_FAILS = (
    '  *"remove-iam-policy-binding"*) echo "fake: REMOVAL FAILED" >&2; exit 1 ;;\n'
)


def _removals(scripts: Scripts) -> list[str]:
    """The public bindings the script removed."""
    return [c for c in scripts.calls() if "remove-iam-policy-binding" in c]


def _served(scripts: Scripts) -> list[str]:
    """The traffic changes the script made."""
    return [c for c in scripts.calls() if "--to-revisions" in c or "--to-latest" in c]


def test_rollback_needs_an_explicit_revision(tmp_path: Path) -> None:
    """An unnamed rollback is a guess, so it is refused before any call."""
    scripts = Scripts(tmp_path, "")
    result = scripts.run("rollback.sh")

    assert result.returncode != 0
    assert "usage" in result.stderr
    assert scripts.calls() == []


def test_rollback_refuses_latest(tmp_path: Path) -> None:
    """`latest` is exactly the guess a rollback must not make."""
    scripts = Scripts(tmp_path, "")
    result = scripts.run("rollback.sh", "latest")

    assert result.returncode != 0
    assert "latest" in result.stderr
    assert scripts.calls() == []


def test_rollback_moves_traffic_to_the_named_revision(tmp_path: Path) -> None:
    """A private service is restored by explicit name with nothing to close."""
    scripts = Scripts(tmp_path, AUTH_ENABLED)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    served = _served(scripts)
    assert len(served) == 1
    assert served[0].endswith(f"--to-revisions={REVISION}=100")
    assert [c for c in scripts.calls() if "iam-policy-binding" in c] == []
    assert "Transport is private" in result.stdout


def test_rollback_closes_public_transport_before_restoring_pre_auth_code(
    tmp_path: Path,
) -> None:
    """A pre-auth image is never exposed while it is being restored."""
    scripts = Scripts(tmp_path, PUBLIC_UNTIL_REMOVED + AUTH_ABSENT_READ)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    removal = _removals(scripts)[0]
    assert "allUsers" in removal
    assert calls.index(removal) < index_of(calls, "update-traffic")
    assert "Transport is private" in result.stdout


def test_a_google_mode_setting_alone_does_not_keep_the_edge_open(
    tmp_path: Path,
) -> None:
    """AUTH_MODE=google is a setting, not a review: an unverified target goes private."""
    scripts = Scripts(tmp_path, PUBLIC_UNTIL_REMOVED + AUTH_ENABLED)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    assert calls.index(_removals(scripts)[0]) < index_of(calls, "update-traffic")
    assert [c for c in calls if "add-iam-policy-binding" in c] == []
    assert "is unverified (AUTH_MODE=google)" in result.stdout
    assert f"bash deploy/promote.sh {REVISION} <sha256:digest>" in result.stdout


def test_rollback_moves_no_traffic_when_the_edge_cannot_be_closed(
    tmp_path: Path,
) -> None:
    """If the public binding cannot be removed, old code is not restored."""
    scripts = Scripts(tmp_path, REMOVAL_FAILS + POLICY_PUBLIC + AUTH_ABSENT_READ)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode != 0
    assert "REMOVAL FAILED" in result.stderr
    assert _served(scripts) == []


def test_a_verified_rollback_keeps_the_transport_as_it_was(tmp_path: Path) -> None:
    """The reviewed image with current keys may be restored behind a public edge."""
    scripts = Scripts(tmp_path, POLICY_PUBLIC + CANDIDATE_OK)
    scripts.record(REVISION, RECORD)
    result = scripts.run("rollback.sh", REVISION, DIGEST_VALUE)

    assert result.returncode == 0, result.stderr
    assert len(_served(scripts)) == 1
    assert _removals(scripts) == []
    assert "transport was left as it was" in result.stdout


def test_a_verified_rollback_refuses_pre_auth_code(tmp_path: Path) -> None:
    """A digest does not make a pre-auth image safe to serve publicly."""
    scripts = Scripts(tmp_path, POLICY_PUBLIC + AUTH_ABSENT_READ + CANDIDATE_OK)
    scripts.record(REVISION, RECORD)
    result = scripts.run("rollback.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "AUTH_MODE=google" in result.stderr
    assert _served(scripts) == []


def test_a_target_pinned_to_retired_keys_is_redeployed_not_revived(
    tmp_path: Path,
) -> None:
    """An old revision's key versions are never re-enabled to restore it."""
    retired = answer(secret_read("SESSION_SIGNING_KEY", "key"), "2")
    scripts = Scripts(tmp_path, retired + POLICY_PUBLIC + CANDIDATE_OK)
    scripts.record(REVISION, RECORD)
    result = scripts.run("rollback.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "version 2" in result.stderr
    assert "redeploy that code with the current versions" in result.stderr
    calls = scripts.calls()
    assert _served(scripts) == []
    assert [
        c
        for c in calls
        if "versions enable" in c or "iam-policy" in c and "get" not in c
    ] == []


def test_a_verified_rollback_needs_the_record(tmp_path: Path) -> None:
    """Naming a digest without the recorded checks restores nothing."""
    scripts = Scripts(tmp_path, POLICY_PUBLIC + CANDIDATE_OK)
    result = scripts.run("rollback.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "no verification record" in result.stderr
    assert _served(scripts) == []


def test_rollback_aborts_before_traffic_when_the_target_cannot_be_read(
    tmp_path: Path,
) -> None:
    """An unreadable revision is not a safe restore point."""
    scripts = Scripts(tmp_path, REVISION_READ_FAILS)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode != 0
    assert "fake: revision read failed" in result.stderr
    assert _served(scripts) == []


def test_rollback_retires_tags_after_the_traffic_change(tmp_path: Path) -> None:
    """A tag would otherwise still reach a revision at 0% traffic."""
    scripts = Scripts(tmp_path, TAGS_PRESENT + AUTH_ENABLED)
    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    assert "--remove-tags=candidate" in " ".join(calls)
    assert index_of(calls, "--to-revisions") < index_of(calls, "remove-tags")
