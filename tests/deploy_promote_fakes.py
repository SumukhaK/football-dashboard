"""Fake gcloud answers and verification records for the promote.sh tests.

A candidate that matches deploy/.env.deploy as the test harness writes it,
built field by field so one test can change exactly one value.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_deploy_behaviour import PROJECT, REVISION

DIGEST_ARG = "sha256:deadbeef"
IMAGE = f"example-region-docker.pkg.dev/{PROJECT}/football-dashboard/console"
RECORD = "record.txt"

EXPECTED_ENV = {
    "SOURCE": "gcp",
    "GCP_PROJECT_ID": PROJECT,
    "API_SERVICE_NAME": "example-api",
    "CACHE_TTL_SECONDS": "60",
    "AUTH_MODE": "google",
    "AUTH_PUBLIC_ORIGIN": "https://console.example",
    "AUTH_CALLBACK_URL": "https://console.example/auth/callback",
    "OWNER_EMAIL": "owner@example.com",
    "GOOGLE_CLIENT_ID": "12345-example.apps.googleusercontent.com",
    "INVITES_ENABLED": "false",
}
EXPECTED_SECRETS = {
    "GOOGLE_CLIENT_SECRET": ("google-client-secret", "3"),
    "SESSION_SIGNING_KEY": ("session-signing-key", "4"),
    "OAUTH_SIGNING_KEY": ("oauth-signing-key", "5"),
}
GOOD_RECORD = {
    "revision": REVISION,
    "digest": DIGEST_ARG,
    "signed_out_denied": "signed-out window sent to /auth/login, no data, 14:02 IST",
    "partial_session_denied": "expired and re-signed cookies both got 401, 14:05",
    "owner_allowed": "owner account saw Overview with data, 14:08",
    "non_owner_denied": "tester1 denied at callback before any read, 14:10",
    "privacy_checks": "no token in page source or logs; outage page generic",
}


def _answer(pattern: str, value: str) -> str:
    """One fake case branch that prints value for calls containing pattern."""
    return f'  *"{pattern}"*) printf \'%s\\n\' "{value}" ;;\n'


def candidate(
    *,
    image: str = f"{IMAGE}@{DIGEST_ARG}",
    ready: str = "True",
    env: dict[str, str] | None = None,
    secrets: dict[str, tuple[str, str]] | None = None,
) -> str:
    """Fake reads for a candidate; every field matches the config by default."""
    values = {**EXPECTED_ENV, **(env or {})}
    bound = {**EXPECTED_SECRETS, **(secrets or {})}
    cases = _answer("containers[0].image", image)
    cases += _answer("conditions", ready)
    for name, value in values.items():
        cases += _answer(f"name={name}).extract(value)", value)
    for name, (secret, version) in bound.items():
        cases += _answer(f"name={name}).extract(valueFrom.secretKeyRef.name)", secret)
        cases += _answer(f"name={name}).extract(valueFrom.secretKeyRef.key)", version)
    return cases


def write_record(root: Path, **changes: str) -> None:
    """Write the verification record promote.sh reads, with optional changes."""
    fields = {**GOOD_RECORD, **changes}
    text = "".join(f"{key}={value}\n" for key, value in fields.items())
    (root / RECORD).write_text(text, encoding="utf-8")
