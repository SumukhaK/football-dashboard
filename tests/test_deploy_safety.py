"""Regression checks for real SDK readbacks and fail-closed deployment reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.deploy_harness import (
    AUTH_ABSENT_READ,
    AUTH_ENABLED,
    BUILD_ID,
    BUILD_OK,
    CANDIDATE_OK,
    DEPLOY_OK,
    DIGEST,
    DIGEST_VALUE,
    NEEDS_BASH,
    PUBLIC_AFTER_BINDING,
    RECORD,
    REVISION,
    TAGS_PRESENT,
    TRAFFIC_OK,
    Scripts,
)

pytestmark = NEEDS_BASH

SUCCESS = CANDIDATE_OK + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
PROMOTE_HINT = f"bash deploy/promote.sh {REVISION} {DIGEST_VALUE}"


def _promotion(tmp_path: Path, cases: str, transport: str = "private") -> Scripts:
    """A tree ready for promote.sh: the given answers and a full record."""
    scripts = Scripts(tmp_path, cases, transport=transport)
    scripts.record(REVISION, RECORD)
    return scripts


INVOKER_READ_FAILS = (
    '  *"invoker-iam-disabled"*) '
    'printf "%s\\n" "fake: invoker read failed" >&2; exit 42 ;;\n'
)


def test_candidate_reads_use_supported_sdk_projections(tmp_path: Path) -> None:
    """JMESPath array predicates return empty with the real SDK formatter."""
    scripts = Scripts(tmp_path, '  *"[?"*) ;;\n' + SUCCESS)

    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    assert f"Candidate {REVISION} is deployed" in result.stdout


@pytest.mark.parametrize("transport", ["private", "app-auth"])
def test_deploy_aborts_when_the_invoker_read_fails(
    tmp_path: Path, transport: str
) -> None:
    """An unreadable security control must not become a successful deploy."""
    scripts = Scripts(
        tmp_path,
        INVOKER_READ_FAILS + PUBLIC_AFTER_BINDING + SUCCESS,
        transport=transport,
    )

    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "fake: invoker read failed" in result.stderr
    assert "Transport:" not in result.stdout
    assert not any("add-iam-policy-binding" in call for call in scripts.calls())


def test_rollback_aborts_before_traffic_when_the_invoker_read_fails(
    tmp_path: Path,
) -> None:
    """A failed read cannot authorize rollback on an unknown public edge."""
    scripts = Scripts(tmp_path, INVOKER_READ_FAILS + AUTH_ENABLED)

    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode != 0
    assert not any("update-traffic" in call for call in scripts.calls())


def test_failed_tag_readback_never_opens_public_transport(tmp_path: Path) -> None:
    """A failed read after removal is not proof that old tag URLs are gone."""
    tag_readback_fails = (
        '  *"traffic[].tag"*)\n'
        '    if grep -q "remove-tags" "${FAKE_GCLOUD_LOG}"; then\n'
        '      printf "%s\\n" "fake: tag readback failed" >&2; exit 42\n'
        '    else printf "%s\\n" "candidate"; fi ;;\n'
    )
    scripts = _promotion(
        tmp_path, tag_readback_fails + PUBLIC_AFTER_BINDING + SUCCESS, "app-auth"
    )

    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert "fake: tag readback failed" in result.stderr
    assert not any("add-iam-policy-binding" in call for call in scripts.calls())


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
    scripts = _promotion(tmp_path, multiple_tags + SUCCESS)

    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode == 0, result.stderr
    assert any("--remove-tags=candidate,old" in call for call in scripts.calls())


def test_deploy_uses_its_own_result_not_a_later_service_revision(
    tmp_path: Path,
) -> None:
    """Another deploy changing latestCreatedRevisionName cannot replace ours."""
    concurrent_revision = (
        f'  *"run deploy"*) printf "%s\\n" "{REVISION}" ;;\n'
        '  *"latestCreatedRevisionName"*) '
        'printf "%s\\n" "football-dashboard-other-deploy" ;;\n'
    )
    scripts = Scripts(tmp_path, concurrent_revision + SUCCESS)

    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    assert PROMOTE_HINT in result.stdout
    reads = [call for call in scripts.calls() if "run revisions describe" in call]
    assert reads and all(f"describe {REVISION} " in call for call in reads)


@pytest.mark.parametrize(
    "field,value", [("secretKeyRef", "bound-secret"), ("AUTH_MODE", "google")]
)
def test_verification_read_failure_with_partial_output_still_aborts(
    tmp_path: Path, field: str, value: str
) -> None:
    """A failed command is not safe just because stdout contains a value."""
    partial_failure = (
        f'  *"revisions describe"*"{field}"*) '
        f'printf "%s\\n" "{value}"; exit 42 ;;\n'
    )
    scripts = Scripts(tmp_path, partial_failure + SUCCESS)

    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "promote.sh" not in result.stdout


def test_deploy_uses_its_own_build_digest_not_a_moving_image_tag(
    tmp_path: Path,
) -> None:
    """A concurrent push of latest cannot substitute another build's image."""
    concurrent_image = (
        '  *"builds submit"*)\n'
        '    if [[ "$*" != *"--suppress-logs"* ]]; then\n'
        '      printf "%s\\n" "streamed build output"\n'
        "    fi\n"
        f'    printf "%s\\t%s\\n" "{BUILD_ID}" "sha256:deadbeef" ;;\n'
        '  *"artifacts docker images describe"*) '
        'printf "%s\\n" "sha256:other-build" ;;\n'
    )
    scripts = Scripts(tmp_path, concurrent_image + SUCCESS)

    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    deployed = next(call for call in scripts.calls() if "run deploy" in call)
    assert "console@sha256:deadbeef" in deployed


def test_tag_removal_failure_does_not_open_transport(tmp_path: Path) -> None:
    """A failed mutation stops the script before its public binding."""
    scripts = _promotion(
        tmp_path,
        '  *"remove-tags"*) exit 42 ;;\n'
        + TAGS_PRESENT
        + PUBLIC_AFTER_BINDING
        + SUCCESS,
        "app-auth",
    )

    result = scripts.run("promote.sh", REVISION, DIGEST_VALUE)

    assert result.returncode != 0
    assert not any("add-iam-policy-binding" in call for call in scripts.calls())


@pytest.mark.parametrize("build_result", ["", BUILD_ID, "sha256:deadbeef"])
def test_incomplete_build_results_never_move_traffic(
    tmp_path: Path, build_result: str
) -> None:
    """Both the build id and digest are required to name our candidate."""
    scripts = Scripts(
        tmp_path,
        f'  *"builds submit"*) printf "%s\\n" "{build_result}" ;;\n' + SUCCESS,
    )

    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert not any("run deploy" in call for call in scripts.calls())


def test_rollback_aborts_on_the_first_failed_policy_read(tmp_path: Path) -> None:
    """A transient failed policy read must not be treated as an empty policy."""
    first_read_fails = (
        '  *"run services get-iam-policy"*)\n'
        '    if [ "$(grep -c get-iam-policy "${FAKE_GCLOUD_LOG}")" -eq 1 ]; then\n'
        '      printf "%s\\n" "fake: policy read failed" >&2; exit 42\n'
        "    fi ;;\n"
    )
    scripts = Scripts(tmp_path, first_read_fails + AUTH_ABSENT_READ)

    result = scripts.run("rollback.sh", REVISION)

    assert result.returncode != 0
    assert "fake: policy read failed" in result.stderr
    assert not any("update-traffic" in call for call in scripts.calls())


def test_candidate_identity_survives_a_concurrent_sdk_deploy_result(
    tmp_path: Path,
) -> None:
    """Even a service result changed during SDK polling cannot rename ours."""
    concurrent_result = (
        f'  *"builds submit"*) printf "%s\\t%s\\n" "{BUILD_ID}" '
        '"sha256:deadbeef" ;;\n'
        '  *"run deploy"*) printf "%s\\n" "football-dashboard-other" ;;\n'
    )
    scripts = Scripts(tmp_path, concurrent_result + SUCCESS)

    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    deploy = next(call for call in calls if "run deploy" in call)
    assert f"--revision-suffix {BUILD_ID}" in deploy
    assert PROMOTE_HINT in result.stdout
    reads = [call for call in calls if "run revisions describe" in call]
    assert reads and all(f"describe {REVISION} " in call for call in reads)
