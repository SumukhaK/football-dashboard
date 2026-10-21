"""Tests for the Google adapter: real OpenID validation, fake HTTP and keys.

Nothing here reaches Google. The discovery document, JWKS and token endpoint
are served by an ``httpx.MockTransport``, and the ID tokens are signed by a
local RSA key published as that JWKS, so Authlib performs its real signature,
algorithm, issuer, audience and nonce validation.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.auth.google import parse_callback, safe_return_path
from app.domain.auth import VerifiedIdentity
from app.services.auth import AuthFailure
from tests.auth.google_helpers import (
    OWNER,
    failure,
    finish,
    ready,
    run,
    started,
)
from tests.auth.support import (
    CALLBACK,
    CLIENT_ID,
    NOW,
    FakeGoogle,
    build_provider,
    pkce_challenge,
)


def test_building_the_provider_makes_no_network_calls() -> None:
    """Discovery, JWKS and tokens are fetched lazily, never at construction."""
    fake = FakeGoogle()

    build_provider(fake)

    assert fake.requests == []


def test_start_builds_a_pkce_authorization_url() -> None:
    """The URL carries our state, nonce, S256 challenge and configured callback."""
    fake = FakeGoogle()
    provider = build_provider(fake)

    start = started(provider, "/requests?window=24")
    query = parse_qs(urlsplit(start.authorization_url).query)

    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["scope"] == ["openid email"]
    assert query["state"] == [start.transaction.state]
    assert query["nonce"] == [start.transaction.nonce]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [pkce_challenge(start.transaction.code_verifier)]
    assert "access_type" not in query  # no offline access or refresh token
    assert start.transaction.return_path == "/requests?window=24"
    assert start.transaction.is_valid_at(NOW)


def test_each_start_gets_fresh_values() -> None:
    """State, nonce and verifier are generated per attempt, not reused."""
    tokens = [f"{letter}" * 20 for letter in "abcdef"]
    provider = build_provider(FakeGoogle(), tokens=tokens)

    first = started(provider)
    second = started(provider)
    values = (
        first.transaction.state,
        first.transaction.nonce,
        first.transaction.code_verifier,
        second.transaction.state,
        second.transaction.nonce,
        second.transaction.code_verifier,
    )

    assert len(set(values)) == 6


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("/requests?window=24", "/requests?window=24"),
        ("/", "/"),
        ("", "/"),
        ("https://evil.example", "/"),
        ("//evil.example", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("/path\nnext", "/"),
    ],
)
def test_the_return_path_stays_on_this_site(given: str, expected: str) -> None:
    """A return path is a local path or the root, never another origin."""
    assert safe_return_path(given) == expected


def test_a_discovery_failure_fails_closed() -> None:
    """A broken provider is a generic failure, not a crash or a bypass."""
    fake = FakeGoogle(discovery_status=503)
    provider = build_provider(fake)

    with pytest.raises(AuthFailure) as caught:
        run(provider.start("/"))

    assert caught.value.kind == "provider"


def test_callback_parameters_are_parsed_and_duplicates_refused() -> None:
    """Absent, empty or duplicated security parameters never reach the exchange."""
    assert parse_callback("code=abc&state=xyz") == ("abc", "xyz")

    for query in (
        "",
        "state=xyz",
        "code=abc",
        "code=&state=xyz",
        "code=abc&state=",
        "code=a&code=b&state=xyz",
        "code=abc&state=x&state=y",
    ):
        with pytest.raises(AuthFailure):
            parse_callback(query)

    with pytest.raises(AuthFailure) as caught:
        parse_callback("error=access_denied&state=xyz")
    assert caught.value.kind == "cancelled"


def test_the_verified_owner_is_accepted() -> None:
    """The happy path: bound state, exchanged code, validated ID token."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)

    identity = finish(provider, start)

    assert identity == VerifiedIdentity(
        subject="1234567890", email=OWNER, email_verified=True
    )
    assert not hasattr(identity, "access_token")
    assert not hasattr(provider, "token")


def test_a_callback_with_the_wrong_state_never_talks_to_the_provider() -> None:
    """State is checked before the code exchange, so a forgery costs nothing."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    before = len(fake.requests)

    with pytest.raises(AuthFailure) as caught:
        run(provider.finish("fake-code", "another-state", start.transaction))

    assert caught.value.kind == "state"
    assert len(fake.requests) == before


def test_an_expired_transaction_is_refused() -> None:
    """Five minutes is a window, not a suggestion: the clock decides."""
    fake = FakeGoogle()
    start = ready(fake, build_provider(fake))
    late = build_provider(fake, clock=lambda: NOW + timedelta(seconds=301))

    with pytest.raises(AuthFailure) as caught:
        finish(late, start)

    assert caught.value.kind == "expired"


def test_a_bad_pkce_verifier_is_refused() -> None:
    """Google rejects the exchange when the verifier does not match; so do we."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.expected_verifier = "a-different-verifier"

    assert failure(provider, start).kind == "provider"


def test_another_email_is_refused() -> None:
    """One verified account, compared exactly: no other Google user gets in."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.id_token_overrides["email"] = "someone.else@example.com"

    assert failure(provider, start).kind == "identity"


@pytest.mark.parametrize(
    "verified",
    [False, None, "true", 1],
    ids=["false", "missing", "string", "int"],
)
def test_email_verification_must_be_boolean_true(verified: object) -> None:
    """Only a boolean true counts; a string "true" or a missing claim does not."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    if verified is None:
        fake.omit_claims = ("email_verified",)
    else:
        fake.id_token_overrides["email_verified"] = verified

    assert failure(provider, start).kind == "identity"


def test_a_token_without_a_subject_is_not_an_identity() -> None:
    """A stable Google subject is required: an empty one never becomes a user."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.id_token_overrides["sub"] = ""

    assert failure(provider, start).kind == "identity"


def test_a_token_missing_the_required_subject_claim_is_refused() -> None:
    """The library refuses a token missing a required claim before we see it."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.omit_claims = ("sub",)

    assert failure(provider, start).kind == "provider"


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example"},
        {"aud": "someone-else.apps.googleusercontent.com"},
        {"azp": "someone-else.apps.googleusercontent.com"},
        {"nonce": "another-nonce"},
    ],
    ids=["issuer", "audience", "authorized-party", "nonce"],
)
def test_a_token_for_another_flow_is_refused(overrides: dict[str, Any]) -> None:
    """Issuer, audience, authorized party and nonce are all checked."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.id_token_overrides.update(overrides)

    assert failure(provider, start).kind == "provider"


def test_a_token_signed_by_another_key_is_refused() -> None:
    """Signature verification is the library's, with the published JWKS."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_body = {
        "access_token": "fake-access-token",
        "token_type": "Bearer",
        "id_token": fake.id_token(signer=fake.other_key),
    }

    assert failure(provider, start).kind == "provider"


def test_an_algorithm_outside_the_published_set_is_refused() -> None:
    """Google publishes RS256 here; a token signed another way is not ours."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_body = {
        "access_token": "fake-access-token",
        "token_type": "Bearer",
        "id_token": fake.id_token(algorithm="RS512"),
    }

    assert failure(provider, start).kind == "provider"


def test_an_expired_token_is_refused() -> None:
    """The library checks exp; a stale ID token is not a sign-in."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.id_token_overrides.update({"iat": 1_000_000, "exp": 1_000_100})

    assert failure(provider, start).kind == "provider"


def test_a_token_issued_in_the_future_is_refused() -> None:
    """A token that is not valid yet is refused, not cached for later."""
    import time

    now = int(time.time())
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.id_token_overrides.update({"iat": now + 600, "exp": now + 900})

    assert failure(provider, start).kind == "provider"
