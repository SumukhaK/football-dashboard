"""A recording fake gcloud and the copied deploy tree the script tests run in.

The scripts are executed as real bash processes with a fake `gcloud` first on
PATH, so the tests see the commands that would reach Google Cloud rather than
the text of the script.
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
BUILD_ID = "00000000-0000-4000-8000-000000000001"
REVISION = f"football-dashboard-{BUILD_ID}"
OLD_BINDING = (
    '  *"projects get-iam-policy"*) printf \'%s\\n\' "roles/cloudtrace.user" ;;\n'
)
DIGEST = (
    '  *"artifacts docker images describe"*) printf \'%s\\n\' "sha256:deadbeef" ;;\n'
)
BUILD_OK = (
    f'  *"builds submit"*) printf \'%s\\t%s\\n\' "{BUILD_ID}" ' '"sha256:deadbeef" ;;\n'
)
BUILD_FAILS = (
    '  *"builds submit"*) printf \'%s\\n\' "fake: BUILD FAILED" >&2; exit 1 ;;\n'
)
DEPLOY_OK = f'  *"run deploy"*) printf \'%s\\n\' "{REVISION}" ;;\n'
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

IMAGE = f"example-region-docker.pkg.dev/{PROJECT}/football-dashboard/console"
DIGEST_VALUE = "sha256:deadbeef"
READER = f"football-dashboard-reader@{PROJECT}.iam.gserviceaccount.com"
# What .env.deploy above configures, as a revision built from it carries it.
SETTINGS = {
    "SOURCE": "gcp",
    "GCP_PROJECT_ID": PROJECT,
    "API_SERVICE_NAME": "example-api",
    "AUTH_MODE": "google",
    "AUTH_PUBLIC_ORIGIN": "https://console.example",
    "AUTH_CALLBACK_URL": "https://console.example/auth/callback",
    "OWNER_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "12345-example.apps.googleusercontent.com",
    "INVITES_ENABLED": "false",
}
SECRETS = {
    "GOOGLE_CLIENT_SECRET": ("google-client-secret", "3"),
    "SESSION_SIGNING_KEY": ("session-signing-key", "4"),
    "OAUTH_SIGNING_KEY": ("oauth-signing-key", "5"),
}


def answer(pattern: str, value: str) -> str:
    """A fake gcloud case branch that prints one value for matching calls."""
    return f"  *{pattern}*) printf '%s\\n' \"{value}\" ;;\n"


def setting_read(name: str) -> str:
    """The pattern of a revision read for one plain environment setting."""
    return f'"revisions describe"*"filter(name={name}).extract(value)"'


def secret_read(name: str, part: str) -> str:
    """The pattern of a revision read for a secret binding's name or version."""
    return f'"revisions describe"*"filter(name={name}).extract(valueFrom.secretKeyRef.{part})"'


# Every read that verifies a revision against the configuration above, answered
# as a revision built by this configuration would answer it.
CANDIDATE_OK = (
    answer('"revisions describe"*"conditions"', "True")
    + answer('"revisions describe"*"containers[0].image)"', f"{IMAGE}@{DIGEST_VALUE}")
    + answer('"revisions describe"*"serviceAccountName"', READER)
    + "".join(answer(setting_read(name), value) for name, value in SETTINGS.items())
    + "".join(
        answer(secret_read(name, "name"), secret)
        + answer(secret_read(name, "key"), version)
        for name, (secret, version) in SECRETS.items()
    )
    + answer('"secrets versions describe"', "ENABLED")
    + '  *"traffic[].tag"*) ;;\n'
)
AUTH_MODE_ABSENT = '  *"revisions describe"*"AUTH_MODE"*) ;;\n'
REVISION_NOT_READY = (
    '  *"revisions describe"*"conditions"*) printf \'%s\\n\' "False" ;;\n'
)
BINDING_ABSENT = '  *"revisions describe"*"secretKeyRef"*) ;;\n'
# A tag on an older revision is only reported until the removal is recorded.
TAGS_PRESENT = (
    '  *"traffic[].tag"*)\n'
    '    if grep -q "remove-tags" "${FAKE_GCLOUD_LOG}"; then :; '
    "else printf '%s\\n' \"candidate\"; fi ;;\n"
)
TAGS_READ_FAILS = (
    '  *"traffic[].tag"*) ' 'printf "%s\\n" "fake: tags read failed" >&2; exit 42 ;;\n'
)
BINDING_ADD_FAILS = (
    '  *"run services add-iam-policy-binding"*) '
    "printf '%s\\n' \"fake: BINDING FAILED\" >&2; exit 1 ;;\n"
)
# The policy is empty until the binding call is recorded, which is what the
# service-scoped readback after a public opt-in looks like.
PUBLIC_AFTER_BINDING = (
    '  *"run services get-iam-policy"*)\n'
    '    if grep -q "add-iam-policy-binding" "${FAKE_GCLOUD_LOG}"; then '
    "printf '%s\\n' \"allUsers\"; fi ;;\n"
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
script="${1:-}"
if [ $# -gt 0 ]; then shift; fi
exec bash "${here}/repo/deploy/${script}" "$@"
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
NEEDS_BASH = pytest.mark.skipif(
    BASH is None,
    reason="needs a POSIX bash to run the deploy scripts; CI runs these on ubuntu",
)


def _bash() -> str:
    """The bash these tests run the scripts with."""
    assert BASH is not None
    return BASH


DEPLOY_FILES = (
    "deploy.sh",
    "promote.sh",
    "rollback.sh",
    "lib.sh",
    "verification.sh",
    "setup_service_account.sh",
    "trace-reader-role.yaml",
)


def _deploy_env(transport: str, env_extra: str) -> str:
    """The .env.deploy a copied tree runs with."""
    return (
        f"GCP_PROJECT_ID={PROJECT}\n"
        "REGION=example-region\n"
        "API_SERVICE_NAME=example-api\n"
        "SERVICE_NAME=football-dashboard\n"
        "REPOSITORY=football-dashboard\n"
        f"DASHBOARD_TRANSPORT={transport}\n"
        "AUTH_PUBLIC_ORIGIN=https://console.example\n"
        "GOOGLE_CLIENT_ID=12345-example.apps.googleusercontent.com\n"
        "OWNER_EMAIL=owner@example.com\n"
        "GOOGLE_CLIENT_SECRET_VERSION=3\n"
        "SESSION_SIGNING_KEY_VERSION=4\n"
        "OAUTH_SIGNING_KEY_VERSION=5\n"
        f"{env_extra}"
    )


class Scripts:
    """A copied deploy tree, a fake gcloud, and the calls that were recorded."""

    def __init__(
        self,
        tmp_path: Path,
        cases: str,
        *,
        transport: str = "private",
        env_extra: str = "",
    ) -> None:
        self.root = tmp_path
        self.repo = tmp_path / "repo"
        self.deploy = self.repo / "deploy"
        self.deploy.mkdir(parents=True)
        for name in DEPLOY_FILES:
            shutil.copy(DEPLOY / name, self.deploy / name)
        self.deploy.joinpath(".env.deploy").write_text(
            _deploy_env(transport, env_extra), encoding="utf-8"
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

    def record(self, revision: str, text: str) -> None:
        """Write an operator verification record for one revision."""
        records = self.deploy / "verification"
        records.mkdir(exist_ok=True)
        records.joinpath(f"{revision}.env").write_text(text, encoding="utf-8")

    def run(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        """Run one script with the fake gcloud first on PATH."""
        return self._invoke(script, *args)

    def calls(self) -> list[str]:
        """The gcloud invocations, in order."""
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip()]


def index_of(calls: list[str], needle: str) -> int:
    """Where the one call containing needle sits in the sequence."""
    found = [position for position, call in enumerate(calls) if needle in call]
    assert len(found) == 1, f"expected exactly one {needle!r} call, got {found}"
    return found[0]


# Rollback targets: a revision read back with or without owner sign-in.
AUTH_ENABLED = '  *"revisions describe"*"AUTH_MODE"*) printf \'%s\\n\' "google" ;;\n'
AUTH_ABSENT_READ = '  *"revisions describe"*"AUTH_MODE"*) ;;\n'
REVISION_READ_FAILS = (
    '  *"revisions describe"*) '
    'printf "%s\\n" "fake: revision read failed" >&2; exit 42 ;;\n'
)
# Public until the removal is recorded, then private: this is what a real
# policy readback looks like across the two sides of remove-iam-policy-binding.
PUBLIC_UNTIL_REMOVED = (
    '  *"run services get-iam-policy"*)\n'
    '    if grep -q "remove-iam-policy-binding" "${FAKE_GCLOUD_LOG}"; then :; '
    "else printf '%s\\n' \"allUsers\"; fi ;;\n"
)

# An operator verification record for REVISION, as deploy/README.md asks for it.
RECORD = (
    f"REVISION={REVISION}\n"
    f"DIGEST={DIGEST_VALUE}\n"
    "SIGNED_OUT_DENIED=fresh browser got the sign-in page on / and /requests\n"
    "PARTIAL_DENIED=HTMX partials returned 401 with no data while signed out\n"
    "OWNER_ALLOWED=owner signed in through the tag URL and saw Overview\n"
    "NON_OWNER_DENIED=second Google account got the not-allowed page\n"
    "PRIVACY_CHECKED=no code, token or email in the request logs\n"
    "VERIFIED_BY=owner\n"
    "VERIFIED_AT=2026-10-21T10:00Z\n"
)
