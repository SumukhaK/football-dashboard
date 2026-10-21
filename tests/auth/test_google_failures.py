"""GoogleOIDC fails closed: provider outages, malformed documents and leak-free errors."""

from __future__ import annotations

import logging
import traceback
from typing import Any

import httpx
import pytest

from app.services.auth import AuthFailure
from tests.auth.google_helpers import (
    failure,
    ready,
    run,
)
from tests.auth.support import (
    FakeGoogle,
    build_provider,
)


def test_a_provider_outage_fails_closed() -> None:
    """A timeout is a generic retry, never an unauthenticated session."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.outage = httpx.ConnectError("no route to host")

    assert failure(provider, start).kind == "provider"


@pytest.mark.parametrize(
    "token_body",
    [
        {"access_token": "fake-access-token", "token_type": "Bearer"},
        {"id_token": "not-a-jwt"},
        {"id_token": ""},
    ],
    ids=["no-id-token", "not-a-jwt", "empty-id-token"],
)
def test_a_malformed_token_response_is_refused(token_body: dict[str, Any]) -> None:
    """Anything that is not a validated ID token is refused."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_body = token_body

    assert failure(provider, start).kind == "provider"


def test_an_unavailable_jwks_fails_closed() -> None:
    """An unknown key set is an outage, not a reason to skip the signature."""
    fake = FakeGoogle(jwks_status=503)
    provider = build_provider(fake)
    start = ready(fake, provider)

    assert failure(provider, start).kind == "provider"


def test_a_failure_never_carries_the_code_verifier_or_tokens() -> None:
    """The generic category is all that leaves the adapter."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_body = {"id_token": "not-a-jwt"}

    error = failure(provider, start)

    assert str(error) == "provider"
    assert start.transaction.code_verifier not in str(error)
    assert "fake-code" not in str(error)
    assert "fake-access-token" not in str(error)


PRIVATE_MARKER = "PRIVATE_PROVIDER_PAYLOAD_SENTINEL"


def rendered(error: BaseException) -> str:
    """Everything a normal traceback or log record could show for this error."""
    return " ".join(
        (str(error), repr(error), "".join(traceback.format_exception(error)))
    )


def test_a_discovery_failure_renders_no_provider_detail() -> None:
    """A transport error's own text never survives the adapter boundary."""
    fake = FakeGoogle()
    fake.outage = httpx.ConnectError(f"{PRIVATE_MARKER} fetching discovery")
    provider = build_provider(fake)

    with pytest.raises(AuthFailure) as caught:
        run(provider.start("/"))

    assert caught.value.kind == "provider"
    assert PRIVATE_MARKER not in rendered(caught.value)
    assert caught.value.__cause__ is None


def test_an_exchange_failure_renders_no_provider_detail() -> None:
    """The token endpoint's description, code and token are not chained."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_status = 400
    fake.token_error_body = {
        "error": "invalid_grant",
        "error_description": f"{PRIVATE_MARKER} fake-code test-access-token",
    }

    error = failure(provider, start)

    assert error.kind == "provider"
    text = rendered(error)
    assert PRIVATE_MARKER not in text
    assert "fake-code" not in text
    assert "test-access-token" not in text
    assert start.transaction.code_verifier not in text
    assert error.__cause__ is None


def test_a_logged_provider_failure_carries_no_provider_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The normal exception logger is safe too, not only str(error)."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_status = 400
    fake.token_error_body = {
        "error": "invalid_grant",
        "error_description": PRIVATE_MARKER,
    }

    error = failure(provider, start)
    with caplog.at_level(logging.ERROR):
        logging.getLogger("app.auth").error("sign-in failed: %s", error, exc_info=error)

    assert PRIVATE_MARKER not in caplog.text


@pytest.mark.parametrize(
    "value",
    [None, True, 1, [], {}],
    ids=["null", "boolean", "number", "array", "object"],
)
def test_a_non_string_id_token_is_refused(value: object) -> None:
    """Only a non-empty string is an ID token; nothing is coerced to one."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    fake.token_body = {"access_token": "fake-access-token", "id_token": value}

    assert failure(provider, start).kind == "provider"


def test_a_malformed_discovery_document_is_refused() -> None:
    """Discovery must be an object; a list is a generic provider failure."""
    fake = FakeGoogle(discovery_body=[])
    provider = build_provider(fake)

    with pytest.raises(AuthFailure) as caught:
        run(provider.start("/"))

    assert caught.value.kind == "provider"
    assert PRIVATE_MARKER not in rendered(caught.value)


@pytest.mark.parametrize(
    "body",
    [{}, {"keys": None}],
    ids=["missing-keys", "null-keys"],
)
def test_a_malformed_jwks_is_refused(body: dict[str, Any]) -> None:
    """An unusable key set is a provider failure, not an empty success."""
    fake = FakeGoogle(jwks_body=body)
    provider = build_provider(fake)
    start = ready(fake, provider)

    assert failure(provider, start).kind == "provider"


@pytest.mark.parametrize("value", [True, False], ids=["true", "false"])
def test_a_boolean_issued_at_is_refused(value: bool) -> None:
    """OpenID's NumericDate is an integer; joserfc 1.7.7 accepts a bool."""
    fake = FakeGoogle()
    provider = build_provider(fake)
    start = ready(fake, provider)
    # set after ready(): that helper replaces the override dict with the nonce.
    fake.id_token_overrides["iat"] = value

    assert failure(provider, start).kind == "provider"
