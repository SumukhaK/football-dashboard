"""Tests for the D7 deploy: scripts, container build and CI guards.

These read the files rather than run them: the scripts talk to Google Cloud, so
what a test can pin is the exact set of roles, the privacy flags, and that no
credential ever lands in the repository.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
SCRIPTS = ("setup_service_account.sh", "deploy.sh")
READ_ROLES = (
    "roles/logging.viewer",
    "roles/cloudtrace.user",
    "roles/errorreporting.viewer",
)
FORBIDDEN_ROLES = (
    "roles/viewer",
    "roles/editor",
    "roles/owner",
    "roles/logging.logWriter",
)


def _read(path: Path) -> str:
    """The text of one committed file."""
    return path.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """A script without its comment lines, so prose cannot trip a guard."""
    lines = text.splitlines()
    return "\n".join(line for line in lines if not line.strip().startswith("#"))


def test_setup_grants_only_the_three_read_roles() -> None:
    """The reader gets exactly logging, trace and error read access."""
    roles = set(re.findall(r"--role=([\w./-]+)", _read(DEPLOY / SCRIPTS[0])))

    assert roles == set(READ_ROLES)


def test_setup_grants_no_write_or_broad_role() -> None:
    """roles/viewer, editor, owner or a write role would break read-only."""
    text = _code(_read(DEPLOY / SCRIPTS[0]))

    assert [role for role in FORBIDDEN_ROLES if role in text] == []


def test_setup_is_safe_to_run_twice() -> None:
    """It checks for the account before creating it."""
    text = _read(DEPLOY / SCRIPTS[0])

    assert "describe" in text
    assert "create" in text


def test_deploy_keeps_the_service_private_and_scales_to_zero() -> None:
    """No public access, and no always-on instance."""
    text = _read(DEPLOY / SCRIPTS[1])
    without_the_private_flag = text.replace("--no-allow-unauthenticated", "")

    assert "--no-allow-unauthenticated" in text
    assert "--allow-unauthenticated" not in without_the_private_flag
    assert "--min-instances 0" in text


def test_deploy_runs_as_the_read_only_reader() -> None:
    """The revision runs as football-dashboard-reader, not the default account."""
    text = _read(DEPLOY / SCRIPTS[1])

    assert "--service-account" in text
    assert "football-dashboard-reader" in text


def test_deploy_applies_the_guided_limits() -> None:
    """One worker, one instance, the cpu, memory, concurrency and timeout."""
    text = _read(DEPLOY / SCRIPTS[1])

    for expected in ("--max-instances 1", "--cpu 1", "--memory 512Mi", "--timeout 60"):
        assert expected in text


def test_both_scripts_fail_fast() -> None:
    """set -euo pipefail, so a failed step stops the script."""
    for name in SCRIPTS:
        assert "set -euo pipefail" in _read(DEPLOY / name)


def test_no_credential_is_read_or_written() -> None:
    """No key file: the platform credentials the reader, not the repository."""
    for name in SCRIPTS:
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


def test_ci_builds_the_image_and_lints_the_shell_scripts() -> None:
    """A broken Dockerfile or shell script fails CI, not the first deploy."""
    workflow = _read(REPO_ROOT / ".github" / "workflows" / "ci.yml")

    assert "docker build" in workflow
    assert "ludeeus/action-shellcheck@" in workflow
    assert "ludeeus/action-shellcheck@latest" not in workflow
