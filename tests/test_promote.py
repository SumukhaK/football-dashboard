"""Behavioural tests for promote.sh, run against a recording gcloud.

promote.sh serves one named revision built from one named digest, only after
the operator's verification record for exactly those and a readback that the
revision runs this configuration and the current, enabled key versions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deploy_harness import (
    CANDIDATE_OK,
    DIGEST_VALUE,
    NEEDS_BASH,
    POLICY_PUBLIC,
    PUBLIC_AFTER_BINDING,
    RECORD,
    REVISION,
    RUN_POLICY_READ_FAILS,
    TAGS_PRESENT,
    TAGS_READ_FAILS,
    TRAFFIC_FAILS,
    TRAFFIC_OK,
    Scripts,
    answer,
    index_of,
    secret_read,
    setting_read,
)

pytestmark = NEEDS_BASH

SUCCESS = CANDIDATE_OK + TRAFFIC_OK


def _scripts(
    tmp_path: Path, cases: str, record: str | None = RECORD, **kw: str
) -> Scripts:
    """A deploy tree with the given answers and, by default, a full record."""
    scripts = Scripts(tmp_path, cases, **kw)
    if record is not None:
        scripts.record(REVISION, record)
    return scripts


def _opened(scripts: Scripts) -> list[str]:
    """The public bindings the script added."""
    return [c for c in scripts.calls() if "add-iam-policy-binding" in c]


def _served(scripts: Scripts) -> list[str]:
    """The traffic changes the script made."""
    return [c for c in scripts.calls() if "--to-revisions" in c or "--to-latest" in c]


def test_promote_serves_the_named_revision_and_stays_private(tmp_path: Path) -> None:
    """The default promotion moves traffic by name and opens nothing."""
    scripts = _scripts(tmp_path, TAGS_PRESENT + SUCCESS)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    served = _served(scripts)
    assert len(served) == 1
    assert "update-traffic football-dashboard " in served[0]
    assert served[0].endswith(f"--to-revisions={REVISION}=100")
    assert index_of(calls, "--to-revisions") < index_of(calls, "remove-tags")
    assert _opened(scripts) == []
    assert "Transport: private" in result.stdout
    assert f"Revision {REVISION} ({DIGEST_VALUE}) is serving" in result.stdout


def test_promote_opens_app_auth_only_after_serving_and_retiring_tags(
    tmp_path: Path,
) -> None:
    """The public edge is the last step, and only when it was asked for."""
    scripts = _scripts(
        tmp_path, PUBLIC_AFTER_BINDING + TAGS_PRESENT + SUCCESS, transport="app-auth"
    )
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    opened = _opened(scripts)
    assert len(opened) == 1
    assert "run services add-iam-policy-binding football-dashboard" in opened[0]
    assert "--member=allUsers --role=roles/run.invoker" in opened[0]
    assert index_of(calls, "--to-revisions") < index_of(calls, "remove-tags")
    assert index_of(calls, "remove-tags") < calls.index(opened[0])
    assert "Transport: app-auth" in result.stdout


@pytest.mark.parametrize(
    "args,message",
    [
        ((), "usage"),
        (("latest", DIGEST_VALUE), "latest"),
        ((REVISION,), "digest"),
        ((REVISION, "latest"), "digest"),
        ((REVISION, "sha256:"), "digest"),
        ((REVISION, "sha256:NOT-HEX"), "digest"),
    ],
)
def test_promote_needs_a_named_revision_and_its_digest(
    tmp_path: Path, args: tuple[str, ...], message: str
) -> None:
    """No guess is promoted, and nothing is read until both are named."""
    scripts = _scripts(tmp_path, SUCCESS)
    result = scripts.run("promote.sh", *args)

    assert result.returncode != 0
    assert message in result.stderr
    assert scripts.calls() == []


def test_promote_needs_the_operator_record_before_any_call(tmp_path: Path) -> None:
    """Without the recorded checks there is nothing to promote."""
    scripts = _scripts(tmp_path, SUCCESS, record=None)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert f"no verification record for {REVISION}" in result.stderr
    assert "Verify a candidate" in result.stderr
    assert scripts.calls() == []


def _with(record: str, key: str, value: str) -> str:
    """The record with one key's line set to value."""
    lines = record.splitlines()
    return "\n".join(f"{key}={value}" if l.startswith(f"{key}=") else l for l in lines)


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("DIGEST", "sha256:0bad", "records digest"),
        ("REVISION", "football-dashboard-older", "records revision"),
        ("OWNER_ALLOWED", "true", "is a flag"),
        ("NON_OWNER_DENIED", "Yes", "is a flag"),
        ("PRIVACY_CHECKED", "", "has no PRIVACY_CHECKED"),
    ],
)
def test_promote_refuses_a_record_that_is_not_evidence_for_this_revision(
    tmp_path: Path, key: str, value: str, message: str
) -> None:
    """A record for another build, a bare flag or a missing check does not count."""
    scripts = _scripts(tmp_path, SUCCESS, record=_with(RECORD, key, value))
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert message in result.stderr
    assert scripts.calls() == []


def test_the_record_is_read_as_data_and_never_run(tmp_path: Path) -> None:
    """A command written into the record is text, not something to execute."""
    planted = RECORD + "VERIFIED_BY=$(touch ../planted)\n"
    scripts = _scripts(tmp_path, SUCCESS, record=planted)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "planted").exists()
    assert not (tmp_path / "repo" / "planted").exists()


@pytest.mark.parametrize(
    "override,message",
    [
        (
            answer('"containers[0].image)"', "elsewhere/console@sha256:deadbeef"),
            "image=",
        ),
        (answer('"serviceAccountName"', "default-compute@example"), "service account="),
        (answer(setting_read("OWNER_EMAIL"), "someone@example.com"), "OWNER_EMAIL="),
        (answer(setting_read("AUTH_PUBLIC_ORIGIN"), "https://old.example"), "ORIGIN="),
        (answer(setting_read("AUTH_CALLBACK_URL"), "https://x/cb"), "CALLBACK_URL="),
        (answer(setting_read("SOURCE"), "fixture"), "SOURCE="),
        (answer(setting_read("API_SERVICE_NAME"), "other-api"), "API_SERVICE_NAME="),
        ('  *"revisions describe"*"AUTH_MODE"*) ;;\n', "AUTH_MODE=google"),
        (answer(secret_read("SESSION_SIGNING_KEY", "name"), "old-key"), "secret="),
        (answer(secret_read("OAUTH_SIGNING_KEY", "key"), "2"), "redeploy"),
        (answer('"secrets versions describe"', "DISABLED"), "not ENABLED"),
        (answer('"revisions describe"*"conditions"', "False"), "not ready"),
    ],
)
def test_promote_refuses_a_revision_that_does_not_match_the_configuration(
    tmp_path: Path, override: str, message: str
) -> None:
    """Every mismatch stops before traffic moves or the edge opens."""
    scripts = _scripts(
        tmp_path, override + PUBLIC_AFTER_BINDING + SUCCESS, transport="app-auth"
    )
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert message in result.stderr
    assert _served(scripts) == []
    assert _opened(scripts) == []


def test_promote_aborts_when_a_verification_read_fails(tmp_path: Path) -> None:
    """A failed read is not a matching value."""
    fails = '  *"secrets versions describe"*) echo "fake: secret read failed" >&2; exit 42 ;;\n'
    scripts = _scripts(tmp_path, fails + SUCCESS)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "fake: secret read failed" in result.stderr
    assert _served(scripts) == []


def test_promote_refuses_while_the_service_is_public(tmp_path: Path) -> None:
    """Traffic moves only while private; closing the edge is the operator's call."""
    scripts = _scripts(tmp_path, POLICY_PUBLIC + SUCCESS)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "is public" in result.stderr
    assert _served(scripts) == []
    assert [c for c in scripts.calls() if "remove-iam-policy-binding" in c] == []


def test_promote_aborts_when_the_policy_read_fails(tmp_path: Path) -> None:
    """An unreadable policy is not a private one."""
    scripts = _scripts(tmp_path, RUN_POLICY_READ_FAILS + SUCCESS)
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "fake: policy read failed" in result.stderr
    assert _served(scripts) == []


@pytest.mark.parametrize(
    "tags",
    [
        TAGS_READ_FAILS,
        '  *"remove-tags"*) exit 42 ;;\n' + TAGS_PRESENT,
        '  *"traffic[].tag"*) printf "%s\\n" "candidate" ;;\n',
    ],
    ids=["read-fails", "removal-fails", "tag-survives"],
)
def test_promote_never_opens_access_while_a_tag_may_remain(
    tmp_path: Path, tags: str
) -> None:
    """A tag reaches a revision at 0% traffic, so it must be gone and read back."""
    scripts = _scripts(
        tmp_path, tags + PUBLIC_AFTER_BINDING + SUCCESS, transport="app-auth"
    )
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert _opened(scripts) == []
    assert "Transport: app-auth" not in result.stdout


def test_promote_fails_loudly_when_traffic_cannot_be_moved(tmp_path: Path) -> None:
    """A refused traffic change is not a promotion, and nothing opens."""
    scripts = _scripts(
        tmp_path,
        TRAFFIC_FAILS + PUBLIC_AFTER_BINDING + CANDIDATE_OK,
        transport="app-auth",
    )
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert _opened(scripts) == []
    assert "is serving" not in result.stdout


def test_promote_fails_closed_when_the_public_binding_is_refused(
    tmp_path: Path,
) -> None:
    """A binding that was refused must abort, not look like a public launch."""
    refused = (
        '  *"run services add-iam-policy-binding"*) '
        "printf '%s\\n' \"fake: BINDING FAILED\" >&2; exit 1 ;;\n"
    )
    scripts = _scripts(tmp_path, refused + SUCCESS, transport="app-auth")
    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "BINDING FAILED" in result.stderr
    assert "Transport: app-auth" not in result.stdout
