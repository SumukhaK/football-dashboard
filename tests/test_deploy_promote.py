"""Behavioural tests for deploy/promote.sh, run against a recording gcloud.

Promotion is the only step that serves a candidate or opens the public edge, so
every check it makes is here: the named revision and digest, the operator's
verification record, the candidate's settings and exact secret versions, the
private edge before and after, and tag retirement before any public binding.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.deploy_promote_fakes import (
    DIGEST_ARG,
    RECORD,
    candidate,
    write_record,
)
from tests.test_deploy_behaviour import (
    BASH,
    BINDING_ADD_FAILS,
    POLICY_PUBLIC,
    PUBLIC_AFTER_BINDING,
    REVISION,
    RUN_POLICY_READ_FAILS,
    TAGS_PRESENT,
    TAGS_READ_FAILS,
    TRAFFIC_FAILS,
    TRAFFIC_OK,
    Scripts,
)

pytestmark = pytest.mark.skipif(BASH is None, reason="requires a working POSIX bash")


def _promote(
    tmp_path: Path, cases: str, *, transport: str = "private", **record: str
) -> tuple[Scripts, subprocess.CompletedProcess[str]]:
    """Run promote.sh for REVISION with a record and the given fake answers."""
    scripts = Scripts(tmp_path, cases, transport=transport)
    write_record(tmp_path, **record)
    return scripts, scripts.run("promote.sh", REVISION, DIGEST_ARG, RECORD)


def _opened(scripts: Scripts) -> list[str]:
    """The public bindings promote.sh added."""
    return [c for c in scripts.calls() if "add-iam-policy-binding" in c]


def _moved(scripts: Scripts) -> list[str]:
    """The traffic moves promote.sh made."""
    return [c for c in scripts.calls() if "--to-revisions=" in c]


def test_promotes_the_named_verified_revision_while_private(tmp_path: Path) -> None:
    """The happy path pins traffic by name and keeps the edge private."""
    scripts, result = _promote(tmp_path, candidate() + TRAFFIC_OK)

    assert result.returncode == 0, result.stderr
    moved = _moved(scripts)
    assert len(moved) == 1
    assert f"--to-revisions={REVISION}=100" in moved[0]
    assert all("--to-latest" not in call for call in scripts.calls())
    assert _opened(scripts) == []
    assert "Transport: private" in result.stdout


def test_opens_app_auth_only_after_promotion_and_tag_retirement(
    tmp_path: Path,
) -> None:
    """app-auth adds one service binding, after traffic and tags are settled."""
    scripts, result = _promote(
        tmp_path,
        PUBLIC_AFTER_BINDING + TAGS_PRESENT + candidate() + TRAFFIC_OK,
        transport="app-auth",
    )

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    (opening,) = _opened(scripts)
    assert "allUsers" in opening and "roles/run.invoker" in opening
    assert "projects add-iam-policy-binding" not in opening
    removal = next(c for c in calls if "remove-tags" in c)
    assert "--remove-tags=candidate" in removal
    assert calls.index(_moved(scripts)[0]) < calls.index(removal)
    assert calls.index(removal) < calls.index(opening)
    assert "Transport: app-auth" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        (),
        (REVISION,),
        (REVISION, DIGEST_ARG),
        ("latest", DIGEST_ARG, RECORD),
        (REVISION, "latest", RECORD),
        (REVISION, "deadbeef", RECORD),
        (REVISION, "sha256:", RECORD),
    ],
)
def test_refuses_a_missing_or_guessed_identity_before_any_call(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    """The revision and its immutable digest are named, never latest."""
    scripts = Scripts(tmp_path, candidate() + TRAFFIC_OK)
    write_record(tmp_path)

    result = scripts.run("promote.sh", *args)

    assert result.returncode != 0
    assert scripts.calls() == []


@pytest.mark.parametrize(
    "record",
    [
        {"revision": "football-dashboard-other"},
        {"digest": "sha256:0ther"},
        {"owner_allowed": ""},
        {"non_owner_denied": "true"},
        {"privacy_checks": "OK"},
    ],
)
def test_refuses_a_record_that_is_not_evidence_for_this_candidate(
    tmp_path: Path, record: dict[str, str]
) -> None:
    """A record for another build, or a bare flag, is not the D9 checks."""
    scripts, result = _promote(tmp_path, candidate() + TRAFFIC_OK, **record)

    assert result.returncode != 0
    assert "verification record" in result.stderr
    assert scripts.calls() == []


def test_refuses_a_missing_record(tmp_path: Path) -> None:
    """No record file means no promotion."""
    scripts = Scripts(tmp_path, candidate() + TRAFFIC_OK)

    result = scripts.run("promote.sh", REVISION, DIGEST_ARG, "missing.txt")

    assert result.returncode != 0
    assert "not found" in result.stderr
    assert scripts.calls() == []


@pytest.mark.parametrize(
    "fields,message",
    [
        ({"image": "elsewhere/console@sha256:deadbeef"}, "runs"),
        ({"image": ""}, "unreadable"),
        ({"ready": "False"}, "not ready"),
        ({"env": {"OWNER_EMAIL": "someone@example.com"}}, "OWNER_EMAIL"),
        ({"env": {"AUTH_PUBLIC_ORIGIN": "https://other.example"}}, "ORIGIN"),
        ({"env": {"AUTH_CALLBACK_URL": "https://x.example/cb"}}, "CALLBACK"),
        ({"env": {"API_SERVICE_NAME": "other-api"}}, "API_SERVICE_NAME"),
        ({"env": {"SOURCE": "fixture"}}, "SOURCE"),
        ({"env": {"AUTH_MODE": ""}}, "AUTH_MODE"),
        ({"secrets": {"SESSION_SIGNING_KEY": ("session-signing-key", "2")}}, ":2"),
        ({"secrets": {"OAUTH_SIGNING_KEY": ("another-key", "5")}}, "another-key"),
    ],
)
def test_a_candidate_that_differs_from_the_config_is_never_served(
    tmp_path: Path, fields: dict[str, Any], message: str
) -> None:
    """Settings, readiness, digest and exact secret versions all have to match."""
    scripts, result = _promote(
        tmp_path,
        PUBLIC_AFTER_BINDING + candidate(**fields) + TRAFFIC_OK,
        transport="app-auth",
    )

    assert result.returncode != 0
    assert message in result.stderr
    assert _moved(scripts) == []
    assert _opened(scripts) == []


def test_a_public_service_is_refused_with_instructions(tmp_path: Path) -> None:
    """Promotion happens while private; the fix is printed, not applied."""
    scripts, result = _promote(tmp_path, POLICY_PUBLIC + candidate() + TRAFFIC_OK)

    assert result.returncode != 0
    assert "remove-iam-policy-binding" in result.stderr
    assert _moved(scripts) == []
    assert [c for c in scripts.calls() if "iam-policy-binding" in c] == []


@pytest.mark.parametrize(
    "failure",
    [RUN_POLICY_READ_FAILS, TRAFFIC_FAILS, TAGS_READ_FAILS, BINDING_ADD_FAILS],
)
def test_any_failed_read_or_write_stops_public_opening(
    tmp_path: Path, failure: str
) -> None:
    """A failed policy read, traffic move, tag read or binding never looks public."""
    scripts, result = _promote(
        tmp_path,
        failure + PUBLIC_AFTER_BINDING + candidate() + TRAFFIC_OK,
        transport="app-auth",
    )

    assert result.returncode != 0
    assert "Transport: app-auth" not in result.stdout
    if failure is not BINDING_ADD_FAILS:
        assert _opened(scripts) == []


def test_tag_removal_failure_does_not_open_transport(tmp_path: Path) -> None:
    """A tag that could not be removed is still an old reachable URL."""
    scripts, result = _promote(
        tmp_path,
        '  *"remove-tags"*) exit 42 ;;\n'
        + TAGS_PRESENT
        + PUBLIC_AFTER_BINDING
        + candidate()
        + TRAFFIC_OK,
        transport="app-auth",
    )

    assert result.returncode != 0
    assert _opened(scripts) == []


def test_failed_tag_readback_never_opens_public_transport(tmp_path: Path) -> None:
    """A failed read after removal is not proof that old tag URLs are gone."""
    readback_fails = (
        '  *"traffic[].tag"*)\n'
        '    if grep -q "remove-tags" "${FAKE_GCLOUD_LOG}"; then\n'
        '      printf "%s\\n" "fake: tag readback failed" >&2; exit 42\n'
        '    else printf "%s\\n" "candidate"; fi ;;\n'
    )
    scripts, result = _promote(
        tmp_path,
        readback_fails + PUBLIC_AFTER_BINDING + candidate() + TRAFFIC_OK,
        transport="app-auth",
    )

    assert result.returncode != 0
    assert "fake: tag readback failed" in result.stderr
    assert _opened(scripts) == []


def test_multiple_sdk_tags_are_removed_as_individual_names(tmp_path: Path) -> None:
    """SDK value lists use semicolons unless a delimiter is requested."""
    multiple_tags = (
        '  *"traffic[].tag"*)\n'
        '    if grep -q "remove-tags" "${FAKE_GCLOUD_LOG}"; then :\n'
        '    elif [[ "$*" == *"delimiter="* ]]; then\n'
        '      printf "%s\\n" candidate old\n'
        '    else printf "%s\\n" "candidate;old"; fi ;;\n'
        '  *"remove-tags"*)\n'
        '    [[ "$*" == *"--remove-tags=candidate,old"* ]] || exit 42 ;;\n'
    )
    scripts, result = _promote(tmp_path, multiple_tags + candidate() + TRAFFIC_OK)

    assert result.returncode == 0, result.stderr
    assert any("--remove-tags=candidate,old" in call for call in scripts.calls())
