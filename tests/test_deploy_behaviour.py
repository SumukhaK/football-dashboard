"""Behavioural tests for the deploy scripts, run against a recording gcloud.

The scripts are executed as real bash processes with a fake `gcloud` first on
PATH, so these tests see the commands that would reach Google Cloud rather than
the text of the script. They cover the two latent redeploy defects: the invoker
IAM check is asked for explicitly, and a deploy promotes the revision it made
instead of leaving traffic on a rolled-back one.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.config import REPO_ROOT

DEPLOY = REPO_ROOT / "deploy"
PROJECT = "example-console-project"
CUSTOM_ROLE = f"projects/{PROJECT}/roles/footballDashboardTraceReader"
# A real POSIX bash first. Windows also answers to "bash" with a WSL launcher,
# which is why the probe below, not the name, decides whether a candidate is used.
BASH_CANDIDATES = (
    "C:/Program Files/Git/bin/bash.exe",
    "/usr/bin/bash",
    "/bin/bash",
    "/usr/local/bin/bash",
    "bash",
)

# What the probe bash has to be able to run: a script that reaches a second
# script through a line continuation, which is how the deploy scripts are written.
PROBE_COMMAND = '#!/usr/bin/env bash\nprintf "<%s>" "$@"\n'
PROBE_SCRIPT = (
    "#!/usr/bin/env bash\n"
    'here="$(cd "$(dirname "$0")" && pwd)"\n'
    'chmod +x "${here}/bin/probe-cmd" 2>/dev/null || true\n'
    'PATH="${here}/bin:${PATH}" probe-cmd one \\\n'
    "  two three\n"
)

# Answers the fake gcloud gives, as extra case branches. A missing answer means
# the call succeeds with no output, which is the normal case for a create.
REPO_ABSENT = '  *"artifacts repositories describe"*) exit 1 ;;\n'
SA_ABSENT = '  *"iam service-accounts describe"*) exit 1 ;;\n'
ROLE_ABSENT = '  *"iam roles describe"*) exit 1 ;;\n'
OLD_BINDING = (
    '  *"projects get-iam-policy"*) printf \'%s\\n\' "roles/cloudtrace.user" ;;\n'
)
DIGEST = (
    '  *"artifacts docker images describe"*) printf \'%s\\n\' "sha256:deadbeef" ;;\n'
)
BUILD_OK = '  *"builds submit"*) printf \'%s\\n\' "fake: build finished" ;;\n'
BUILD_FAILS = (
    '  *"builds submit"*) printf \'%s\\n\' "fake: BUILD FAILED" >&2; exit 1 ;;\n'
)
DEPLOY_OK = '  *"run deploy"*) printf \'%s\\n\' "fake: revision deployed" ;;\n'
DEPLOY_FAILS = (
    '  *"run deploy"*) printf \'%s\\n\' "fake: DEPLOY FAILED" >&2; exit 1 ;;\n'
)
TRAFFIC_OK = '  *"run services update-traffic"*) printf \'%s\\n\' "fake: traffic" ;;\n'
TRAFFIC_FAILS = (
    '  *"run services update-traffic"*) printf \'%s\\n\' "fake: TRAFFIC FAILED" >&2; '
    "exit 1 ;;\n"
)
INVOKER_DISABLED = '  *"run services describe"*) printf \'%s\\n\' "true" ;;\n'
POLICY_PUBLIC = '  *"run services get-iam-policy"*) printf \'%s\\n\' "allUsers" ;;\n'
RUN_POLICY_READ_FAILS = (
    '  *"run services get-iam-policy"*) '
    'printf "%s\\n" "fake: policy read failed" >&2; exit 42 ;;\n'
)
PROJECT_POLICY_READ_FAILS = (
    '  *"projects get-iam-policy"*) '
    'printf "%s\\n" "fake: project policy read failed" >&2; exit 42 ;;\n'
)
BINDING_FAILS = (
    '  *"projects add-iam-policy-binding"*) printf \'%s\\n\' "fake: BINDING FAILED" >&2; '
    "exit 1 ;;\n"
)

FAKE_GCLOUD = """#!/usr/bin/env bash
# Test double: records every call, then answers from the table below.
printf '%s\\n' "$*" >>"${FAKE_GCLOUD_LOG}"
case "$*" in
@CASES@  *) ;;
esac
exit 0
"""

# Bash resolves these paths itself, so nothing Windows-shaped is ever handed to
# it as an argument: that is what makes this work on Git Bash as well as Linux.
RUNNER = """#!/usr/bin/env bash
# Harness runner: every path below is relative to this file.
here="$(cd "$(dirname "$0")" && pwd)"
chmod +x "${here}/bin/gcloud" 2>/dev/null || true
export PATH="${here}/bin:${PATH}"
export FAKE_GCLOUD_LOG="${here}/gcloud.log"
if [ "${1}" = "--fake-probe" ]; then
  command -v gcloud
  gcloud --version
  exit $?
fi
exec bash "${here}/repo/deploy/${1}"
"""


def _find_bash() -> str | None:
    """A bash that runs a copied script properly, or None when there is none.

    The probe is deliberately the capability these tests need: run a script file
    that calls another script through a line continuation. Windows ships a WSL
    launcher named bash that answers a trivial command but mangles that, and a
    test double that never runs would let a test pass while proving nothing.
    """
    for raw in BASH_CANDIDATES:
        candidate = shutil.which(raw)
        if candidate is None and Path(raw).exists():
            candidate = raw
        if candidate is not None and _bash_runs_a_script(candidate):
            return candidate
    return None


def _bash_runs_a_script(candidate: str) -> bool:
    """True when this bash runs PROBE_SCRIPT exactly as the deploy scripts need."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        (root / "bin").mkdir()
        (root / "bin" / "probe-cmd").write_text(
            PROBE_COMMAND, encoding="utf-8", newline="\n"
        )
        (root / "probe.sh").write_text(PROBE_SCRIPT, encoding="utf-8", newline="\n")
        try:
            probe = subprocess.run(
                [candidate, "probe.sh"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return False
    return probe.returncode == 0 and probe.stdout.strip() == "<one><two><three>"


BASH = _find_bash()
pytestmark = pytest.mark.skipif(
    BASH is None,
    reason="needs a POSIX bash to run the deploy scripts; CI runs these on ubuntu",
)


def _bash() -> str:
    """The bash these tests run the scripts with."""
    assert BASH is not None
    return BASH


class Scripts:
    """A copied deploy tree, a fake gcloud, and the calls that were recorded."""

    def __init__(self, tmp_path: Path, cases: str) -> None:
        self.root = tmp_path
        self.repo = tmp_path / "repo"
        self.deploy = self.repo / "deploy"
        self.deploy.mkdir(parents=True)
        for name in ("deploy.sh", "setup_service_account.sh", "trace-reader-role.yaml"):
            shutil.copy(DEPLOY / name, self.deploy / name)
        self.deploy.joinpath(".env.deploy").write_text(
            f"GCP_PROJECT_ID={PROJECT}\n"
            "REGION=example-region\n"
            "API_SERVICE_NAME=example-api\n"
            "SERVICE_NAME=football-dashboard\n"
            "REPOSITORY=football-dashboard\n",
            encoding="utf-8",
        )
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.fake = self.bin / "gcloud"
        self.fake.write_text(
            FAKE_GCLOUD.replace("@CASES@", cases), encoding="utf-8", newline="\n"
        )
        self.log = tmp_path / "gcloud.log"
        self.log.write_text("", encoding="utf-8")
        tmp_path.joinpath("run.sh").write_text(RUNNER, encoding="utf-8", newline="\n")
        self._assert_the_fake_shadows_the_real_gcloud()

    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the harness runner, which spawns the script under test."""
        return subprocess.run(
            [_bash(), "run.sh", *args],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=False,
        )

    def _assert_the_fake_shadows_the_real_gcloud(self) -> None:
        """Refuse to run if a call would reach the real gcloud instead."""
        probe = self._invoke("--fake-probe")
        recorded = self.log.read_text(encoding="utf-8")
        if "gcloud" not in probe.stdout or not recorded.strip():
            raise AssertionError(
                f"the fake gcloud did not run, so this test cannot trust the calls it "
                f"sees: {probe.stdout!r} {probe.stderr!r}"
            )
        self.log.write_text("", encoding="utf-8")

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        """Run one script with the fake gcloud first on PATH."""
        return self._invoke(script)

    def calls(self) -> list[str]:
        """The gcloud invocations, in order."""
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip()]


def _index(calls: list[str], needle: str) -> int:
    """Where the one call containing needle sits in the sequence."""
    found = [position for position, call in enumerate(calls) if needle in call]
    assert len(found) == 1, f"expected exactly one {needle!r} call, got {found}"
    return found[0]


# --- setup_service_account.sh ------------------------------------------------


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
    assert _index(calls, "iam roles create") < _index(calls, CUSTOM_ROLE)


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


# --- deploy.sh ---------------------------------------------------------------


def test_deploy_asks_for_both_privacy_controls(tmp_path: Path) -> None:
    """allUsers off, and the separate invoker IAM check explicitly on."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
    )
    scripts.run("deploy.sh")

    deploy = [c for c in scripts.calls() if "run deploy" in c]
    assert len(deploy) == 1
    assert "--no-allow-unauthenticated" in deploy[0]
    assert "--invoker-iam-check" in deploy[0]
    assert "--no-invoker-iam-check" not in deploy[0]


def test_deploy_keeps_the_digest_and_the_reader_identity(tmp_path: Path) -> None:
    """The private identity and the pinned digest survive the extra steps."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
    )
    scripts.run("deploy.sh")

    deploy = next(c for c in scripts.calls() if "run deploy" in c)
    assert "console@sha256:deadbeef" in deploy
    assert f"football-dashboard-reader@{PROJECT}.iam.gserviceaccount.com" in deploy


def test_deploy_updates_the_settings_it_owns_rather_than_replacing_them(
    tmp_path: Path,
) -> None:
    """Settings the script does not name must survive a later deploy.

    --set-env-vars replaces a service's whole environment, so a redeploy would
    silently drop anything added by hand, such as the crashed-app settings the
    crashes page needs. --update-env-vars merges the four this script owns into
    what is already there and leaves the rest alone.
    """
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
    )
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
    ):
        assert setting in deploy, setting


def test_deploy_promotes_the_revision_it_just_deployed(tmp_path: Path) -> None:
    """A rollback pins traffic; deploying again must serve the new revision."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
    )
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    calls = scripts.calls()
    traffic = [c for c in calls if "update-traffic" in c]
    assert len(traffic) == 1
    assert "--to-latest" in traffic[0]
    assert _index(calls, "run deploy") < _index(calls, "update-traffic")
    assert "gcloud run services proxy" in result.stdout


def test_deploy_issues_nothing_after_a_failed_build(tmp_path: Path) -> None:
    """A build that fails stops before the deployment and any traffic change."""
    scripts = Scripts(tmp_path, REPO_ABSENT + DIGEST + BUILD_FAILS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    calls = scripts.calls()
    assert [c for c in calls if "run deploy" in c] == []
    assert [c for c in calls if "update-traffic" in c] == []
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_does_not_move_traffic_when_the_deploy_fails(tmp_path: Path) -> None:
    """A failed deployment leaves the traffic assignment alone."""
    scripts = Scripts(tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_FAILS)
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert [c for c in scripts.calls() if "update-traffic" in c] == []
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_fails_loudly_when_traffic_cannot_be_moved(tmp_path: Path) -> None:
    """Promotion failing must not look like a successful deploy."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_FAILS
    )
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_refuses_to_report_success_when_the_invoker_check_is_off(
    tmp_path: Path,
) -> None:
    """A target that had invoker checking disabled stays public without this."""
    scripts = Scripts(
        tmp_path,
        REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK + INVOKER_DISABLED,
    )
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "invoker" in result.stderr.lower()
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_refuses_to_report_success_when_all_users_is_bound(
    tmp_path: Path,
) -> None:
    """The other public-access mechanism is checked too."""
    scripts = Scripts(
        tmp_path,
        REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK + POLICY_PUBLIC,
    )
    result = scripts.run("deploy.sh")

    assert result.returncode != 0
    assert "allUsers" in result.stderr
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_aborts_when_the_policy_read_fails(tmp_path: Path) -> None:
    """A failed read must not pass for "no allUsers binding"."""
    scripts = Scripts(
        tmp_path,
        REPO_ABSENT
        + DIGEST
        + BUILD_OK
        + DEPLOY_OK
        + TRAFFIC_OK
        + RUN_POLICY_READ_FAILS,
    )
    result = scripts.run("deploy.sh")

    assert "fake: policy read failed" in result.stderr
    assert result.returncode != 0
    assert "gcloud run services proxy" not in result.stdout


def test_deploy_reports_success_only_when_both_controls_hold(tmp_path: Path) -> None:
    """The happy path ends with the proxy command."""
    scripts = Scripts(
        tmp_path, REPO_ABSENT + DIGEST + BUILD_OK + DEPLOY_OK + TRAFFIC_OK
    )
    result = scripts.run("deploy.sh")

    assert result.returncode == 0, result.stderr
    assert "gcloud run services proxy" in result.stdout
    assert "run services get-iam-policy" in " ".join(scripts.calls())
