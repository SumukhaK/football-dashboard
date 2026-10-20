"""Tests for the D7 deploy: scripts, container build and CI guards.

These read the files rather than run them. What a file-level test can pin is the
permission set of the custom Trace role, which roles the setup script hands out,
and the intent of the deploy flags; tests/test_deploy_behaviour.py runs the real
scripts against a recording gcloud to check the commands that would be issued.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app.config import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
SETUP = DEPLOY / "setup_service_account.sh"
DEPLOY_SCRIPT = DEPLOY / "deploy.sh"
ROLE_FILE = DEPLOY / "trace-reader-role.yaml"
SCRIPTS = (SETUP.name, DEPLOY_SCRIPT.name)

# The read-only roles the reader may hold, plus the custom Trace role that is
# defined by permission. roles/cloudtrace.user is deliberately absent: it also
# carries Trace task and scope mutations.
READ_ROLES = {
    "roles/logging.viewer",
    "roles/errorreporting.viewer",
    "projects/${GCP_PROJECT_ID}/roles/footballDashboardTraceReader",
}

# Trace mutations that must never appear in the role definition.
MUTATION_PERMISSIONS = (
    "cloudtrace.tasks.create",
    "cloudtrace.tasks.delete",
    "cloudtrace.traces.create",
    "cloudtrace.traces.update",
    "cloudtrace.traces.delete",
    "cloudtrace.traces.patch",
    "cloudtrace.traces.write",
    "telemetry.traces.write",
    "cloudtrace.scopes.create",
    "cloudtrace.scopes.update",
    "cloudtrace.scopes.delete",
)


def _read(path: Path) -> str:
    """The text of one committed file."""
    return path.read_text(encoding="utf-8")


def _joined(text: str) -> str:
    """A script with its line continuations joined, one statement per line."""
    return text.replace("\\\r\n", " ").replace("\\\n", " ")


def _granted_roles(text: str) -> set[str]:
    """Every role this script hands out with add-iam-policy-binding."""
    roles: set[str] = set()
    for statement in re.findall(r"gcloud [^\n]+", _joined(text)):
        if "add-iam-policy-binding" in statement:
            roles |= {
                found.strip("\"'") for found in re.findall(r"--role=(\S+)", statement)
            }
    return roles


def _role_permissions(text: str) -> list[str]:
    """The includedPermissions list of a custom role definition."""
    permissions: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("includedPermissions:"):
            inside = True
            continue
        if not inside:
            continue
        if stripped.startswith("- "):
            permissions.append(stripped[2:].strip())
        elif stripped and not stripped.startswith("#"):
            break
    return permissions


def test_the_custom_trace_role_grants_only_the_permission_the_reader_uses() -> None:
    """The console calls get_trace and nothing else on Cloud Trace."""
    assert _role_permissions(_read(ROLE_FILE)) == ["cloudtrace.traces.get"]


def test_the_custom_trace_role_grants_no_mutation_permission() -> None:
    """No Trace task, scope or span mutation may creep into the definition."""
    permissions = _role_permissions(_read(ROLE_FILE))

    assert [p for p in permissions if p in MUTATION_PERMISSIONS] == []


def test_setup_hands_out_only_read_roles() -> None:
    """Logging and errors by predefined role, Trace by the narrow custom role."""
    assert _granted_roles(_read(SETUP)) == READ_ROLES


def test_setup_no_longer_grants_the_broad_trace_role() -> None:
    """roles/cloudtrace.user must not be granted: it can mutate Trace config."""
    granted = _granted_roles(_read(SETUP))

    assert "roles/cloudtrace.user" not in granted


def test_setup_removes_the_broad_trace_role_it_granted_before() -> None:
    """Adding the custom role does not cancel the old binding, so remove it."""
    statements = re.findall(r"gcloud [^\n]+", _joined(_read(SETUP)))
    removals = [s for s in statements if "remove-iam-policy-binding" in s]

    assert len(removals) == 1
    assert "--role=roles/cloudtrace.user" in removals[0]


def test_setup_provisions_the_custom_role_from_the_committed_definition() -> None:
    """Created once, updated afterwards, always from trace-reader-role.yaml."""
    text = _read(SETUP)

    assert "iam roles describe footballDashboardTraceReader" in text
    assert "iam roles create footballDashboardTraceReader" in text
    assert "iam roles update footballDashboardTraceReader" in text
    assert "${role_file}" in text


def test_setup_is_safe_to_run_twice() -> None:
    """It checks for the account and the role before creating either."""
    text = _read(SETUP)

    assert "iam service-accounts describe" in text
    assert "iam service-accounts create" in text


def test_setup_gives_the_reader_no_write_or_broad_role() -> None:
    """roles/viewer, editor or owner would all break read-only."""
    text = _joined(_read(SETUP))
    granted = _granted_roles(text)

    assert [
        r for r in ("roles/viewer", "roles/editor", "roles/owner") if r in granted
    ] == []


def test_deploy_asks_for_both_privacy_controls() -> None:
    """allUsers off, and the independent invoker IAM check explicitly on."""
    text = _read(DEPLOY_SCRIPT)

    assert "--no-allow-unauthenticated" in text
    assert "--invoker-iam-check" in text
    assert "--no-invoker-iam-check" not in text


def test_deploy_promotes_the_revision_it_just_deployed() -> None:
    """A rollback pins traffic; a deploy names its verified revision explicitly."""
    text = _read(DEPLOY_SCRIPT)

    assert "run services update-traffic" in text
    assert "--to-revisions=" in text
    assert "--to-latest" not in text


def test_deploy_proves_the_service_is_not_public_before_reporting_success() -> None:
    """Both mechanisms are checked, not just the flag that was passed."""
    text = _read(DEPLOY_SCRIPT) + _read(DEPLOY / "lib.sh")

    assert "get-iam-policy" in text
    assert "allUsers" in text
    assert "run.googleapis.com/invoker-iam-disabled" in text


def test_deploy_keeps_the_service_scaling_to_zero() -> None:
    """No always-on instance."""
    assert "--min-instances 0" in _read(DEPLOY_SCRIPT)


def test_deploy_applies_the_guided_limits() -> None:
    """One worker, one instance, the cpu, memory, concurrency and timeout."""
    text = _read(DEPLOY_SCRIPT)

    for expected in ("--max-instances 1", "--cpu 1", "--memory 512Mi", "--timeout 60"):
        assert expected in text


def test_deploy_runs_as_the_read_only_reader() -> None:
    """The revision runs as football-dashboard-reader, not the default account."""
    text = _read(DEPLOY_SCRIPT)

    assert "--service-account" in text
    assert "football-dashboard-reader" in text


def test_both_scripts_fail_fast() -> None:
    """set -euo pipefail, so a failed step stops the script."""
    for name in (*SCRIPTS, "rollback.sh"):
        assert "set -euo pipefail" in _read(DEPLOY / name)


def test_lib_is_only_sourced_by_scripts_that_fail_fast() -> None:
    """Shared helpers never run on their own and inherit the caller's guards."""
    lib = _read(DEPLOY / "lib.sh")

    assert "set -euo pipefail" not in lib
    for name in ("deploy.sh", "rollback.sh"):
        text = _read(DEPLOY / name)
        assert 'source "${script_dir}/lib.sh"' in text


def test_no_credential_is_read_or_written() -> None:
    """No key file: the platform credentials the reader, not the repository."""
    for name in (*SCRIPTS, "rollback.sh", "lib.sh"):
        text = _read(DEPLOY / name)
        assert "--key-file" not in text
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in text


def test_the_real_environment_file_is_ignored_and_the_example_is_committed() -> None:
    """deploy/.env.deploy holds real ids; the example holds placeholders."""
    ignored = _read(REPO_ROOT / ".gitignore")
    example = _read(DEPLOY / ".env.deploy.example")

    assert "deploy/.env.deploy" in ignored
    assert "GCP_PROJECT_ID=" in example
    assert "your-project-id" in example
    assert "firm-tracer" not in example


def test_the_image_copies_only_the_app_and_the_contract() -> None:
    """No fixtures, tests or scripts in the runtime image."""
    dockerfile = _read(REPO_ROOT / "Dockerfile")

    assert "COPY app" in dockerfile
    assert "COPY contract" in dockerfile
    assert "COPY . " not in dockerfile
    for excluded in ("fixtures", "tests", "scripts"):
        assert f"COPY {excluded}" not in dockerfile


def test_the_image_installs_from_the_lock_file_as_a_non_root_user() -> None:
    """Reproducible install, and the container does not run as root."""
    dockerfile = _read(REPO_ROOT / "Dockerfile")

    assert "uv sync --frozen --no-dev" in dockerfile
    assert "USER " in dockerfile
    assert "PORT:-8080" in dockerfile


def test_the_image_installs_the_locked_runtime_without_dev_packages() -> None:
    """Runtime auth dependencies reach the production image, not the dev group.

    The packages themselves are added by the auth slices; what this slice pins is
    the mechanism: the image installs the project's runtime dependencies from the
    frozen lockfile with `--no-dev`, so whatever those slices add is carried into
    the production image, and a missing owner sign-in configuration still stops
    the revision from starting (tests/test_auth_startup.py).
    """
    dockerfile = _read(REPO_ROOT / "Dockerfile")
    project = tomllib.loads(_read(REPO_ROOT / "pyproject.toml"))["project"]

    assert "uv sync --frozen --no-dev" in dockerfile
    assert "COPY app" in dockerfile
    assert project["dependencies"]


def test_the_example_documents_the_transport_and_secret_versions() -> None:
    """An operator can see what app-auth needs without a secret being committed."""
    example = _read(DEPLOY / ".env.deploy.example")

    assert "DASHBOARD_TRANSPORT=private" in example
    assert "AUTH_PUBLIC_ORIGIN=https://" in example
    for name in (
        "GOOGLE_CLIENT_SECRET_VERSION",
        "SESSION_SIGNING_KEY_VERSION",
        "OAUTH_SIGNING_KEY_VERSION",
    ):
        assert f"{name}=" in example
    assert "GOCSPX-" not in example


def test_ci_builds_the_image_and_lints_the_shell_scripts() -> None:
    """A broken Dockerfile or shell script fails CI, not the first deploy."""
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "ci.yml")

    assert "docker build" in workflow
    assert "ludeeus/action-shellcheck@" in workflow
    assert "ludeeus/action-shellcheck@latest" not in workflow
