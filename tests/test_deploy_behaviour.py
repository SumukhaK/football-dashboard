"""Behavioural tests for deploy.sh, run against a recording gcloud.

deploy.sh builds and deploys one unserved candidate and stops there: it never
moves traffic and never opens public access. Promotion is promote.sh.
"""

from __future__ import annotations

from pathlib import Path

from tests.deploy_harness import (
    AUTH_MODE_ABSENT,
    BINDING_ABSENT,
    BUILD_FAILS,
    BUILD_OK,
    CANDIDATE_OK,
    DEPLOY_FAILS,
    DEPLOY_OK,
    DIGEST,
    DIGEST_VALUE,
    INVOKER_DISABLED,
    NEEDS_BASH,
    POLICY_PUBLIC,
    PROJECT,
    REPO_ABSENT,
    REVISION,
    REVISION_NOT_READY,
    RUN_POLICY_READ_FAILS,
    Scripts,
    answer,
)

pytestmark = NEEDS_BASH

SUCCESS = REPO_ABSENT + CANDIDATE_OK + DIGEST + BUILD_OK + DEPLOY_OK
SERVICE_EXISTS = answer('"run services list"', "football-dashboard")
PROMOTE_HINT = f"bash deploy/promote.sh {REVISION} {DIGEST_VALUE}"


def _mutations(calls: list[str]) -> list[str]:
    """Calls that would serve a revision or open the service."""
    return [c for c in calls if "update-traffic" in c or "add-iam-policy-binding" in c]


def test_deploy_asks_for_both_privacy_controls(tmp_path: Path) -> None:
    """allUsers off, and the separate invoker IAM check explicitly on."""
    scripts = Scripts(tmp_path, SUCCESS)
    scripts.run("deploy.sh")

    deploy = [c for c in scripts.calls() if "run deploy" in c]
    assert len(deploy) == 1
    assert "--no-allow-unauthenticated" in deploy[0]
    assert "--invoker-iam-check" in deploy[0]
    assert "--no-invoker-iam-check" not in deploy[0]


def test_deploy_keeps_the_digest_and_the_reader_identity(tmp_path: Path) -> None:
    """The private identity and the pinned digest survive the extra steps."""
    scripts = Scripts(tmp_path, SUCCESS)
    scripts.run("deploy.sh")

    deploy = next(c for c in scripts.calls() if "run deploy" in c)
    assert f"console@{DIGEST_VALUE}" in deploy
    assert f"football-dashboard-reader@{PROJECT}.iam.gserviceaccount.com" in deploy


def test_deploy_updates_the_settings_it_owns_rather_than_replacing_them(
    tmp_path: Path,
) -> None:
    """Settings the script does not name must survive a later deploy.

    --set-env-vars replaces a service's whole environment, so a redeploy would
    silently drop anything added by hand, such as the crashed-app settings the
    crashes page needs. --update-env-vars merges the ones this script owns into
    what is already there and leaves the rest alone.
    """
    scripts = Scripts(tmp_path, SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    deploy = next(c for c in scripts.calls() if "run deploy" in c)
    assert "--set-env-vars" not in deploy
    assert "--update-env-vars" in deploy
    for setting in (
        "SOURCE=gcp",
        f"GCP_PROJECT_ID={PROJECT}",
        "API_SERVICE_NAME=example-api",
        "CACHE_TTL_SECONDS=60",
        # The owner sign-in settings this script owns are re-asserted on every
        # deploy, so a redeploy can never drop them and start without auth.
        "AUTH_MODE=google",
        "AUTH_PUBLIC_ORIGIN=https://console.example",
        "AUTH_CALLBACK_URL=https://console.example/auth/callback",
        "OWNER_EMAIL=owner@example.com",
        "INVITES_ENABLED=false",
    ):
        assert setting in deploy, setting
    assert "--update-secrets" in deploy
    for binding in (
        "GOOGLE_CLIENT_SECRET=google-client-secret:3",
        "SESSION_SIGNING_KEY=session-signing-key:4",
        "OAUTH_SIGNING_KEY=oauth-signing-key:5",
    ):
        assert binding in deploy, binding


def test_deploy_creates_a_candidate_with_no_traffic_behind_a_tag(
    tmp_path: Path,
) -> None:
    """The new revision is built, tagged and left unserved."""
    scripts = Scripts(tmp_path, SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    deploy = next(c for c in scripts.calls() if "run deploy" in c)
    assert "--no-traffic" in deploy
    assert "--tag candidate" in deploy
    assert "--no-allow-unauthenticated" in deploy


def test_creating_a_candidate_never_serves_it_or_opens_access(tmp_path: Path) -> None:
    """Even with app-auth configured, a deploy alone promotes and opens nothing."""
    scripts = Scripts(tmp_path, SERVICE_EXISTS + SUCCESS, transport="app-auth")
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    assert _mutations(scripts.calls()) == []
    assert [c for c in scripts.calls() if "remove-tags" in c] == []


def test_deploy_ends_with_the_candidate_and_the_separate_promotion(
    tmp_path: Path,
) -> None:
    """The operator gets the revision, digest, private check and promote command."""
    scripts = Scripts(tmp_path, SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    assert f"Candidate {REVISION} is deployed with no traffic." in result.stdout
    assert f"Image digest: {DIGEST_VALUE}" in result.stdout
    assert (
        "gcloud run services proxy football-dashboard --tag candidate" in result.stdout
    )
    assert f"deploy/verification/{REVISION}.env" in result.stdout
    assert PROMOTE_HINT in result.stdout
    assert "private (Cloud Run IAM" in result.stdout


def test_deploy_refuses_a_public_service_before_building(tmp_path: Path) -> None:
    """A candidate tag on a public service would be public, so nothing starts."""
    scripts = Scripts(tmp_path, SERVICE_EXISTS + POLICY_PUBLIC + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "is public" in result.stderr
    assert "remove-iam-policy-binding football-dashboard" in result.stderr
    calls = scripts.calls()
    assert [c for c in calls if "builds submit" in c or "run deploy" in c] == []
    assert [c for c in calls if "remove-iam-policy-binding" in c] == []


def test_deploy_refuses_a_service_without_the_invoker_check(tmp_path: Path) -> None:
    """A disabled invoker check is the other way to be public."""
    scripts = Scripts(tmp_path, SERVICE_EXISTS + INVOKER_DISABLED + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "invoker" in result.stderr.lower()
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_aborts_before_building_when_the_policy_read_fails(
    tmp_path: Path,
) -> None:
    """A failed read of an existing service is not "private"."""
    scripts = Scripts(tmp_path, SERVICE_EXISTS + RUN_POLICY_READ_FAILS + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "fake: policy read failed" in result.stderr
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_aborts_when_the_service_cannot_be_listed(tmp_path: Path) -> None:
    """Not knowing whether the service exists is not "it does not exist"."""
    list_fails = '  *"run services list"*) echo "fake: list failed" >&2; exit 42 ;;\n'
    scripts = Scripts(tmp_path, list_fails + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "fake: list failed" in result.stderr
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_refuses_an_unknown_transport_before_building(
    tmp_path: Path,
) -> None:
    """A typo must not fall back to public or to a half-configured deploy."""
    scripts = Scripts(tmp_path, SUCCESS, transport="public")
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "DASHBOARD_TRANSPORT" in result.stderr
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_refuses_incomplete_owner_sign_in_configuration(
    tmp_path: Path,
) -> None:
    """An empty owner address is a configuration error, not a wildcard owner."""
    scripts = Scripts(tmp_path, SUCCESS, env_extra="OWNER_EMAIL=\n")
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "OWNER_EMAIL" in result.stderr
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_refuses_a_secret_version_that_is_not_a_number(
    tmp_path: Path,
) -> None:
    """`latest` would make a deploy unrepeatable and a rollback ambiguous."""
    scripts = Scripts(
        tmp_path, SUCCESS, env_extra="SESSION_SIGNING_KEY_VERSION=latest\n"
    )
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "numeric secret version" in result.stderr
    assert [c for c in scripts.calls() if "builds submit" in c] == []


def test_deploy_reports_a_candidate_that_is_not_ready(tmp_path: Path) -> None:
    """A broken candidate is reported, with no promotion command."""
    scripts = Scripts(tmp_path, REVISION_NOT_READY + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "not ready" in result.stderr
    assert "promote.sh" not in result.stdout


def test_deploy_refuses_a_candidate_without_owner_sign_in(tmp_path: Path) -> None:
    """An image built without AUTH_MODE=google is never offered for promotion."""
    scripts = Scripts(tmp_path, AUTH_MODE_ABSENT + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "AUTH_MODE=google" in result.stderr
    assert "promote.sh" not in result.stdout


def test_deploy_refuses_a_candidate_without_its_secret_bindings(
    tmp_path: Path,
) -> None:
    """A revision missing a signing key or the client secret is not verifiable."""
    scripts = Scripts(tmp_path, BINDING_ABSENT + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "does not bind" in result.stderr
    assert "promote.sh" not in result.stdout


def test_deploy_refuses_a_candidate_running_another_image(tmp_path: Path) -> None:
    """The readback has to show this build's digest, not just any image."""
    other = answer('"containers[0].image)"', "elsewhere/console@sha256:0ther")
    scripts = Scripts(tmp_path, other + SUCCESS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "image=" in result.stderr
    assert "promote.sh" not in result.stdout


def test_deploy_issues_nothing_after_a_failed_build(tmp_path: Path) -> None:
    """A build that fails stops before the deployment."""
    scripts = Scripts(tmp_path, REPO_ABSENT + CANDIDATE_OK + DIGEST + BUILD_FAILS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert [c for c in scripts.calls() if "run deploy" in c] == []
    assert "promote.sh" not in result.stdout


def test_deploy_reports_a_failed_deployment(tmp_path: Path) -> None:
    """A failed deployment is not a candidate to promote."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + CANDIDATE_OK + DIGEST + BUILD_OK + DEPLOY_FAILS
    )
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert [c for c in scripts.calls() if "revisions describe" in c] == []
    assert "promote.sh" not in result.stdout


def test_deploy_refuses_to_report_success_when_the_invoker_check_is_off(
    tmp_path: Path,
) -> None:
    """The candidate's tag URL must be as private as the service."""
    scripts = Scripts(tmp_path, SUCCESS + INVOKER_DISABLED)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "invoker" in result.stderr.lower()
    assert "promote.sh" not in result.stdout


def test_deploy_refuses_to_report_success_when_all_users_is_bound(
    tmp_path: Path,
) -> None:
    """The other public-access mechanism is checked too."""
    scripts = Scripts(tmp_path, SUCCESS + POLICY_PUBLIC)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "allUsers" in result.stderr
    assert "promote.sh" not in result.stdout


def test_deploy_aborts_when_the_policy_read_fails(tmp_path: Path) -> None:
    """A failed read must not pass for "no allUsers binding"."""
    scripts = Scripts(tmp_path, SUCCESS + RUN_POLICY_READ_FAILS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "fake: policy read failed" in result.stderr
    assert "promote.sh" not in result.stdout
